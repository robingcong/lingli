from __future__ import annotations

import re
from typing import Dict, List

from .schemas import RAGContextResult, RetrievedChunk


class KnowledgeContextBuilder:
    """Convert ranked chunks into compact prompt-ready context with citations."""

    def build(
        self,
        query: str,
        ranked_chunks: List[RetrievedChunk],
        max_chars_per_chunk: int = 600,
        max_total_chars: int = 2400,
    ) -> RAGContextResult:
        used_chunks: List[RetrievedChunk] = []
        citations: List[Dict[str, str]] = []
        blocks: List[str] = []
        seen_fingerprints = set()
        dropped_count = 0

        for chunk in ranked_chunks:
            fingerprint = self._fingerprint(chunk.content)
            if not fingerprint or fingerprint in seen_fingerprints:
                dropped_count += 1
                continue

            citation_id = f"KB#{len(used_chunks) + 1}"
            header_lines = [
                f"[{citation_id}]",
                f"source: {chunk.source or 'unknown'}",
                f"chunk_id: {chunk.chunk_id or 'unknown'}",
                f"score: {chunk.hybrid_score:.3f}",
                "content:",
            ]
            header = "\n".join(header_lines)
            remaining_budget = max_total_chars - sum(len(block) for block in blocks)
            if remaining_budget <= len(header) + 1:
                dropped_count += 1
                continue

            content_budget = min(max_chars_per_chunk, remaining_budget - len(header) - 1)
            display_content, truncated = self._truncate(chunk.content, content_budget)
            if not display_content:
                dropped_count += 1
                continue

            block = f"{header}\n{display_content}"
            if len(block) > remaining_budget:
                display_content, truncated = self._truncate(
                    chunk.content,
                    max(remaining_budget - len(header) - 1, 0),
                )
                block = f"{header}\n{display_content}" if display_content else ""
            if not block:
                dropped_count += 1
                continue

            prepared = RetrievedChunk(
                content=chunk.content,
                source=chunk.source,
                chunk_id=chunk.chunk_id,
                doc_type=chunk.doc_type,
                metadata=chunk.metadata,
                vector_score=chunk.vector_score,
                bm25_score=chunk.bm25_score,
                hybrid_score=chunk.hybrid_score,
                upload_time=chunk.upload_time,
                citation_id=citation_id,
                truncated=truncated,
            )
            used_chunks.append(prepared)
            citations.append(
                {
                    "citation_id": citation_id,
                    "source": prepared.source,
                    "chunk_id": prepared.chunk_id,
                    "score": round(prepared.hybrid_score, 4),
                }
            )
            blocks.append(block)
            seen_fingerprints.add(fingerprint)

        return RAGContextResult(
            query=query,
            chunks=used_chunks,
            context_text="\n\n".join(blocks),
            citations=citations,
            used_chunk_count=len(used_chunks),
            dropped_chunk_count=dropped_count,
        )

    def _fingerprint(self, content: str) -> str:
        normalized = re.sub(r"\s+", "", content or "").lower()
        return normalized[:200]

    def _truncate(self, content: str, limit: int) -> tuple[str, bool]:
        if limit <= 0:
            return "", False
        if len(content) <= limit:
            return content, False
        if limit <= 3:
            return content[:limit], True
        return content[: limit - 3].rstrip() + "...", True
