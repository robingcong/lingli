import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.conf import settings
from django.test import RequestFactory

from apps.agents.generator import TestCaseGeneratorAgent
from apps.core.views import generate


class _DummyKnowledgeService:
    def search_relevant_knowledge(self, query, top_k=5, min_score_threshold=0.6):
        return ""


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        self.calls.append(merged)
        return SimpleNamespace(content=self.responses.pop(0))


class _FakeReviewer:
    def __init__(self, review_map):
        self.review_map = review_map

    def review_case_data(self, test_case_data):
        description = test_case_data["description"]
        result = self.review_map[description]
        return {
            "raw_text": json.dumps(result, ensure_ascii=False),
            "parsed": result,
            "score": result.get("score"),
            "recommendation": result.get("recommendation", ""),
        }


class GenerateViewQualityConfigTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_generate_view_uses_low_temperature_for_generation_and_review(self):
        request = self.factory.post(
            "/generate",
            data=json.dumps({"requirements": "用户登录", "llm_provider": "qwen", "case_count": 4}),
            content_type="application/json",
        )

        create_calls = []

        class FakeGeneratorAgent:
            last_init = None

            def __init__(self, llm_service, knowledge_service, case_design_methods, case_categories, case_count, reviewer_agent=None, quality_config=None):
                type(self).last_init = {
                    "llm_service": llm_service,
                    "reviewer_agent": reviewer_agent,
                    "quality_config": quality_config,
                    "case_count": case_count,
                }

            def generate(self, requirements, input_type="requirement"):
                return [
                    {
                        "description": "登录主流程",
                        "test_steps": ["输入账号密码"],
                        "expected_results": ["登录成功"],
                    }
                ]

        def fake_create(provider, **config):
            create_calls.append((provider, config))
            return SimpleNamespace(provider=provider, config=config)

        with (
            patch.object(settings, "TEST_CASE_GENERATION_CONFIG", {
                "generation_temperature": 0.3,
                "review_temperature": 0.2,
                "default_target_count": 4,
                "candidate_multiplier": 2,
                "minimum_candidate_count": 8,
                "min_review_score": 7,
                "max_supplement_rounds": 2,
                "max_total_rounds": 3,
            }, create=True),
            patch("apps.core.views.LLMServiceFactory.create", side_effect=fake_create),
            patch("apps.core.views.TestCaseGeneratorAgent", FakeGeneratorAgent),
            patch("apps.core.views.knowledge_service", _DummyKnowledgeService()),
        ):
            response = generate(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(len(create_calls), 2)
        self.assertEqual(create_calls[0][1]["temperature"], 0.3)
        self.assertEqual(create_calls[1][1]["temperature"], 0.2)
        self.assertIsNotNone(FakeGeneratorAgent.last_init["reviewer_agent"])
        self.assertEqual(FakeGeneratorAgent.last_init["quality_config"]["min_review_score"], 7)


class GeneratorQualityGateTests(unittest.TestCase):
    def setUp(self):
        self.knowledge_service = _DummyKnowledgeService()

    def test_deduplicate_cases_merges_similar_descriptions(self):
        agent = TestCaseGeneratorAgent(
            llm_service=SimpleNamespace(),
            knowledge_service=self.knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试"],
            case_count=4,
            reviewer_agent=_FakeReviewer({}),
            quality_config={},
        )
        deduped = agent._deduplicate_test_cases([
            {
                "description": "登录成功主流程验证",
                "test_steps": ["输入账号密码", "点击登录"],
                "expected_results": ["登录成功", "进入首页"],
            },
            {
                "description": "登录成功主流程校验",
                "test_steps": ["输入账号密码", "点击登录"],
                "expected_results": ["登录成功", "进入首页"],
            },
        ])

        self.assertEqual(len(deduped), 1)

    def test_generate_retries_to_fill_shortfall_after_dedupe_and_quality_filter(self):
        llm = _FakeLLM([
            json.dumps([
                {
                    "description": "登录成功主流程验证",
                    "test_steps": ["输入账号密码", "点击登录"],
                    "expected_results": ["登录成功", "进入首页"],
                },
                {
                    "description": "登录成功主流程校验",
                    "test_steps": ["输入账号密码", "点击登录"],
                    "expected_results": ["登录成功", "进入首页"],
                },
                {
                    "description": "登录失败异常提示",
                    "test_steps": ["输入错误密码", "点击登录"],
                    "expected_results": ["登录失败", "提示账号或密码错误"],
                },
                {
                    "description": "登录性能响应时间",
                    "test_steps": ["连续发起登录请求"],
                    "expected_results": ["接口响应时间满足要求"],
                },
            ], ensure_ascii=False),
            json.dumps([
                {
                    "description": "登录边界长度限制",
                    "test_steps": ["输入超长用户名", "点击登录"],
                    "expected_results": ["登录失败", "提示用户名长度超限"],
                },
                {
                    "description": "登录分支角色限制",
                    "test_steps": ["使用受限角色登录", "访问首页"],
                    "expected_results": ["登录成功", "仅展示授权内容"],
                },
                {
                    "description": "登录安全越权校验",
                    "test_steps": ["伪造他人token访问首页"],
                    "expected_results": ["请求被拒绝"],
                },
            ], ensure_ascii=False),
        ])
        reviewer = _FakeReviewer({
            "登录成功主流程验证": {"score": 9, "recommendation": "通过"},
            "登录失败异常提示": {"score": 8, "recommendation": "通过"},
            "登录性能响应时间": {"score": 6, "recommendation": "不通过"},
            "登录边界长度限制": {"score": 8, "recommendation": "通过"},
            "登录分支角色限制": {"score": 8, "recommendation": "通过"},
            "登录安全越权校验": {"score": 8, "recommendation": "通过"},
        })
        agent = TestCaseGeneratorAgent(
            llm_service=llm,
            knowledge_service=self.knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试", "安全测试"],
            case_count=4,
            reviewer_agent=reviewer,
            quality_config={
                "default_target_count": 4,
                "candidate_multiplier": 2,
                "minimum_candidate_count": 4,
                "min_review_score": 7,
                "max_supplement_rounds": 2,
                "max_total_rounds": 3,
                "dedupe_similarity_threshold": 0.72,
                "keyword_overlap_threshold": 0.6,
            },
        )

        cases = agent.generate("用户登录")

        self.assertEqual(len(cases), 4)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(len({case["description"] for case in cases}), 4)
        self.assertNotIn("登录性能响应时间", [case["description"] for case in cases])
        self.assertIn("边界条件", llm.calls[1])
        self.assertIn("关键分支", llm.calls[1])


if __name__ == "__main__":
    unittest.main()
