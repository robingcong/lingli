import json
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from apps.agents.reviewer import TestCaseReviewerAgent


class _DummyKnowledgeService:
    pass


class _FakeLLM:
    def __init__(self, response_text):
        self.response_text = response_text
        self.calls = []

    def invoke(self, messages):
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        self.calls.append(merged)
        return SimpleNamespace(content=self.response_text)


class ReviewerBatchTests(unittest.TestCase):
    def test_review_case_batch_returns_payloads_in_input_order(self):
        llm = _FakeLLM(json.dumps([
            {"score": 9, "recommendation": "通过", "comments": "好", "strengths": [], "weaknesses": [], "suggestions": [], "missing_scenarios": []},
            {"score": 6, "recommendation": "不通过", "comments": "差", "strengths": [], "weaknesses": [], "suggestions": [], "missing_scenarios": []},
        ], ensure_ascii=False))
        agent = TestCaseReviewerAgent(llm, _DummyKnowledgeService())

        payloads = agent.review_case_batch([
            {"description": "登录主流程", "test_steps": ["输入账号密码"], "expected_results": ["登录成功"]},
            {"description": "登录异常", "test_steps": ["输入错误密码"], "expected_results": ["提示失败"]},
        ])

        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["score"], 9)
        self.assertEqual(payloads[1]["recommendation"], "不通过")
        self.assertIn("按输入顺序返回等长 JSON 数组", llm.calls[0])
        self.assertIn("登录主流程", llm.calls[0])
        self.assertIn("登录异常", llm.calls[0])

    def test_review_case_data_keeps_single_case_compatibility(self):
        llm = _FakeLLM(json.dumps({
            "score": 8,
            "recommendation": "通过",
            "comments": "可执行",
            "strengths": [],
            "weaknesses": [],
            "suggestions": [],
            "missing_scenarios": [],
        }, ensure_ascii=False))
        agent = TestCaseReviewerAgent(llm, _DummyKnowledgeService())

        payload = agent.review_case_data({
            "description": "登录主流程",
            "test_steps": ["输入账号密码"],
            "expected_results": ["登录成功"],
        })

        self.assertEqual(payload["score"], 8)
        self.assertEqual(payload["recommendation"], "通过")


if __name__ == "__main__":
    unittest.main()
