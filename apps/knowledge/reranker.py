from __future__ import annotations

import json
import math
import re
from typing import Dict, List

from langchain_core.documents import Document

from .schemas import RetrievedChunk


class KnowledgeReranker:
    """Hybrid reranker using existing vector score and lightweight BM25."""

    def rerank(
        self,
        documents: List[Document],
        query: str,
        top_k: int,
        min_score_threshold: float,
    ) -> List[RetrievedChunk]:
        candidates = self._to_chunks(documents)
        vector_filtered = [
            item for item in candidates if float(item.vector_score) >= min_score_threshold
        ]
        if not vector_filtered:
            vector_filtered = candidates[: max(top_k * 3, 10)]

        keywords = self._extract_keywords(query)
        docs = [item.content for item in vector_filtered]
        vector_scores = [item.vector_score for item in vector_filtered]
        bm25_scores = self._bm25_scores(docs, keywords)
        norm_vec = self._normalize(vector_scores)
        norm_bm25 = self._normalize(bm25_scores)

        reranked: List[RetrievedChunk] = []
        for item, vec_s, bm25_s in zip(vector_filtered, norm_vec, norm_bm25):
            hybrid_score = 0.7 * vec_s + 0.3 * bm25_s
            reranked.append(
                RetrievedChunk(
                    content=item.content,
                    source=item.source,
                    chunk_id=item.chunk_id,
                    doc_type=item.doc_type,
                    metadata=item.metadata,
                    vector_score=item.vector_score,
                    bm25_score=bm25_s,
                    hybrid_score=hybrid_score,
                    upload_time=item.upload_time,
                )
            )

        reranked.sort(key=lambda x: x.hybrid_score, reverse=True)
        return reranked[:top_k]

    def _to_chunks(self, documents: List[Document]) -> List[RetrievedChunk]:
        chunks: List[RetrievedChunk] = []
        for doc in documents:
            metadata = dict(doc.metadata or {})
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

            chunks.append(
                RetrievedChunk(
                    content=str(doc.page_content or ""),
                    source=str(metadata.get("source") or ""),
                    chunk_id=str(metadata.get("chunk_id") or ""),
                    doc_type=str(metadata.get("doc_type") or ""),
                    metadata=parsed_metadata,
                    vector_score=float(metadata.get("vector_score", 0.0)),
                    upload_time=str(metadata.get("upload_time") or ""),
                )
            )
        return chunks

    def _extract_keywords(self, query: str) -> List[str]:
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", query or "")
        keywords: List[str] = []
        for token in tokens:
            token = token.strip()
            if len(token) <= 1:
                continue
            keywords.append(token)
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
