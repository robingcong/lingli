from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class RetrievedChunk:
    content: str
    source: str = ""
    chunk_id: str = ""
    doc_type: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    vector_score: float = 0.0
    bm25_score: float = 0.0
    hybrid_score: float = 0.0
    upload_time: str = ""
    citation_id: str = ""
    truncated: bool = False


@dataclass
class RAGContextResult:
    query: str
    chunks: List[RetrievedChunk]
    context_text: str
    citations: List[Dict[str, Any]]
    used_chunk_count: int
    dropped_chunk_count: int = 0

    @property
    def plain_text(self) -> str:
        return "\n\n".join(chunk.content for chunk in self.chunks if chunk.content)


@dataclass
class RAGContextEnvelope:
    query: str
    normalized_query: str
    retrieval_mode: str
    confidence_level: str
    context_result: RAGContextResult
    top_scores: List[float] = field(default_factory=list)
    cache_hit: bool = False
    latency_ms: float = 0.0
