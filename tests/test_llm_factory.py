import unittest
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from apps.llm.base import LLMServiceFactory


class LLMFactoryTests(unittest.TestCase):
    def test_create_kimi_provider_uses_kimi_chat_model(self):
        fake_settings = SimpleNamespace(
            LLM_PROVIDERS={
                "default_provider": "kimi",
                "kimi": {
                    "name": "Kimi",
                    "model": "kimi-k2.5",
                    "api_base": "http://172.21.30.114:8020/v1",
                    "api_key": "test-key",
                },
            }
        )

        with patch("apps.llm.base.settings", fake_settings), patch("apps.llm.base.KimiChatModel") as mock_kimi:
            sentinel = object()
            mock_kimi.return_value = sentinel

            result = LLMServiceFactory.create("kimi")

            self.assertIs(result, sentinel)
            mock_kimi.assert_called_once()

    def test_primary_provider_falls_back_to_qwen_on_502(self):
        fake_settings = SimpleNamespace(
            LLM_PROVIDERS={
                "default_provider": "qwen",
                "deepseek": {
                    "name": "DeepSeek",
                    "model": "deepseek-chat",
                    "api_base": "http://172.21.30.114:8020/v1",
                    "api_key": "deepseek-key",
                },
                "qwen": {
                    "name": "Qwen",
                    "model": "qwen-max",
                    "api_base": "http://172.21.30.114:8020/v1",
                    "api_key": "qwen-key",
                },
            }
        )

        primary = MagicMock()
        primary.invoke.side_effect = Exception("Error code: 502 Bad Gateway")
        fallback = MagicMock()
        fallback.invoke.return_value = "fallback-ok"

        with (
            patch("apps.llm.base.settings", fake_settings),
            patch("apps.llm.base.DeepSeekChatModel", return_value=primary),
            patch("apps.llm.base.QwenChatModel", return_value=fallback),
        ):
            result = LLMServiceFactory.create("deepseek").invoke(["hello"])

        self.assertEqual(result, "fallback-ok")
        primary.invoke.assert_called_once_with(["hello"])
        fallback.invoke.assert_called_once_with(["hello"])

    def test_primary_provider_falls_back_to_qwen_when_model_not_supported(self):
        fake_settings = SimpleNamespace(
            LLM_PROVIDERS={
                "default_provider": "qwen",
                "kimi": {
                    "name": "Kimi",
                    "model": "kimi-k2.5",
                    "api_base": "http://172.21.30.114:8020/v1",
                    "api_key": "kimi-key",
                },
                "qwen": {
                    "name": "Qwen",
                    "model": "qwen-max",
                    "api_base": "http://172.21.30.114:8020/v1",
                    "api_key": "qwen-key",
                },
            }
        )

        primary = MagicMock()
        primary.invoke.side_effect = Exception("Model kimi-k2.5 is not supported by this gateway")
        fallback = MagicMock()
        fallback.invoke.return_value = "fallback-ok"

        with (
            patch("apps.llm.base.settings", fake_settings),
            patch("apps.llm.base.KimiChatModel", return_value=primary),
            patch("apps.llm.base.QwenChatModel", return_value=fallback),
        ):
            result = LLMServiceFactory.create("kimi").invoke(["hello"])

        self.assertEqual(result, "fallback-ok")
        primary.invoke.assert_called_once_with(["hello"])
        fallback.invoke.assert_called_once_with(["hello"])


if __name__ == "__main__":
    unittest.main()
