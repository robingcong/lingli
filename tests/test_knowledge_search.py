import os
import unittest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from apps.knowledge.service import KnowledgeService
from apps.knowledge.schemas import RAGContextEnvelope, RAGContextResult, RetrievedChunk


class FakeEmbedder:
    def __init__(self):
        self.calls = []

    def get_embeddings(self, text, show_progress_bar=False):
        self.calls.append(text)
        return [[0.01] * 1024]


class FakeVectorStore:
    def __init__(self, results_by_call):
        self.results_by_call = list(results_by_call)
        self.calls = []

    def search(self, query_vector, top_k=5):
        self.calls.append(top_k)
        if not self.results_by_call:
            return []
        return self.results_by_call.pop(0)


class CountingReranker:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or []

    def rerank(self, documents, query, top_k, min_score_threshold):
        self.calls.append(
            {
                "documents": documents,
                "query": query,
                "top_k": top_k,
                "min_score_threshold": min_score_threshold,
            }
        )
        return list(self.response)


class KnowledgeSearchRollbackTests(unittest.TestCase):
    def test_search_relevant_knowledge_only_uses_primary_vector_store(self):
        embedder = FakeEmbedder()
        primary_store = FakeVectorStore([
            [
                {
                    "id": 1,
                    "score": 0.72,
                    "content": "主库命中：设备列表页面展示设备基础信息。",
                }
            ]
        ])
        rag_store = FakeVectorStore([
            [
                {
                    "id": 2,
                    "score": 0.95,
                    "content": "RAG 命中：这条结果不应该进入当前检索上下文。",
                    "section_path": "V3.7 > 二、设备管理 > 1、设备列表",
                    "source_path": "docs/rag/dushu.md",
                }
            ]
        ])

        service = KnowledgeService(
            vector_store=primary_store,
            embedder=embedder,
            rag_vector_store=rag_store,
        )

        context = service.search_relevant_knowledge("设备列表")

        self.assertEqual(context, "主库命中：设备列表页面展示设备基础信息。")
        self.assertEqual(embedder.calls, ["设备列表"])
        self.assertEqual(primary_store.calls, [20])
        self.assertEqual(rag_store.calls, [])

    def test_search_relevant_knowledge_hybrid_rerank_can_keep_low_vector_scores(self):
        embedder = FakeEmbedder()
        primary_store = FakeVectorStore([
            [
                {"id": 1, "score": 0.41, "content": "飞行指点流程：起飞前先检查姿态与航线。"},
                {"id": 2, "score": 0.39, "content": "设备测试流程：上电自检、链路测试。"},
                {"id": 3, "score": 0.38, "content": "通用文档：与飞行无关。"},
            ]
        ])
        service = KnowledgeService(
            vector_store=primary_store,
            embedder=embedder,
            rag_vector_store=None,
        )

        context = service.search_relevant_knowledge("指点飞行", top_k=2, min_score_threshold=0.5)

        self.assertTrue(context)
        self.assertIn("飞行指点流程", context)

    def test_search_relevant_knowledge_context_returns_structured_citations(self):
        embedder = FakeEmbedder()
        primary_store = FakeVectorStore([
            [
                {
                    "id": 1,
                    "score": 0.91,
                    "content": "设备列表展示设备名称、状态、电量和最近心跳时间。",
                    "source": "uploads/device.md",
                    "chunk_id": "device_0001",
                    "doc_type": ".md",
                    "upload_time": "2026-03-24T10:00:00",
                },
                {
                    "id": 2,
                    "score": 0.89,
                    "content": "设备详情页支持查看定位信息、任务历史与告警记录。",
                    "source": "uploads/device.md",
                    "chunk_id": "device_0002",
                    "doc_type": ".md",
                    "upload_time": "2026-03-24T10:00:00",
                },
            ]
        ])
        service = KnowledgeService(vector_store=primary_store, embedder=embedder)

        result = service.search_relevant_knowledge_context("设备列表", top_k=2)

        self.assertIsInstance(result, RAGContextResult)
        self.assertEqual(result.query, "设备列表")
        self.assertEqual(result.used_chunk_count, 2)
        self.assertEqual(len(result.chunks), 2)
        self.assertIn("[KB#1]", result.context_text)
        self.assertIn("source: uploads/device.md", result.context_text)
        self.assertIn("chunk_id: device_0001", result.context_text)
        self.assertEqual(result.citations[0]["citation_id"], "KB#1")
        self.assertEqual(result.citations[0]["source"], "uploads/device.md")

    def test_search_relevant_knowledge_context_deduplicates_and_limits_chunk_length(self):
        embedder = FakeEmbedder()
        duplicated = "飞行调度前需校验姿态、电量、航线、禁飞区和返航条件。" * 20
        primary_store = FakeVectorStore([
            [
                {
                    "id": 1,
                    "score": 0.95,
                    "content": duplicated,
                    "source": "uploads/dispatch.md",
                    "chunk_id": "dispatch_0001",
                    "doc_type": ".md",
                },
                {
                    "id": 2,
                    "score": 0.94,
                    "content": duplicated,
                    "source": "uploads/dispatch.md",
                    "chunk_id": "dispatch_0002",
                    "doc_type": ".md",
                },
            ]
        ])
        service = KnowledgeService(vector_store=primary_store, embedder=embedder)

        result = service.search_relevant_knowledge_context(
            "飞行调度",
            top_k=2,
            max_chars_per_chunk=120,
            max_total_chars=220,
        )

        self.assertEqual(result.used_chunk_count, 1)
        self.assertEqual(result.dropped_chunk_count, 1)
        self.assertLessEqual(len(result.context_text), 220)
        self.assertTrue(result.chunks[0].truncated)

    def test_search_relevant_knowledge_once_returns_high_confidence_fast_path_envelope(self):
        embedder = FakeEmbedder()
        primary_store = FakeVectorStore([
            [
                {
                    "id": 1,
                    "score": 0.93,
                    "content": "设备列表展示设备名称、状态、电量和最近心跳时间。",
                    "source": "uploads/device.md",
                    "chunk_id": "device_0001",
                    "doc_type": ".md",
                },
                {
                    "id": 2,
                    "score": 0.74,
                    "content": "设备详情页支持查看定位信息、任务历史与告警记录。",
                    "source": "uploads/device.md",
                    "chunk_id": "device_0002",
                    "doc_type": ".md",
                },
                {
                    "id": 3,
                    "score": 0.72,
                    "content": "设备告警支持按时间和级别筛选。",
                    "source": "uploads/device.md",
                    "chunk_id": "device_0003",
                    "doc_type": ".md",
                },
            ]
        ])
        service = KnowledgeService(vector_store=primary_store, embedder=embedder)
        service.reranker = CountingReranker()

        envelope = service.search_relevant_knowledge_once("设备列表", top_k=2)

        self.assertIsInstance(envelope, RAGContextEnvelope)
        self.assertEqual(envelope.retrieval_mode, "fast")
        self.assertEqual(envelope.confidence_level, "high")
        self.assertFalse(envelope.cache_hit)
        self.assertEqual(service.reranker.calls, [])
        self.assertEqual(envelope.context_result.used_chunk_count, 2)

    def test_search_relevant_knowledge_once_uses_rerank_on_low_confidence_results(self):
        embedder = FakeEmbedder()
        primary_store = FakeVectorStore([
            [
                {
                    "id": 1,
                    "score": 0.61,
                    "content": "飞行指点流程：起飞前先检查姿态与航线。",
                    "source": "uploads/dispatch.md",
                    "chunk_id": "dispatch_0001",
                    "doc_type": ".md",
                },
                {
                    "id": 2,
                    "score": 0.60,
                    "content": "设备测试流程：上电自检、链路测试。",
                    "source": "uploads/dispatch.md",
                    "chunk_id": "dispatch_0002",
                    "doc_type": ".md",
                },
                {
                    "id": 3,
                    "score": 0.59,
                    "content": "通用文档：与飞行无关。",
                    "source": "uploads/dispatch.md",
                    "chunk_id": "dispatch_0003",
                    "doc_type": ".md",
                },
            ]
        ])
        service = KnowledgeService(vector_store=primary_store, embedder=embedder)
        reranker = CountingReranker(
            response=[
                RetrievedChunk(
                    content="飞行指点流程：起飞前先检查姿态与航线。",
                    source="uploads/dispatch.md",
                    chunk_id="dispatch_0001",
                    doc_type=".md",
                    vector_score=0.61,
                    bm25_score=1.0,
                    hybrid_score=0.82,
                )
            ]
        )
        service.reranker = reranker

        envelope = service.search_relevant_knowledge_once("指点飞行", top_k=2)

        self.assertEqual(envelope.retrieval_mode, "rerank")
        self.assertEqual(envelope.confidence_level, "low")
        self.assertEqual(len(reranker.calls), 1)
        self.assertEqual(len(reranker.calls[0]["documents"]), 3)
        self.assertEqual(envelope.context_result.used_chunk_count, 1)

    def test_search_relevant_knowledge_once_caches_context_for_repeated_queries(self):
        embedder = FakeEmbedder()
        primary_store = FakeVectorStore([
            [
                {
                    "id": 1,
                    "score": 0.92,
                    "content": "设备列表展示设备名称、状态、电量和最近心跳时间。",
                    "source": "uploads/device.md",
                    "chunk_id": "device_0001",
                    "doc_type": ".md",
                },
                {
                    "id": 2,
                    "score": 0.79,
                    "content": "设备详情页支持查看定位信息、任务历史与告警记录。",
                    "source": "uploads/device.md",
                    "chunk_id": "device_0002",
                    "doc_type": ".md",
                },
                {
                    "id": 3,
                    "score": 0.73,
                    "content": "设备告警支持按时间和级别筛选。",
                    "source": "uploads/device.md",
                    "chunk_id": "device_0003",
                    "doc_type": ".md",
                },
            ]
        ])
        service = KnowledgeService(vector_store=primary_store, embedder=embedder)
        service.reranker = CountingReranker()

        first = service.search_relevant_knowledge_once("  设备列表  ", top_k=2)
        second = service.search_relevant_knowledge_once("设备列表", top_k=2)

        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(len(embedder.calls), 1)
        self.assertEqual(primary_store.calls, [10])


if __name__ == "__main__":
    unittest.main()
