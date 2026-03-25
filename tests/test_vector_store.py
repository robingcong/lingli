import unittest
import os
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from apps.knowledge.vector_store import MilvusVectorStore


class _FakeCollection:
    def __init__(self, *args, **kwargs):
        self.deleted_expr = None
        self.loaded = False
        self.flushed = False
        self.released = False

    def load(self):
        self.loaded = True

    def delete(self, expr):
        self.deleted_expr = expr

    def flush(self):
        self.flushed = True

    def release(self):
        self.released = True


class MilvusVectorStoreTests(unittest.TestCase):
    def test_delete_by_source_uses_single_quoted_expr(self):
        fake_collection = _FakeCollection()
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store.collection_name = "vv_rag_markdown_chunks"

        with patch("apps.knowledge.vector_store.Collection", return_value=fake_collection):
            store.delete_by_source("docs/rag/dushu.md")

        self.assertEqual(fake_collection.deleted_expr, "source == 'docs/rag/dushu.md'")
        self.assertTrue(fake_collection.loaded)
        self.assertTrue(fake_collection.flushed)
        self.assertTrue(fake_collection.released)


if __name__ == "__main__":
    unittest.main()
