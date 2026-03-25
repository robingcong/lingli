import hashlib
import os
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from apps.knowledge.rag_sync import RagKnowledgeSyncService


class _FakeEmbedder:
    def get_embeddings(self, texts, show_progress_bar=False):
        if isinstance(texts, str):
            texts = [texts]
        return [[0.1] * 1024 for _ in texts]


class _FakeVectorStore:
    def __init__(self):
        self.added = []

    def add_data(self, rows):
        self.added.extend(rows)


class _FakeDocumentStore:
    def __init__(self):
        self.documents = {}
        self.chunks = {}

    def get_by_source(self, source_path):
        return self.documents.get(source_path)

    def upsert_document(self, payload):
        document = dict(payload)
        document.setdefault("id", len(self.documents) + 1)
        self.documents[payload["source_path"]] = document
        return document

    def replace_chunks(self, source_path, chunks):
        self.chunks[source_path] = list(chunks)


class RagKnowledgeSyncTests(unittest.TestCase):
    def test_sync_sanitizes_4byte_unicode_before_persisting(self):
        with TemporaryDirectory() as temp_dir:
            rag_dir = os.path.join(temp_dir, "docs", "rag")
            os.makedirs(rag_dir, exist_ok=True)
            file_path = os.path.join(rag_dir, "emoji.md")
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write("普通文本🌟\n第二行")

            store = _FakeDocumentStore()
            vector_store = _FakeVectorStore()
            service = RagKnowledgeSyncService(
                base_dir=temp_dir,
                document_store=store,
                vector_store=vector_store,
                embedder=_FakeEmbedder(),
            )

            with patch("apps.knowledge.rag_sync.process_singel_file", return_value=["普通文本🌟", "第二行"]):
                summary = service.sync()

        self.assertEqual(summary["created"], 1)
        document = store.documents["docs/rag/emoji.md"]
        self.assertEqual(document["content"], "普通文本\n第二行")
        self.assertEqual(store.chunks["docs/rag/emoji.md"][0]["content"], "普通文本")
        self.assertEqual(vector_store.added[0]["content"], "普通文本")

    def test_sync_creates_document_and_chunk_records_for_new_rag_file(self):
        with TemporaryDirectory() as temp_dir:
            rag_dir = os.path.join(temp_dir, "docs", "rag")
            os.makedirs(rag_dir, exist_ok=True)
            file_path = os.path.join(rag_dir, "sample.md")
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write("第一段内容\n\n第二段内容")

            store = _FakeDocumentStore()
            vector_store = _FakeVectorStore()
            service = RagKnowledgeSyncService(
                base_dir=temp_dir,
                document_store=store,
                vector_store=vector_store,
                embedder=_FakeEmbedder(),
            )

            with patch("apps.knowledge.rag_sync.process_singel_file", return_value=["第一段内容", "第二段内容"]):
                summary = service.sync()

        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["skipped"], 0)
        doc = store.documents["docs/rag/sample.md"]
        self.assertEqual(doc["chunk_count"], 2)
        self.assertEqual(doc["content_hash"], hashlib.md5("第一段内容\n\n第二段内容".encode("utf-8")).hexdigest())
        self.assertEqual(len(store.chunks["docs/rag/sample.md"]), 2)
        self.assertEqual(len(vector_store.added), 2)

    def test_sync_skips_unchanged_file(self):
        with TemporaryDirectory() as temp_dir:
            rag_dir = os.path.join(temp_dir, "docs", "rag")
            os.makedirs(rag_dir, exist_ok=True)
            file_path = os.path.join(rag_dir, "sample.md")
            content = "第一段内容\n\n第二段内容"
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(content)

            content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
            store = _FakeDocumentStore()
            store.documents["docs/rag/sample.md"] = {
                "id": 1,
                "source_path": "docs/rag/sample.md",
                "content_hash": content_hash,
                "file_mtime": os.path.getmtime(file_path),
            }
            service = RagKnowledgeSyncService(
                base_dir=temp_dir,
                document_store=store,
                vector_store=_FakeVectorStore(),
                embedder=_FakeEmbedder(),
            )

            with patch("apps.knowledge.rag_sync.process_singel_file", return_value=["第一段内容", "第二段内容"]):
                summary = service.sync()

        self.assertEqual(summary["created"], 0)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
