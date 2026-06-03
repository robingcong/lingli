import json
import os
import unittest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.test import RequestFactory

from apps.core.api_views import test_cases_list as api_test_cases_list
from apps.core.models import TestCase, TestCaseAIReview


class ReviewWorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.created_case_ids = []

    def tearDown(self):
        if self.created_case_ids:
            TestCase.objects.filter(id__in=self.created_case_ids).delete()

    def _create_case(self, **overrides):
        defaults = {
            "title": "集群任务规划-选择多架无人机",
            "description": "从设备列表选择多架异构无人机创建集群任务",
            "test_steps": "1. 进入集群任务规划页面\n2. 勾选多架异构无人机\n3. 点击创建任务",
            "expected_results": "1. 页面展示设备列表\n2. 已选设备数量正确\n3. 任务创建成功",
            "requirements": "集群任务规划：系统支持从设备列表选择多架异构无人机执行任务。",
            "status": "pending",
            "llm_provider": "qwen",
        }
        defaults.update(overrides)
        case = TestCase.objects.create(**defaults)
        self.created_case_ids.append(case.id)
        return case

    def test_test_cases_list_returns_review_workspace_fields_and_ai_review(self):
        case = self._create_case()
        TestCaseAIReview.objects.create(
            test_case=case,
            provider="qwen",
            score=8,
            recommendation="通过",
            raw_result=json.dumps({"score": 8, "recommendation": "通过"}, ensure_ascii=False),
        )

        request = self.factory.get("/api/test-cases-list/?status=pending&page=1&page_size=10")
        response = api_test_cases_list(request)

        payload = json.loads(response.content)
        item = next(item for item in payload["items"] if item["id"] == case.id)
        self.assertEqual(item["test_steps"], case.test_steps)
        self.assertEqual(item["expected_results"], case.expected_results)
        self.assertEqual(item["llm_provider"], "qwen")
        self.assertEqual(item["ai_review"]["score"], 8)
        self.assertEqual(item["ai_review"]["recommendation"], "通过")
        self.assertIn("raw_result", item["ai_review"])
        self.assertIn("updated_at", item)

    def test_test_cases_list_supports_all_status_filter(self):
        pending_case = self._create_case(title="待评审用例", status="pending")
        approved_case = self._create_case(title="已通过用例", status="approved")

        request = self.factory.get("/api/test-cases-list/?status=all&page=1&page_size=50")
        response = api_test_cases_list(request)

        payload = json.loads(response.content)
        returned_ids = {item["id"] for item in payload["items"]}
        self.assertIn(pending_case.id, returned_ids)
        self.assertIn(approved_case.id, returned_ids)


if __name__ == "__main__":
    unittest.main()
