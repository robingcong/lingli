import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from apps.knowledge.vector_store import MilvusVectorStore


class _FakeCollection:
    def __init__(self, fields=None, *args, **kwargs):
        self.deleted_expr = None
        self.loaded = False
        self.flushed = False
        self.released = False
        self.inserted_data = None
        self.schema = SimpleNamespace(fields=fields or [])

    def load(self):
        self.loaded = True

    def insert(self, data):
        self.inserted_data = data

    def delete(self, expr):
        self.deleted_expr = expr

    def flush(self):
        self.flushed = True

    def release(self):
        self.released = True


class MilvusVectorStoreTests(unittest.TestCase):
    def test_delete_by_source_uses_single_quoted_expr(self):
        fake_collection = _FakeCollection(fields=[SimpleNamespace(name="source")])
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store.collection_name = "vv_rag_markdown_chunks"

        with patch("apps.knowledge.vector_store.Collection", return_value=fake_collection):
            store.delete_by_source("docs/rag/dushu.md")

        self.assertEqual(fake_collection.deleted_expr, "source == 'docs/rag/dushu.md'")
        self.assertTrue(fake_collection.loaded)
        self.assertTrue(fake_collection.flushed)
        self.assertTrue(fake_collection.released)

    def test_delete_by_source_uses_source_path_for_legacy_schema(self):
        fake_collection = _FakeCollection(fields=[SimpleNamespace(name="source_path")])
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store.collection_name = "vv_rag_markdown_chunks"

        with patch("apps.knowledge.vector_store.Collection", return_value=fake_collection):
            store.delete_by_source("docs/rag/dushu.md")

        self.assertEqual(fake_collection.deleted_expr, "source_path == 'docs/rag/dushu.md'")

    def test_add_data_filters_fields_not_in_existing_collection_schema(self):
        fake_collection = _FakeCollection(
            fields=[
                SimpleNamespace(name="id"),
                SimpleNamespace(name="embedding"),
                SimpleNamespace(name="content"),
            ]
        )
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store.collection_name = "vv_rag_markdown_chunks"

        with patch("apps.knowledge.vector_store.Collection", return_value=fake_collection):
            store.add_data([
                {
                    "embedding": [0.1] * 1024,
                    "content": "手动知识内容",
                    "metadata": "{}",
                    "source": "手动规则",
                    "chunk_id": "manual-1",
                }
            ])

        self.assertEqual(
            fake_collection.inserted_data,
            [{"embedding": [0.1] * 1024, "content": "手动知识内容"}],
        )
        self.assertTrue(fake_collection.flushed)

    def test_add_data_fills_required_legacy_rag_schema_fields(self):
        fake_collection = _FakeCollection(
            fields=[
                SimpleNamespace(name="id", auto_id=True),
                SimpleNamespace(name="embedding"),
                SimpleNamespace(name="doc_id"),
                SimpleNamespace(name="chunk_id"),
                SimpleNamespace(name="chunk_index"),
                SimpleNamespace(name="content"),
                SimpleNamespace(name="source_path"),
                SimpleNamespace(name="doc_title"),
                SimpleNamespace(name="section_path"),
                SimpleNamespace(name="doc_type"),
                SimpleNamespace(name="version_tag"),
                SimpleNamespace(name="content_hash"),
                SimpleNamespace(name="keywords"),
                SimpleNamespace(name="created_at"),
            ]
        )
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store.collection_name = "vv_rag_markdown_chunks"

        with patch("apps.knowledge.vector_store.Collection", return_value=fake_collection):
            store.add_data([
                {
                    "embedding": [0.1] * 1024,
                    "content": "手动知识内容",
                    "source": "手动规则",
                    "doc_type": "text",
                    "chunk_id": "manual-1",
                    "upload_time": "2026-06-03T16:00:00",
                }
            ])

        inserted = fake_collection.inserted_data[0]
        self.assertEqual(inserted["source_path"], "手动规则")
        self.assertEqual(inserted["doc_title"], "手动规则")
        self.assertEqual(inserted["chunk_id"], "manual-1")
        self.assertEqual(inserted["chunk_index"], 0)
        self.assertEqual(inserted["doc_type"], "text")
        self.assertEqual(inserted["created_at"], "2026-06-03T16:00:00")
        self.assertTrue(inserted["doc_id"])
        self.assertTrue(inserted["content_hash"])


if __name__ == "__main__":
    unittest.main()
