from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict

from utils.logger_manager import get_logger

from .context_builder import KnowledgeContextBuilder
from .embedding import BGEM3Embedder
from .reranker import KnowledgeReranker
from .retriever import KnowledgeRetriever
from .schemas import RAGContextResult
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
        """检索、重排并生成带引用的知识库上下文。"""
        query_embedding = self.embedder.get_embeddings(query)[0]
        self.logger.info(
            "知识库查询context: '%s'\n向量维度: %s\n",
            query,
            len(query_embedding),
        )

        search_k = max(top_k * 8, 20)
        documents = self.retriever.retrieve(query_embedding, top_k=search_k)
        self.logger.info(
            "知识库原始召回结果: count=%s, top_scores=%s",
            len(documents),
            [
                round(float((doc.metadata or {}).get("vector_score", 0.0)), 4)
                for doc in documents[:5]
            ],
        )

        reranked = self.reranker.rerank(
            documents=documents,
            query=query,
            top_k=top_k,
            min_score_threshold=min_score_threshold,
        )
        self.logger.info("知识库BM25混合重排后结果: %s", reranked[:top_k])

        context_result = self.context_builder.build(
            query=query,
            ranked_chunks=reranked,
            max_chars_per_chunk=max_chars_per_chunk,
            max_total_chars=max_total_chars,
        )
        self.logger.info("知识库前 top_k 结果: %s", context_result.citations)
        return context_result
