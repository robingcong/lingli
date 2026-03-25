import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch, mock_open

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.test import RequestFactory

from apps.core import views
from apps.core.models import KnowledgeChunk, KnowledgeDocument


class _FakeVectorStore:
    def __init__(self, grouped_documents=None, chunks_by_source=None):
        self.grouped_documents = grouped_documents or []
        self.chunks_by_source = chunks_by_source or {}

    def list_grouped_documents(self):
        return self.grouped_documents

    def get_document_chunks(self, source):
        return self.chunks_by_source.get(source, [])


class KnowledgeLibraryApiTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        KnowledgeChunk.objects.all().delete()
        KnowledgeDocument.objects.all().delete()

    def tearDown(self):
        KnowledgeChunk.objects.all().delete()
        KnowledgeDocument.objects.all().delete()

    def test_knowledge_library_list_only_includes_docs_rag_files(self):
        request = self.factory.get("/api/knowledge-library/")
        KnowledgeDocument.objects.create(
            source_path="docs/rag/dushu.md",
            title="dushu.md",
            doc_type=".md",
            content="V3.17 版本公告\n详细内容",
            content_hash="hash-1",
            file_mtime=0,
            chunk_count=2,
        )

        with (
            patch.object(views, "_sync_rag_documents_if_needed", return_value=None),
        ):
            response = views.knowledge_library_list(request)

        payload = json.loads(response.content)
        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["entry_type"], "rag_file")
        self.assertEqual(payload["items"][0]["source"], "docs/rag/dushu.md")
        self.assertEqual(payload["items"][0]["chunk_count"], 2)

    def test_knowledge_library_detail_returns_uploaded_chunks(self):
        request = self.factory.get("/api/knowledge-library/detail/?entry_id=rag:docs/rag/dushu.md")
        document = KnowledgeDocument.objects.create(
            source_path="docs/rag/dushu.md",
            title="dushu.md",
            doc_type=".md",
            content="V3.17 版本公告\n详细内容",
            content_hash="hash-1",
            file_mtime=0,
            chunk_count=2,
        )
        KnowledgeChunk.objects.create(
            document=document,
            chunk_id="device_0001",
            chunk_index=0,
            content="设备列表展示设备名称、状态和电量。",
        )
        KnowledgeChunk.objects.create(
            document=document,
            chunk_id="device_0002",
            chunk_index=1,
            content="设备详情页支持查看告警和定位。",
        )

        with (
            patch.object(views, "_sync_rag_documents_if_needed", return_value=None),
        ):
            response = views.knowledge_library_detail(request)

        payload = json.loads(response.content)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["item"]["entry_type"], "rag_file")
        self.assertEqual(payload["item"]["chunk_count"], 2)
        self.assertIn("V3.17 版本公告", payload["item"]["full_content"])
        self.assertEqual(payload["item"]["chunks"][0]["chunk_id"], "device_0001")

    def test_search_knowledge_returns_vector_matches_with_chunk_metadata(self):
        request = self.factory.post(
            "/api/search-knowledge/",
            data=json.dumps({"query": "设备列表"}),
            content_type="application/json",
        )
        fake_embedder = SimpleNamespace(get_embeddings=lambda query: [[0.1] * 1024])
        fake_service = SimpleNamespace(
            search_knowledge=lambda query: [
                {
                    "content": "设备列表展示设备名称、状态、电量。",
                    "score": 0.91,
                    "source": "docs/rag/dushu.md",
                    "chunk_id": "device_0001",
                }
            ]
        )

        with (
            patch.object(views, "embedder", fake_embedder, create=True),
            patch.object(views, "knowledge_service", fake_service),
        ):
            response = views.search_knowledge(request)

        payload = json.loads(response.content)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["results"][0]["source"], "docs/rag/dushu.md")
        self.assertEqual(payload["results"][0]["chunk_id"], "device_0001")


if __name__ == "__main__":
    unittest.main()
