import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.test import RequestFactory

from django.conf import settings

from apps.core.api_views import llm_providers


class DefaultProviderTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_llm_providers_returns_kimi_as_default_provider(self):
        request = self.factory.get("/api/llm-providers/")
        fake_settings = SimpleNamespace(
            LLM_PROVIDERS={
                "default_provider": "kimi",
                "qwen": {"name": "Qwen"},
                "kimi": {"name": "Kimi"},
            }
        )

        with patch("apps.core.api_views.settings", fake_settings):
            response = llm_providers(request)

        payload = json.loads(response.content)
        self.assertEqual(payload["default_provider"], "kimi")

    def test_qwen_defaults_to_latest_max_model(self):
        self.assertEqual(settings.LLM_PROVIDERS["qwen"]["model"], "qwen3.7-max")


if __name__ == "__main__":
    unittest.main()
