from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict

from utils.logger_manager import get_logger

from .context_builder import KnowledgeContextBuilder
from .embedding import BGEM3Embedder
from .reranker import KnowledgeReranker
from .retriever import KnowledgeRetriever
from .schemas import RAGContextEnvelope, RAGContextResult
from .vector_store import MilvusVectorStore
from ..core.models import KnowledgeBase


class KnowledgeService:
    """知识库服务：整合向量存储和嵌入模型。"""

    def __init__(
        self,
        vector_store: MilvusVectorStore,
        embedder: BGEM3Embedder,
        rag_vector_store: MilvusVectorStore | None = None,
    ):
        self.vector_store = vector_store
        self.embedder = embedder
        self.logger = get_logger(self.__class__.__name__)
        self.retriever = KnowledgeRetriever(vector_store)
        self.reranker = KnowledgeReranker()
        self.context_builder = KnowledgeContextBuilder()
        self._embedding_cache: Dict[str, list[float]] = {}
        self._context_cache: Dict[tuple[Any, ...], RAGContextEnvelope] = {}

    def add_knowledge(self, title: str, content: str) -> int:
        """添加知识到向量库与MySQL。"""
        embedding = self.embedder.get_embeddings(content)[0]
        metadata = json.dumps({"title": title}, ensure_ascii=False)

        # 注意：Milvus集合字段必须与schema完全一致
        self.vector_store.add_documents([
            {
                "embedding": embedding,
                "content": content,
                "metadata": metadata,
                "source": title,
                "doc_type": "text",
                "chunk_id": str(uuid.uuid4()),
                "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ])

        knowledge = KnowledgeBase(title=title, content=content)
        knowledge.save()
        return knowledge.id

    def search_relevant_knowledge(
        self,
        query: str,
        top_k: int = 5,
        min_score_threshold: float = 0.5,
    ) -> str:
        """兼容旧接口：返回纯文本上下文。"""
        context_result = self.search_relevant_knowledge_context(
            query=query,
            top_k=top_k,
            min_score_threshold=min_score_threshold,
        )
        return context_result.plain_text

    def search_knowledge(self, query: str, top_k: int = 5) -> list[Dict[str, Any]]:
        """返回向量库直接命中的 chunk 结果，用于知识库检索页面。"""
        query_embedding = self.embedder.get_embeddings(query)[0]
        return self.vector_store.search(query_embedding, top_k=top_k)

    def search_relevant_knowledge_context(
        self,
        query: str,
        top_k: int = 5,
        min_score_threshold: float = 0.5,
        max_chars_per_chunk: int = 600,
        max_total_chars: int = 2400,
    ) -> RAGContextResult:
        envelope = self.search_relevant_knowledge_once(
            query=query,
            top_k=top_k,
            min_score_threshold=min_score_threshold,
            max_chars_per_chunk=max_chars_per_chunk,
            max_total_chars=max_total_chars,
        )
        return envelope.context_result

    def search_relevant_knowledge_once(
        self,
        query: str,
        top_k: int = 5,
        min_score_threshold: float = 0.5,
        max_chars_per_chunk: int = 600,
        max_total_chars: int = 2400,
    ) -> RAGContextEnvelope:
        """检索、重排并生成带引用的知识库上下文。"""
        started_at = time.perf_counter()
        normalized_query = self.normalize_query(query)
        cache_key = (
            normalized_query,
            top_k,
            min_score_threshold,
            max_chars_per_chunk,
            max_total_chars,
        )
        cached = self._context_cache.get(cache_key)
        if cached is not None:
            return RAGContextEnvelope(
                query=query,
                normalized_query=normalized_query,
                retrieval_mode=cached.retrieval_mode,
                confidence_level=cached.confidence_level,
                context_result=cached.context_result,
                top_scores=list(cached.top_scores),
                cache_hit=True,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )

        query_embedding = self.get_query_embedding_cached(normalized_query)
        self.logger.info(
            "知识库查询context: '%s'\n向量维度: %s\n",
            query,
            len(query_embedding),
        )

        search_k = max(top_k * 4, 10)
        documents = self.retriever.retrieve(query_embedding, top_k=search_k)
        top_scores = [
            round(float((doc.metadata or {}).get("vector_score", 0.0)), 4)
            for doc in documents[:5]
        ]
        self.logger.info(
            "知识库原始召回结果: count=%s, top_scores=%s",
            len(documents),
            top_scores,
        )
        rerank_needed, confidence_level = self.should_rerank(documents)
        retrieval_mode = "rerank" if rerank_needed else "fast"
        if rerank_needed:
            rerank_limit = max(top_k * 3, 8)
            reranked = self.reranker.rerank(
                documents=documents[:rerank_limit],
                query=query,
                top_k=top_k,
                min_score_threshold=min_score_threshold,
            )
            self.logger.info("知识库BM25混合重排后结果: %s", reranked[:top_k])
        else:
            reranked = self._documents_to_chunks(documents[:top_k])

        context_result = self.context_builder.build(
            query=query,
            ranked_chunks=reranked,
            max_chars_per_chunk=max_chars_per_chunk,
            max_total_chars=max_total_chars,
        )
        self.logger.info("知识库前 top_k 结果: %s", context_result.citations)
        envelope = RAGContextEnvelope(
            query=query,
            normalized_query=normalized_query,
            retrieval_mode=retrieval_mode,
            confidence_level=confidence_level,
            context_result=context_result,
            top_scores=top_scores,
            cache_hit=False,
            latency_ms=round((time.perf_counter() - started_at) * 1000, 3),
        )
        self._context_cache[cache_key] = envelope
        return envelope

    def normalize_query(self, query: str) -> str:
        text = re.sub(r"\s+", " ", str(query or "")).strip()
        return text.lower()

    def get_query_embedding_cached(self, normalized_query: str) -> list[float]:
        cached = self._embedding_cache.get(normalized_query)
        if cached is not None:
            return cached
        embedding = self.embedder.get_embeddings(normalized_query)[0]
        self._embedding_cache[normalized_query] = embedding
        return embedding

    def should_rerank(self, documents) -> tuple[bool, str]:
        scores = [float((doc.metadata or {}).get("vector_score", 0.0)) for doc in documents[:3]]
        if not scores:
            return False, "low"
        top1 = scores[0]
        top2 = scores[1] if len(scores) > 1 else 0.0
        avg_top3 = sum(scores[:3]) / len(scores[:3])
        passed = sum(
            [
                top1 >= 0.78,
                (top1 - top2) >= 0.08,
                avg_top3 >= 0.72,
            ]
        )
        if passed >= 2:
            return False, "high"
        if top1 >= 0.68:
            return True, "medium"
        return True, "low"

    def _documents_to_chunks(self, documents):
        return self.reranker._to_chunks(documents) if hasattr(self.reranker, "_to_chunks") else [
            self._document_to_chunk(doc) for doc in documents
        ]

    def _document_to_chunk(self, document):
        metadata = dict(document.metadata or {})
        raw_metadata = metadata.get("metadata")
        if isinstance(raw_metadata, str):
            try:
                parsed_metadata = json.loads(raw_metadata)
            except json.JSONDecodeError:
                parsed_metadata = {"raw": raw_metadata}
        elif isinstance(raw_metadata, dict):
            parsed_metadata = raw_metadata
        else:
            parsed_metadata = {}

        from .schemas import RetrievedChunk

        return RetrievedChunk(
            content=str(document.page_content or ""),
            source=str(metadata.get("source") or ""),
            chunk_id=str(metadata.get("chunk_id") or ""),
            doc_type=str(metadata.get("doc_type") or ""),
            metadata=parsed_metadata,
            vector_score=float(metadata.get("vector_score", 0.0)),
            upload_time=str(metadata.get("upload_time") or ""),
        )
