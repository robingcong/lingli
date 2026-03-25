from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Any, Dict, List

from django.utils import timezone

from apps.core.milvus_helper import process_singel_file
from apps.core.models import KnowledgeChunk, KnowledgeDocument
from utils.logger_manager import get_logger


class DjangoKnowledgeDocumentStore:
    def get_by_source(self, source_path: str) -> KnowledgeDocument | None:
        return KnowledgeDocument.objects.filter(source_path=source_path).first()

    def upsert_document(self, payload: Dict[str, Any]) -> KnowledgeDocument:
        defaults = dict(payload)
        source_path = defaults.pop("source_path")
        obj, _ = KnowledgeDocument.objects.update_or_create(
            source_path=source_path,
            defaults=defaults,
        )
        return obj

    def replace_chunks(self, source_path: str, chunks: List[Dict[str, Any]]) -> None:
        document = KnowledgeDocument.objects.get(source_path=source_path)
        KnowledgeChunk.objects.filter(document=document).delete()
        KnowledgeChunk.objects.bulk_create(
            [
                KnowledgeChunk(
                    document=document,
                    chunk_id=item["chunk_id"],
                    chunk_index=item["chunk_index"],
                    content=item["content"],
                )
                for item in chunks
            ]
        )


class RagKnowledgeSyncService:
    """同步 docs/rag 下文档到 MySQL 与 Milvus。"""

    def __init__(self, base_dir: str, document_store=None, vector_store=None, embedder=None):
        self.base_dir = base_dir
        self.document_store = document_store or DjangoKnowledgeDocumentStore()
        self.vector_store = vector_store
        self.embedder = embedder
        self.logger = get_logger(self.__class__.__name__)

    def sync(self) -> Dict[str, int]:
        summary = {"created": 0, "updated": 0, "skipped": 0}
        for source_path in self._list_rag_files():
            abs_path = os.path.join(self.base_dir, source_path)
            with open(abs_path, "r", encoding="utf-8") as fh:
                raw_content = fh.read()
            content_hash = hashlib.md5(raw_content.encode("utf-8")).hexdigest()
            file_mtime = os.path.getmtime(abs_path)
            existing = self.document_store.get_by_source(source_path)
            existing_hash = (
                existing.get("content_hash")
                if isinstance(existing, dict)
                else getattr(existing, "content_hash", "")
            )
            if (
                existing
                and existing_hash == content_hash
            ):
                summary["skipped"] += 1
                continue

            content = self._sanitize_text_for_mysql(raw_content)
            chunk_texts = [
                self._sanitize_text_for_mysql(chunk_text)
                for chunk_text in self._extract_chunk_texts(abs_path)
            ]
            document = self.document_store.upsert_document(
                {
                    "source_path": source_path,
                    "title": os.path.basename(source_path),
                    "doc_type": os.path.splitext(source_path)[1],
                    "content": content,
                    "content_hash": content_hash,
                    "file_mtime": file_mtime,
                    "chunk_count": len(chunk_texts),
                    "status": "indexed",
                    "last_indexed_at": timezone.now(),
                }
            )
            document_doc_type = (
                document.get("doc_type")
                if isinstance(document, dict)
                else getattr(document, "doc_type", os.path.splitext(source_path)[1])
            )
            chunk_rows = [
                {
                    "chunk_id": f"{content_hash[:12]}-{index}",
                    "chunk_index": index,
                    "content": chunk_text,
                }
                for index, chunk_text in enumerate(chunk_texts)
            ]
            self.document_store.replace_chunks(source_path, chunk_rows)
            self._sync_vector_store(source_path, document_doc_type, chunk_rows)

            if existing:
                summary["updated"] += 1
            else:
                summary["created"] += 1
        return summary

    def _sanitize_text_for_mysql(self, value: str) -> str:
        if not value:
            return ""
        # Some deployments still reject 4-byte unicode in text columns even when the
        # table definition requests utf8mb4. Strip those characters to keep sync stable.
        return "".join(ch for ch in value if ch != "\x00" and ord(ch) <= 0xFFFF)

    def _list_rag_files(self) -> List[str]:
        rag_root = os.path.join(self.base_dir, "docs", "rag")
        rag_files = []
        if not os.path.isdir(rag_root):
            return rag_files
        for root, _, files in os.walk(rag_root):
            for file_name in files:
                abs_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(abs_path, self.base_dir)
                rag_files.append(rel_path.replace("\\", "/"))
        return sorted(rag_files)

    def _extract_chunk_texts(self, abs_path: str) -> List[str]:
        chunks = process_singel_file(abs_path)
        if not chunks:
            return []
        texts = []
        for chunk in chunks if isinstance(chunks, list) else [chunks]:
            texts.append(str(chunk.text) if hasattr(chunk, "text") else str(chunk))
        return texts

    def _sync_vector_store(self, source_path: str, doc_type: str, chunk_rows: List[Dict[str, Any]]) -> None:
        if not self.vector_store or not self.embedder or not chunk_rows:
            return
        if hasattr(self.vector_store, "delete_by_source"):
            self.vector_store.delete_by_source(source_path)
        embeddings = self.embedder.get_embeddings(
            [item["content"] for item in chunk_rows],
            show_progress_bar=False,
        )
        payload = []
        now = datetime.now().isoformat()
        for item, embedding in zip(chunk_rows, embeddings):
            payload.append(
                {
                    "embedding": embedding.tolist() if hasattr(embedding, "tolist") else embedding,
                    "content": item["content"],
                    "metadata": "{}",
                    "source": source_path,
                    "doc_type": doc_type,
                    "chunk_id": item["chunk_id"],
                    "upload_time": now,
                }
            )
        self.vector_store.add_data(payload)
