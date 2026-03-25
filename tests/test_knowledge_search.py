import os
import unittest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from apps.knowledge.service import KnowledgeService
from apps.knowledge.schemas import RAGContextResult


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
        self.assertEqual(primary_store.calls, [40])
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


if __name__ == "__main__":
    unittest.main()
