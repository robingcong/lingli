from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List

from utils.logger_manager import get_logger

from .embedding import BGEM3Embedder
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
        """检索相关知识并合并返回（向量 + BM25 混合召回）。"""
        query_embedding = self.embedder.get_embeddings(query)[0]
        self.logger.info(
            "知识库查询context: '%s'\n向量维度: %s\n",
            query,
            len(query_embedding),
        )

        # 先取更多结果，后续再做过滤
        search_k = max(top_k * 8, 20)
        results = self.vector_store.search(query_embedding, top_k=search_k)
        self.logger.info(
            "知识库原始召回结果: count=%s, top_scores=%s",
            len(results),
            [round(float(item.get("score", 0.0)), 4) for item in results[:5]],
        )

        # 1) 向量分阈值 + 回退兜底
        vector_filtered = [
            item for item in results if float(item.get("score", 0.0)) >= min_score_threshold
        ]
        if not vector_filtered:
            vector_filtered = results[: max(top_k * 3, 10)]
        self.logger.info("知识库相似度阈值过滤后结果: %s", vector_filtered)

        # 2) BM25 对候选集重排
        keywords = self._extract_keywords(query)
        self.logger.info("知识库关键词过滤使用关键词: %s", keywords)
        reranked = self._hybrid_rerank(vector_filtered, keywords)
        self.logger.info("知识库BM25混合重排后结果: %s", reranked[:top_k])

        # 3) 取前 top_k
        top_results = reranked[:top_k]
        self.logger.info("知识库前 top_k 结果: %s", top_results)

        # 4) 拼接内容
        content_list = [str(item.get("content") or "") for item in top_results if item.get("content")]
        if not content_list:
            return ""

        return "\n\n".join(content_list)

    def _extract_keywords(self, query: str) -> List[str]:
        """抽取关键词，兼容中文无空格场景。"""
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", query or "")
        keywords: List[str] = []
        for token in tokens:
            token = token.strip()
            if len(token) <= 1:
                continue
            keywords.append(token)
            # 中文长词补充2-gram，降低“整句匹配”导致的漏召回
            if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) >= 4:
                keywords.extend(token[i : i + 2] for i in range(len(token) - 1))

        deduped: List[str] = []
        seen = set()
        for keyword in keywords:
            if keyword not in seen:
                deduped.append(keyword)
                seen.add(keyword)
        return deduped

    def _tokenize_for_bm25(self, text: str) -> List[str]:
        base_tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text or "")
        tokens: List[str] = []
        for token in base_tokens:
            token = token.strip().lower()
            if not token:
                continue
            tokens.append(token)
            if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) >= 2:
                tokens.extend(token[i : i + 2] for i in range(len(token) - 1))
        return tokens

    def _bm25_scores(self, documents: List[str], query_terms: List[str]) -> List[float]:
        if not documents or not query_terms:
            return [0.0] * len(documents)

        tokenized_docs = [self._tokenize_for_bm25(doc) for doc in documents]
        doc_count = len(tokenized_docs)
        avgdl = sum(len(doc) for doc in tokenized_docs) / max(doc_count, 1)
        if avgdl <= 0:
            avgdl = 1.0

        query_tokens = self._tokenize_for_bm25(" ".join(query_terms))
        unique_query_tokens = list(dict.fromkeys(query_tokens))

        doc_freq: Dict[str, int] = {}
        for term in unique_query_tokens:
            doc_freq[term] = sum(1 for doc in tokenized_docs if term in doc)

        k1 = 1.5
        b = 0.75
        scores: List[float] = []
        for doc_tokens in tokenized_docs:
            tf: Dict[str, int] = {}
            for token in doc_tokens:
                tf[token] = tf.get(token, 0) + 1
            dl = len(doc_tokens)
            score = 0.0
            for term in unique_query_tokens:
                f = tf.get(term, 0)
                if f == 0:
                    continue
                df = doc_freq.get(term, 0)
                idf = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
                denom = f + k1 * (1 - b + b * (dl / avgdl))
                score += idf * (f * (k1 + 1)) / max(denom, 1e-9)
            scores.append(score)
        return scores

    def _normalize(self, values: List[float]) -> List[float]:
        if not values:
            return []
        min_v = min(values)
        max_v = max(values)
        if max_v - min_v < 1e-9:
            return [1.0 if max_v > 0 else 0.0 for _ in values]
        return [(v - min_v) / (max_v - min_v) for v in values]

    def _hybrid_rerank(self, candidates: List[Dict[str, Any]], keywords: List[str]) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        docs = [str(item.get("content") or "") for item in candidates]
        vector_scores = [float(item.get("score", 0.0)) for item in candidates]
        bm25_scores = self._bm25_scores(docs, keywords)

        norm_vec = self._normalize(vector_scores)
        norm_bm25 = self._normalize(bm25_scores)

        reranked: List[Dict[str, Any]] = []
        for item, vec_s, bm25_s in zip(candidates, norm_vec, norm_bm25):
            hybrid_score = 0.7 * vec_s + 0.3 * bm25_s
            merged = dict(item)
            merged["vector_score"] = float(item.get("score", 0.0))
            merged["bm25_score"] = bm25_s
            merged["hybrid_score"] = hybrid_score
            reranked.append(merged)

        reranked.sort(key=lambda x: x.get("hybrid_score", 0.0), reverse=True)
        return reranked
