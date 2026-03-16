import os
import unittest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from apps.knowledge.service import KnowledgeService


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


if __name__ == "__main__":
    unittest.main()
