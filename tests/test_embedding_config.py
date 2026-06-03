import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from apps.core import milvus_helper
from apps.knowledge.embedding import BGEM3Embedder


class EmbeddingConfigTests(unittest.TestCase):
    def test_bge_embedder_prefers_local_model_path_env(self):
        with patch.dict(os.environ, {"EMBEDDING_MODEL_PATH": "/models/bge-m3"}, clear=False):
            with patch("apps.knowledge.embedding.SentenceTransformer") as sentence_transformer:
                BGEM3Embedder()

        sentence_transformer.assert_called_once_with("/models/bge-m3")

    def test_milvus_helper_embedding_model_uses_local_model_path_env(self):
        milvus_helper._embedding_model = None
        with patch.dict(os.environ, {"EMBEDDING_MODEL_PATH": "/models/bge-m3"}, clear=False):
            with patch("apps.core.milvus_helper.SentenceTransformer") as sentence_transformer:
                milvus_helper.get_embedding_model()

        sentence_transformer.assert_called_once_with("/models/bge-m3", trust_remote_code=True)
        milvus_helper._embedding_model = None


if __name__ == "__main__":
    unittest.main()
