import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.test import RequestFactory

from apps.core.api_views import plane_one_click_generate, plane_work_items


class PlaneApiErrorTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_plane_refresh_maps_upstream_502_to_bad_gateway(self):
        request = self.factory.post(
            "/api/plane-work-items/",
            data=json.dumps({"max_items": 0}),
            content_type="application/json",
        )

        with (
            patch("apps.core.api_views._ensure_plane_work_item_table"),
            patch(
                "apps.core.api_views.sync_work_items_to_db",
                side_effect=RuntimeError(
                    "GET http://plane.jing-an.com:3238/api/v1/workspaces/gtja/projects/ failed: 502"
                ),
            ),
        ):
            response = plane_work_items(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 502)
        self.assertIn("Plane", payload["message"])
        self.assertIn("502", payload["message"])


class PlaneOneClickGenerateTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.item = SimpleNamespace(
            id=1,
            project_id="p1",
            project_name="Plane 项目",
            work_item_id="w1",
            work_item_name="设备列表",
            work_item_content="需要生成设备列表相关测试用例",
        )

    def test_plane_generate_falls_back_to_qwen_and_returns_cases(self):
        unique_description = "设备列表展示正常-回退到qwen"
        request = self.factory.post(
            "/api/plane-one-click-generate/",
            data=json.dumps({"id": self.item.id, "llm_provider": "kimi", "case_count": 0}),
            content_type="application/json",
        )

        fake_settings = SimpleNamespace(
            LLM_PROVIDERS={
                "default_provider": "qwen",
                "qwen": {"name": "Qwen", "model": "qwen-max", "api_key": "qwen-key"},
                "kimi": {"name": "Kimi", "model": "kimi-k2.5", "api_key": "kimi-key"},
            }
        )

        class FakeGenerator:
            def __init__(self, llm_service, **kwargs):
                self.llm_service = llm_service

            def generate(self, requirements, input_type="requirement"):
                if self.llm_service.provider == "kimi":
                    raise Exception("Error code: 502 Bad Gateway")
                self.llm_service.last_provider_used = "qwen"
                return [
                    {
                        "description": unique_description,
                        "test_steps": ["进入设备列表"],
                        "expected_results": ["看到设备列表数据"],
                    }
                ]

        def fake_create(provider, **config):
            return SimpleNamespace(provider=provider, last_provider_used=provider)

        fake_filter_result = MagicMock()
        fake_filter_result.first.return_value = self.item

        def fake_bulk_create(objs):
            for index, obj in enumerate(objs, start=1):
                obj.id = index
            return objs

        with (
            patch("apps.core.api_views.settings", fake_settings),
            patch("apps.core.api_views._ensure_plane_work_item_table"),
            patch("apps.core.views.knowledge_service", object()),
            patch("apps.core.api_views.PlaneWorkItem.objects.filter", return_value=fake_filter_result),
            patch("apps.core.api_views.LLMServiceFactory.create", side_effect=fake_create),
            patch("apps.core.api_views.TestCaseGeneratorAgent", side_effect=FakeGenerator),
            patch("apps.core.api_views.TestCase.objects.bulk_create", side_effect=fake_bulk_create),
            patch("apps.core.api_views.logger", create=True) as mock_logger,
        ):
            response = plane_one_click_generate(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["effective_provider"], "qwen")
        self.assertEqual(len(payload["test_cases"]), 1)
        mock_logger.warning.assert_called_once()
        mock_logger.info.assert_called()
        self.assertEqual(payload["saved_count"], 1)
        self.assertEqual(payload["test_case_ids"], [1])
        self.assertEqual(payload["test_cases"][0]["description"], unique_description)

    def test_plane_generate_connection_error_also_falls_back_to_qwen(self):
        unique_description = "设备列表展示正常-连接失败回退"
        request = self.factory.post(
            "/api/plane-one-click-generate/",
            data=json.dumps({"id": self.item.id, "llm_provider": "kimi", "case_count": 0}),
            content_type="application/json",
        )

        fake_settings = SimpleNamespace(
            LLM_PROVIDERS={
                "default_provider": "qwen",
                "qwen": {"name": "Qwen", "model": "qwen-max", "api_key": "qwen-key"},
                "kimi": {"name": "Kimi", "model": "kimi-k2.5", "api_key": "kimi-key"},
            }
        )

        class FakeGenerator:
            def __init__(self, llm_service, **kwargs):
                self.llm_service = llm_service

            def generate(self, requirements, input_type="requirement"):
                if self.llm_service.provider == "kimi":
                    raise Exception("Connection error.")
                self.llm_service.last_provider_used = "qwen"
                return [
                    {
                        "description": unique_description,
                        "test_steps": ["进入设备列表"],
                        "expected_results": ["看到设备列表数据"],
                    }
                ]

        def fake_create(provider, **config):
            return SimpleNamespace(provider=provider, last_provider_used=provider)

        fake_filter_result = MagicMock()
        fake_filter_result.first.return_value = self.item

        def fake_bulk_create(objs):
            for index, obj in enumerate(objs, start=1):
                obj.id = index
            return objs

        with (
            patch("apps.core.api_views.settings", fake_settings),
            patch("apps.core.api_views._ensure_plane_work_item_table"),
            patch("apps.core.views.knowledge_service", object()),
            patch("apps.core.api_views.PlaneWorkItem.objects.filter", return_value=fake_filter_result),
            patch("apps.core.api_views.LLMServiceFactory.create", side_effect=fake_create),
            patch("apps.core.api_views.TestCaseGeneratorAgent", side_effect=FakeGenerator),
            patch("apps.core.api_views.TestCase.objects.bulk_create", side_effect=fake_bulk_create),
            patch("apps.core.api_views.logger", create=True) as mock_logger,
        ):
            response = plane_one_click_generate(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["effective_provider"], "qwen")
        self.assertEqual(len(payload["test_cases"]), 1)
        mock_logger.warning.assert_called_once()
        self.assertEqual(payload["saved_count"], 1)
        self.assertEqual(payload["test_case_ids"], [1])
        self.assertEqual(payload["test_cases"][0]["description"], unique_description)


class PlaneWorkItemsFilterTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_plane_work_items_supports_project_filter(self):
        request = self.factory.get("/api/plane-work-items/?project_id=p2&page=1&page_size=20")
        fake_items = [
            SimpleNamespace(
                id=2,
                project_id="p2",
                project_name="项目B",
                work_item_id="w2",
                work_item_name="需求B",
                work_item_content="内容B",
                updated_at=SimpleNamespace(isoformat=lambda: "2026-03-16T10:00:00"),
            )
        ]
        fake_qs = MagicMock()
        fake_qs.order_by.return_value = fake_qs
        fake_qs.filter.return_value = fake_items

        fake_values = MagicMock()
        fake_values.exclude.return_value = fake_values
        fake_values.order_by.return_value = fake_values
        fake_values.distinct.return_value = [
            {"project_id": "p1", "project_name": "项目A"},
            {"project_id": "p2", "project_name": "项目B"},
        ]

        with (
            patch("apps.core.api_views._ensure_plane_work_item_table"),
            patch("apps.core.api_views.PlaneWorkItem.objects.all", return_value=fake_qs),
            patch("apps.core.api_views.PlaneWorkItem.objects.values", return_value=fake_values),
        ):
            response = plane_work_items(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["project_id"], "p2")
        project_ids = {p["project_id"] for p in payload["projects"]}
        self.assertIn("p1", project_ids)
        self.assertIn("p2", project_ids)


if __name__ == "__main__":
    unittest.main()
