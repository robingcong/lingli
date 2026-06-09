import json
import os
import re
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.conf import settings
from django.test import RequestFactory

from apps.agents.generator import RequirementDecomposerAgent, TestCaseGeneratorAgent
from apps.core.views import generate


class _DummyKnowledgeService:
    def search_relevant_knowledge(self, query, top_k=5, min_score_threshold=0.6):
        return ""


class _CountingKnowledgeService:
    def __init__(self, value=""):
        self.value = value
        self.calls = []

    def search_relevant_knowledge_context(self, query, top_k=5, min_score_threshold=0.5, **kwargs):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "min_score_threshold": min_score_threshold,
                **kwargs,
            }
        )
        return self.value


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        self.calls.append(merged)
        return SimpleNamespace(content=self.responses.pop(0))


class _ParallelAwareLLM:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def invoke(self, messages):
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        with self._lock:
            self.calls.append(merged)
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        time.sleep(0.05)
        with self._lock:
            self.active_calls -= 1

        if "nonfunctional-case-generator" in merged:
            payload = [
                {
                    "description": "登录安全控制覆盖",
                    "test_steps": ["伪造他人token访问首页"],
                    "expected_results": ["请求被拒绝"],
                }
            ]
        else:
            payload = [
                {
                    "description": "登录主流程覆盖",
                    "test_steps": ["输入账号密码", "点击登录"],
                    "expected_results": ["登录成功", "进入首页"],
                }
            ]
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))


class _FeatureAwareParallelLLM:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def invoke(self, messages):
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        focus_match = re.search(r"需求功能点：([^\n]+)", merged)
        focus_text = focus_match.group(1) if focus_match else merged
        with self._lock:
            self.calls.append(merged)
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        time.sleep(0.05)
        with self._lock:
            self.active_calls -= 1

        if "设备列表" in focus_text:
            title = "从设备列表选择多架异构无人机"
        elif "执行任务" in focus_text:
            title = "多架异构无人机执行任务"
        else:
            title = "集群任务规划创建"

        payload = [
            {
                "description": title,
                "test_steps": [f"进入{title}入口", "提交操作"],
                "expected_results": [f"{title}入口展示正确", "系统保存并回显结果"],
            }
        ]
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))


class _MultiCaseFeatureLLM:
    def __init__(self):
        self.calls = []

    def invoke(self, messages):
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        focus_match = re.search(r"需求功能点：([^\n]+)", merged)
        focus_text = focus_match.group(1) if focus_match else "需求核心功能"
        self.calls.append(merged)
        payload = [
            {
                "description": f"{focus_text}主流程",
                "test_steps": ["进入功能入口", "提交有效数据"],
                "expected_results": ["功能入口展示正确", "提交成功并回显"],
            },
            {
                "description": f"{focus_text}异常提示",
                "test_steps": ["进入功能入口", "提交无效数据"],
                "expected_results": ["功能入口展示正确", "提示数据不合法"],
            },
        ]
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))


class _FakeReviewer:
    def __init__(self, review_map):
        self.review_map = review_map
        self.single_calls = []
        self.batch_calls = []

    def review_case_data(self, test_case_data):
        self.single_calls.append(test_case_data["description"])
        description = test_case_data["description"]
        result = self.review_map[description]
        return {
            "raw_text": json.dumps(result, ensure_ascii=False),
            "parsed": result,
            "score": result.get("score"),
            "recommendation": result.get("recommendation", ""),
        }

    def review_case_batch(self, test_cases_data):
        self.batch_calls.append([item["description"] for item in test_cases_data])
        payloads = []
        for item in test_cases_data:
            description = item["description"]
            result = self.review_map[description]
            payloads.append({
                "raw_text": json.dumps(result, ensure_ascii=False),
                "parsed": result,
                "score": result.get("score"),
                "recommendation": result.get("recommendation", ""),
            })
        return payloads


class _SingleOnlyReviewer(_FakeReviewer):
    review_case_batch = None


class GenerateViewQualityConfigTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_generate_view_defaults_to_fast_mode_without_review_llm(self):
        request = self.factory.post(
            "/generate",
            data=json.dumps({"requirements": "用户登录", "llm_provider": "qwen", "case_count": 4}),
            content_type="application/json",
        )

        create_calls = []

        class FakeGeneratorAgent:
            last_init = None

            def __init__(
                self,
                llm_service,
                knowledge_service,
                case_design_methods,
                case_categories,
                case_count,
                reviewer_agent=None,
                quality_config=None,
                generation_preferences=None,
            ):
                type(self).last_init = {
                    "llm_service": llm_service,
                    "reviewer_agent": reviewer_agent,
                    "quality_config": quality_config,
                    "case_count": case_count,
                    "case_categories": case_categories,
                    "generation_preferences": generation_preferences,
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
                "fast_mode": True,
                "fast_single_call": True,
                "enable_llm_review": False,
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
        self.assertEqual(len(create_calls), 1)
        self.assertEqual(create_calls[0][1]["temperature"], 0.3)
        self.assertIsNone(FakeGeneratorAgent.last_init["reviewer_agent"])
        self.assertEqual(FakeGeneratorAgent.last_init["quality_config"]["min_review_score"], 7)
        self.assertEqual(FakeGeneratorAgent.last_init["case_categories"], ["功能测试"])

    def test_generate_view_passes_generation_preferences_to_agent(self):
        request = self.factory.post(
            "/generate",
            data=json.dumps({
                "requirements": "用户登录",
                "llm_provider": "qwen",
                "case_count": 3,
                "generation_profile": "feature_first",
                "focus_points": ["功能子点", "页面交互", "状态流转"],
                "focus_strength": "strong",
            }, ensure_ascii=False),
            content_type="application/json",
        )

        class FakeGeneratorAgent:
            last_init = None

            def __init__(self, *args, **kwargs):
                type(self).last_init = kwargs
                self.last_run_trace = {}

            def generate(self, requirements, input_type="requirement"):
                self.last_run_trace = {"mode": "fast_single_call", "status": "success"}
                return [
                    {
                        "description": "登录功能点拆分",
                        "test_steps": ["进入登录页"],
                        "expected_results": ["展示登录表单"],
                    }
                ]

        def fake_create(provider, **config):
            return SimpleNamespace(provider=provider, config=config)

        with (
            patch.object(settings, "TEST_CASE_GENERATION_CONFIG", {
                "generation_temperature": 0.3,
                "fast_mode": True,
                "fast_single_call": True,
                "enable_llm_review": False,
                "default_target_count": 3,
            }, create=True),
            patch("apps.core.views.LLMServiceFactory.create", side_effect=fake_create),
            patch("apps.core.views.TestCaseGeneratorAgent", FakeGeneratorAgent),
            patch("apps.core.views.knowledge_service", _DummyKnowledgeService()),
        ):
            response = generate(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(FakeGeneratorAgent.last_init["generation_preferences"]["generation_profile"], "feature_first")
        self.assertEqual(
            FakeGeneratorAgent.last_init["generation_preferences"]["focus_points"],
            ["功能子点", "页面交互", "状态流转"],
        )
        self.assertEqual(FakeGeneratorAgent.last_init["generation_preferences"]["focus_strength"], "strong")

    def test_generate_view_returns_generation_meta(self):
        request = self.factory.post(
            "/generate",
            data=json.dumps({"requirements": "用户登录", "llm_provider": "qwen", "case_count": 1}),
            content_type="application/json",
        )

        class FakeGeneratorAgent:
            def __init__(self, *args, **kwargs):
                self.last_run_trace = {}

            def generate(self, requirements, input_type="requirement"):
                self.last_run_trace = {
                    "mode": "fast_single_call",
                    "status": "success",
                    "target_count": 1,
                    "returned_count": 1,
                    "steps": [{"name": "llm_generation", "elapsed_ms": 10.0}],
                }
                return [
                    {
                        "description": "登录主流程",
                        "test_steps": ["输入账号密码"],
                        "expected_results": ["登录成功"],
                    }
                ]

        def fake_create(provider, **config):
            return SimpleNamespace(provider=provider, config=config)

        with (
            patch.object(settings, "TEST_CASE_GENERATION_CONFIG", {
                "generation_temperature": 0.3,
                "review_temperature": 0.2,
                "fast_mode": True,
                "fast_single_call": True,
                "enable_llm_review": False,
                "default_target_count": 1,
                "candidate_multiplier": 1,
                "minimum_candidate_count": 1,
                "min_review_score": 7,
                "max_total_rounds": 1,
            }, create=True),
            patch("apps.core.views.LLMServiceFactory.create", side_effect=fake_create),
            patch("apps.core.views.TestCaseGeneratorAgent", FakeGeneratorAgent),
            patch("apps.core.views.knowledge_service", _DummyKnowledgeService()),
        ):
            response = generate(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["generation_meta"]["mode"], "fast_single_call")
        self.assertEqual(payload["generation_meta"]["returned_count"], 1)
        self.assertEqual(payload["generation_meta"]["steps"][0]["name"], "llm_generation")


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

    def test_fast_prompt_includes_generation_preferences(self):
        agent = TestCaseGeneratorAgent(
            llm_service=SimpleNamespace(),
            knowledge_service=self.knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试"],
            case_count=4,
            reviewer_agent=_FakeReviewer({}),
            quality_config={"fast_mode": True, "fast_single_call": True},
            generation_preferences={
                "generation_profile": "feature_first",
                "focus_points": ["功能子点", "页面交互", "状态流转", "业务链路"],
                "focus_strength": "strong",
            },
        )
        bundle = agent.requirement_normalizer.normalize("登录页面包含账号密码登录和验证码校验", "requirement", ["功能测试"])

        messages = agent._build_fast_generation_messages(
            requirement_bundle=bundle,
            knowledge_context="",
            target_count=4,
        )
        prompt_text = "\n".join(message.content for message in messages)

        self.assertIn("功能点优先", prompt_text)
        self.assertIn("功能子点", prompt_text)
        self.assertIn("页面交互", prompt_text)
        self.assertIn("状态流转", prompt_text)
        self.assertIn("偏向点：功能子点、页面交互、状态流转、业务链路。", prompt_text)
        self.assertIn("强度", prompt_text)
        self.assertIn("尽量拆出更多功能点", prompt_text)

    def test_requirement_decomposer_extracts_feature_units_from_system_requirement(self):
        decomposer = RequirementDecomposerAgent()

        features = decomposer.decompose(
            "集群任务规划：系统支持集群任务规划，支持从设备列表选择多架异构无人机执行任务。"
        )

        titles = [feature.title for feature in features]
        self.assertGreaterEqual(len(features), 3)
        self.assertIn("集群任务规划", titles)
        self.assertIn("从设备列表选择多架异构无人机", titles)
        self.assertIn("多架异构无人机执行任务", titles)

    def test_functional_only_generation_does_not_force_nonfunctional_coverages_by_count(self):
        agent = TestCaseGeneratorAgent(
            llm_service=SimpleNamespace(),
            knowledge_service=self.knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试"],
            case_count=8,
            reviewer_agent=_FakeReviewer({}),
            quality_config={},
        )

        coverages = agent._required_coverages_for_target(8)

        self.assertEqual(coverages, ["主流程", "关键分支", "边界条件", "异常处理"])

    def test_fast_generate_records_runtime_trace_steps(self):
        llm = _FakeLLM([
            json.dumps([
                {
                    "description": "登录成功主流程验证",
                    "test_steps": ["输入账号密码", "点击登录"],
                    "expected_results": ["登录成功", "进入首页"],
                }
            ], ensure_ascii=False),
        ])
        knowledge_service = _CountingKnowledgeService("知识上下文")
        agent = TestCaseGeneratorAgent(
            llm_service=llm,
            knowledge_service=knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试"],
            case_count=1,
            reviewer_agent=_FakeReviewer({}),
            quality_config={
                "default_target_count": 1,
                "fast_mode": True,
                "fast_single_call": True,
                "enable_llm_review": False,
                "candidate_multiplier": 1,
                "minimum_candidate_count": 1,
                "max_total_rounds": 1,
            },
        )

        cases = agent.generate("用户登录")

        self.assertEqual(len(cases), 1)
        trace = agent.last_run_trace
        self.assertEqual(trace["mode"], "fast_single_call")
        self.assertEqual(trace["status"], "success")
        self.assertEqual(trace["target_count"], 1)
        self.assertEqual(trace["returned_count"], 1)
        self.assertGreaterEqual(trace["total_elapsed_ms"], 0)
        step_names = [step["name"] for step in trace["steps"]]
        self.assertIn("knowledge_retrieval", step_names)
        self.assertIn("llm_generation", step_names)
        self.assertIn("quality_filtering", step_names)
        self.assertIn("finalization", step_names)
        self.assertEqual(trace["metadata"]["candidate_count"], 1)
        self.assertEqual(trace["metadata"]["qualified_count"], 1)
        self.assertEqual(trace["metadata"]["retained_count"], 1)
        self.assertEqual(len(knowledge_service.calls), 1)

    def test_fast_generation_decomposes_requirement_and_runs_feature_workers_in_parallel(self):
        llm = _FeatureAwareParallelLLM()
        agent = TestCaseGeneratorAgent(
            llm_service=llm,
            knowledge_service=self.knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试"],
            case_count=3,
            reviewer_agent=_FakeReviewer({}),
            quality_config={
                "default_target_count": 3,
                "fast_mode": True,
                "fast_single_call": True,
                "enable_llm_review": False,
                "candidate_multiplier": 1,
                "minimum_candidate_count": 3,
                "max_total_rounds": 1,
            },
        )

        cases = agent.generate("集群任务规划：系统支持集群任务规划，支持从设备列表选择多架异构无人机执行任务。")

        self.assertEqual(len(cases), 3)
        self.assertGreaterEqual(llm.max_active_calls, 2)
        self.assertGreaterEqual(len(llm.calls), 2)
        self.assertTrue(any("需求功能点" in call for call in llm.calls))
        descriptions = {case["description"] for case in cases}
        self.assertIn("集群任务规划创建", descriptions)
        self.assertIn("从设备列表选择多架异构无人机", descriptions)
        self.assertIn("多架异构无人机执行任务", descriptions)
        step_names = [step["name"] for step in agent.last_run_trace["steps"]]
        self.assertIn("requirement_decomposition", step_names)
        self.assertIn("generation_planning", step_names)
        self.assertIn("parallel_generation", step_names)

    def test_generation_returns_all_model_cases_without_trimming_to_case_count(self):
        llm = _MultiCaseFeatureLLM()
        agent = TestCaseGeneratorAgent(
            llm_service=llm,
            knowledge_service=self.knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试"],
            case_count=2,
            reviewer_agent=_FakeReviewer({}),
            quality_config={
                "default_target_count": 2,
                "fast_mode": True,
                "fast_single_call": True,
                "enable_llm_review": False,
                "candidate_multiplier": 1,
                "minimum_candidate_count": 2,
                "max_total_rounds": 1,
            },
        )

        cases = agent.generate("集群任务规划：支持任务创建，支持从设备列表选择多架无人机。")

        self.assertGreater(len(cases), 2)
        self.assertEqual(len(cases), 6)
        self.assertEqual(agent.last_run_trace["returned_count"], 6)

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
                "fast_mode": False,
                "enable_llm_review": True,
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

        self.assertEqual(len(cases), 5)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(len({case["description"] for case in cases}), 5)
        self.assertNotIn("登录性能响应时间", [case["description"] for case in cases])
        self.assertTrue(any("functional-case-generator" in call for call in llm.calls))
        self.assertTrue(any("nonfunctional-case-generator" in call for call in llm.calls))
        self.assertEqual(
            reviewer.batch_calls,
            [
                ["登录成功主流程验证", "登录失败异常提示", "登录性能响应时间", "登录边界长度限制", "登录分支角色限制", "登录安全越权校验"],
            ],
        )
        self.assertEqual(reviewer.single_calls, [])

    def test_review_and_filter_cases_reuses_cached_reviews(self):
        reviewer = _FakeReviewer({
            "登录主流程": {"score": 9, "recommendation": "通过"},
            "登录异常提示": {"score": 8, "recommendation": "通过"},
        })
        agent = TestCaseGeneratorAgent(
            llm_service=SimpleNamespace(),
            knowledge_service=self.knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试"],
            case_count=2,
            reviewer_agent=reviewer,
            quality_config={"min_review_score": 7},
        )

        first = agent._review_and_filter_cases([
            {
                "description": "登录主流程",
                "test_steps": ["输入账号密码", "点击登录"],
                "expected_results": ["登录成功", "进入首页"],
            }
        ])
        second = agent._review_and_filter_cases([
            {
                "description": "登录主流程",
                "test_steps": ["输入账号密码", "点击登录"],
                "expected_results": ["登录成功", "进入首页"],
            },
            {
                "description": "登录异常提示",
                "test_steps": ["输入错误密码", "点击登录"],
                "expected_results": ["登录失败", "提示账号或密码错误"],
            },
        ])

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 2)
        self.assertEqual(reviewer.batch_calls, [["登录主流程"], ["登录异常提示"]])

    def test_review_and_filter_cases_falls_back_to_single_review_when_batch_missing(self):
        reviewer = _SingleOnlyReviewer({
            "登录主流程": {"score": 9, "recommendation": "通过"},
            "登录异常提示": {"score": 8, "recommendation": "通过"},
        })
        agent = TestCaseGeneratorAgent(
            llm_service=SimpleNamespace(),
            knowledge_service=self.knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试"],
            case_count=2,
            reviewer_agent=reviewer,
            quality_config={"min_review_score": 7},
        )

        qualified = agent._review_and_filter_cases([
            {
                "description": "登录主流程",
                "test_steps": ["输入账号密码", "点击登录"],
                "expected_results": ["登录成功", "进入首页"],
            },
            {
                "description": "登录异常提示",
                "test_steps": ["输入错误密码", "点击登录"],
                "expected_results": ["登录失败", "提示账号或密码错误"],
            },
        ])

        self.assertEqual(len(qualified), 2)
        self.assertEqual(reviewer.single_calls, ["登录主流程", "登录异常提示"])

    def test_generate_runs_functional_and_nonfunctional_agents_in_parallel(self):
        llm = _ParallelAwareLLM()
        reviewer = _FakeReviewer({
            "登录主流程覆盖": {"score": 9, "recommendation": "通过"},
            "登录安全控制覆盖": {"score": 8, "recommendation": "通过"},
        })
        agent = TestCaseGeneratorAgent(
            llm_service=llm,
            knowledge_service=self.knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试", "安全测试"],
            case_count=2,
            reviewer_agent=reviewer,
            quality_config={
                "default_target_count": 2,
                "fast_mode": False,
                "candidate_multiplier": 1,
                "minimum_candidate_count": 2,
                "min_review_score": 7,
                "max_total_rounds": 1,
            },
        )

        cases = agent.generate("用户登录")

        self.assertEqual(len(cases), 2)
        self.assertEqual(llm.max_active_calls, 2)
        self.assertEqual(len(llm.calls), 2)
        self.assertTrue(any("functional-case-generator" in call for call in llm.calls))
        self.assertTrue(any("nonfunctional-case-generator" in call for call in llm.calls))

    def test_generate_reuses_knowledge_context_across_rounds(self):
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
            ], ensure_ascii=False),
            json.dumps([
                {
                    "description": "登录边界长度限制",
                    "test_steps": ["输入超长用户名", "点击登录"],
                    "expected_results": ["登录失败", "提示用户名长度超限"],
                },
                {
                    "description": "登录安全越权校验",
                    "test_steps": ["伪造他人token访问首页"],
                    "expected_results": ["请求被拒绝"],
                },
            ], ensure_ascii=False),
            json.dumps([
                {
                    "description": "登录关键分支角色限制",
                    "test_steps": ["使用受限角色登录", "访问首页"],
                    "expected_results": ["登录成功", "仅展示授权内容"],
                }
            ], ensure_ascii=False),
        ])
        reviewer = _FakeReviewer({
            "登录成功主流程验证": {"score": 9, "recommendation": "通过"},
            "登录边界长度限制": {"score": 8, "recommendation": "通过"},
            "登录安全越权校验": {"score": 8, "recommendation": "通过"},
            "登录关键分支角色限制": {"score": 8, "recommendation": "通过"},
        })
        knowledge_service = _CountingKnowledgeService("知识上下文")
        agent = TestCaseGeneratorAgent(
            llm_service=llm,
            knowledge_service=knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试", "安全测试"],
            case_count=3,
            reviewer_agent=reviewer,
            quality_config={
                "default_target_count": 3,
                "fast_mode": False,
                "enable_llm_review": True,
                "candidate_multiplier": 1,
                "minimum_candidate_count": 2,
                "min_review_score": 7,
                "max_total_rounds": 2,
            },
        )

        cases = agent.generate("用户登录")

        self.assertEqual(len(cases), 4)
        self.assertEqual(len(knowledge_service.calls), 1)
        self.assertEqual(knowledge_service.calls[0]["query"], "用户登录")

    def test_generate_requests_compact_knowledge_context(self):
        llm = _FakeLLM([
            json.dumps([
                {
                    "description": "登录成功主流程验证",
                    "test_steps": ["输入账号密码", "点击登录"],
                    "expected_results": ["登录成功", "进入首页"],
                }
            ], ensure_ascii=False),
        ])
        reviewer = _FakeReviewer({
            "登录成功主流程验证": {"score": 9, "recommendation": "通过"},
        })
        knowledge_service = _CountingKnowledgeService("知识上下文")
        agent = TestCaseGeneratorAgent(
            llm_service=llm,
            knowledge_service=knowledge_service,
            case_design_methods=["等价类划分"],
            case_categories=["功能测试"],
            case_count=1,
            reviewer_agent=reviewer,
            quality_config={
                "default_target_count": 1,
                "fast_mode": False,
                "candidate_multiplier": 1,
                "minimum_candidate_count": 1,
                "min_review_score": 7,
                "max_total_rounds": 1,
            },
        )

        agent.generate("用户登录")

        self.assertEqual(knowledge_service.calls[0]["top_k"], 3)
        self.assertEqual(knowledge_service.calls[0]["max_chars_per_chunk"], 350)
        self.assertEqual(knowledge_service.calls[0]["max_total_chars"], 1200)


if __name__ == "__main__":
    unittest.main()
