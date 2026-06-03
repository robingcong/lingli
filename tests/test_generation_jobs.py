import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.test import RequestFactory

from apps.core.api_views import generation_job_detail, generation_jobs
from apps.core.generation_jobs import _run_requirement_generation, ensure_generation_job_table
from apps.core.models import TestCase, TestCaseGenerationJob


class GenerationJobApiTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        ensure_generation_job_table()
        self.created_job_ids = []
        self.created_test_case_ids = []

    def tearDown(self):
        if self.created_test_case_ids:
            TestCase.objects.filter(id__in=self.created_test_case_ids).delete()
        TestCase.objects.filter(description="账号密码和验证码正确时登录成功").delete()
        if self.created_job_ids:
            TestCaseGenerationJob.objects.filter(id__in=self.created_job_ids).delete()

    def test_create_requirement_job_persists_task_and_submits_background_worker(self):
        request = self.factory.post(
            "/api/generation-jobs/",
            data=json.dumps({
                "source_type": "requirement",
                "requirements": "登录页面包含账号密码登录和验证码校验",
                "llm_provider": "qwen",
                "case_count": 6,
                "generation_profile": "feature_first",
                "focus_points": ["功能子点", "页面交互", "业务链路"],
                "focus_strength": "strong",
            }, ensure_ascii=False),
            content_type="application/json",
        )

        with patch("apps.core.api_views.submit_generation_job") as mock_submit:
            response = generation_jobs(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 202)
        self.assertTrue(payload["success"])
        self.assertIn("job_id", payload)
        self.created_job_ids.append(payload["job_id"])
        mock_submit.assert_called_once_with(payload["job_id"])

        job = TestCaseGenerationJob.objects.get(id=payload["job_id"])
        self.assertEqual(job.source_type, "requirement")
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.llm_provider, "qwen")
        self.assertEqual(job.case_count, 6)
        self.assertIn("账号密码登录", job.requirements)
        config = json.loads(job.config_json)
        self.assertEqual(config["generation_profile"], "feature_first")
        self.assertEqual(config["focus_points"], ["功能子点", "页面交互", "业务链路"])
        self.assertEqual(config["focus_strength"], "strong")
        self.assertEqual(config["case_categories"], ["功能测试"])

    def test_list_generation_jobs_returns_latest_task_status(self):
        job = TestCaseGenerationJob.objects.create(
            source_type="requirement",
            source_title="登录需求",
            requirements="登录页面需求",
            llm_provider="qwen",
            case_count=2,
            config_json=json.dumps({"generation_profile": "feature_first"}, ensure_ascii=False),
            status="completed",
            progress=100,
            stage="已完成",
            message="生成完成",
            result_json=json.dumps([{
                "description": "账号密码登录成功",
                "test_steps": ["输入正确账号密码", "点击登录"],
                "expected_results": ["登录成功", "进入首页"],
            }], ensure_ascii=False),
        )
        self.created_job_ids.append(job.id)

        request = self.factory.get("/api/generation-jobs/")
        response = generation_jobs(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        item = next(item for item in payload["items"] if item["id"] == job.id)
        self.assertEqual(item["status"], "completed")
        self.assertEqual(item["progress"], 100)
        self.assertEqual(item["result_count"], 1)
        self.assertEqual(item["source_title"], "登录需求")

    def test_generation_job_detail_returns_cases_and_trace(self):
        job = TestCaseGenerationJob.objects.create(
            source_type="requirement",
            source_title="登录需求",
            requirements="登录页面需求",
            llm_provider="qwen",
            effective_provider="qwen",
            case_count=1,
            config_json=json.dumps({"generation_profile": "feature_first"}, ensure_ascii=False),
            status="completed",
            progress=100,
            result_json=json.dumps([{
                "description": "验证码为空时阻断登录",
                "test_steps": ["输入账号密码", "清空验证码", "点击登录"],
                "expected_results": ["登录被阻断", "提示验证码不能为空"],
            }], ensure_ascii=False),
            generation_meta_json=json.dumps({"mode": "fast_single_call"}, ensure_ascii=False),
            test_case_ids_json=json.dumps([101], ensure_ascii=False),
        )
        self.created_job_ids.append(job.id)

        request = self.factory.get(f"/api/generation-jobs/{job.id}/")
        response = generation_job_detail(request, job.id)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["job"]["id"], job.id)
        self.assertEqual(payload["job"]["effective_provider"], "qwen")
        self.assertEqual(payload["test_cases"][0]["description"], "验证码为空时阻断登录")
        self.assertEqual(payload["generation_meta"]["mode"], "fast_single_call")
        self.assertEqual(payload["test_case_ids"], [101])

    def test_requirement_job_generation_auto_saves_cases_for_review(self):
        job = TestCaseGenerationJob.objects.create(
            source_type="requirement",
            source_title="登录需求",
            requirements="登录页面包含账号密码登录和验证码校验",
            llm_provider="qwen",
            case_count=1,
            config_json=json.dumps({
                "case_design_methods": ["等价类划分"],
                "case_categories": ["功能测试"],
                "generation_profile": "feature_first",
                "focus_points": ["功能子点"],
                "focus_strength": "strong",
            }, ensure_ascii=False),
            status="running",
            progress=25,
        )
        self.created_job_ids.append(job.id)

        class FakeGenerator:
            def __init__(self, *args, **kwargs):
                self.last_run_trace = {"mode": "fast_single_call"}

            def generate(self, requirements, input_type="requirement"):
                return [
                    {
                        "description": "账号密码和验证码正确时登录成功",
                        "test_steps": ["输入正确账号密码", "输入正确验证码", "点击登录"],
                        "expected_results": ["账号密码校验通过", "验证码校验通过", "进入首页"],
                    }
                ]

        with (
            patch(
                "apps.core.generation_jobs.LLMServiceFactory.create",
                return_value=SimpleNamespace(last_provider_used="qwen"),
            ),
            patch("apps.core.generation_jobs.TestCaseGeneratorAgent", FakeGenerator),
            patch("apps.core.views.knowledge_service", object()),
        ):
            result = _run_requirement_generation(job)

        self.assertEqual(result["saved_count"], 1)
        self.assertEqual(len(result["test_case_ids"]), 1)
        self.created_test_case_ids.extend(result["test_case_ids"])

        saved_case = TestCase.objects.get(id=result["test_case_ids"][0])
        self.assertEqual(saved_case.status, "pending")
        self.assertEqual(saved_case.llm_provider, "qwen")
        self.assertIn("登录页面包含账号密码登录", saved_case.requirements)
        self.assertEqual(saved_case.description, "账号密码和验证码正确时登录成功")
