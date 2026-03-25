from __future__ import annotations

from typing import List

from langchain_core.documents import Document

from .vector_store import MilvusVectorStore


class KnowledgeRetriever:
    """Wrap vector-store hits as Documents for downstream ranking/building."""

    def __init__(self, vector_store: MilvusVectorStore):
        self.vector_store = vector_store

    def retrieve(self, query_vector, top_k: int) -> List[Document]:
        raw_results = self.vector_store.search(query_vector, top_k=top_k)
        documents: List[Document] = []
        for item in raw_results:
            content = str(item.get("content") or "")
            if not content:
                continue
            metadata = {
                "id": item.get("id"),
                "source": item.get("source") or "",
                "doc_type": item.get("doc_type") or "",
                "chunk_id": item.get("chunk_id") or "",
                "upload_time": item.get("upload_time") or "",
                "metadata": item.get("metadata"),
                "vector_score": float(item.get("score", 0.0)),
            }
            documents.append(Document(page_content=content, metadata=metadata))
        return documents
