import os
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import HumanMessage, SystemMessage

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from apps.llm.kimi import KimiChatModel


class KimiAdapterTests(unittest.TestCase):
    def test_kimi_messages_protocol_payload_and_response(self):
        model = KimiChatModel(
            api_key="test-kimi-key",
            api_base="http://172.21.30.114:8020/v1",
            model="kimi-k2.5",
            max_tokens=512,
        )

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": "你好，我是 Kimi。",
                }
            ]
        }

        with patch("apps.llm.kimi.requests.post", return_value=response) as mock_post:
            result = model.invoke(
                [
                    SystemMessage(content="你是一个助手"),
                    HumanMessage(content="你好，介绍一下你自己"),
                ]
            )

        self.assertIn("Kimi", result.content)
        mock_post.assert_called_once()
        args = mock_post.call_args.args
        kwargs = mock_post.call_args.kwargs
        self.assertEqual(args[0], "http://172.21.30.114:8020/v1/messages")
        self.assertEqual(kwargs["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(kwargs["json"]["model"], "kimi-k2.5")
        self.assertEqual(kwargs["json"]["messages"][0]["role"], "user")
        self.assertEqual(kwargs["json"]["messages"][0]["content"], "你好，介绍一下你自己")
        self.assertEqual(kwargs["json"]["system"], "你是一个助手")


if __name__ == "__main__":
    unittest.main()
