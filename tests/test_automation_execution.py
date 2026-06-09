import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.test import RequestFactory
from django.db import connection

from apps.core.automation.persistence import ensure_automation_run_table
from apps.core.automation.specs import (
    build_api_specs_from_generation,
    build_ui_spec_from_test_case,
    generate_playwright_script,
)
from apps.core.automation.runners import execute_api_spec
from apps.core.api_views import (
    api_case_generation_automation_run,
    test_case_automation_run as run_test_case_automation,
    test_case_automation_script as build_test_case_automation_script,
    ui_automation_test_cases,
)
from apps.core.models import (
    ApiCaseGeneration,
    ApiSchemaFile,
    AutomationRun,
    TestCase,
    TestCaseAIReview,
    TestCaseReview,
)
from apps.core.views import get_test_case


def _ensure_table(model):
    table_name = model._meta.db_table
    with connection.cursor() as cursor:
        existing = set(connection.introspection.table_names(cursor))
    if table_name in existing:
        return
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(model)


def _sample_api_result_json():
    return json.dumps(
        {
            "apiDefinitions": [
                {
                    "name": "登录",
                    "method": "POST",
                    "path": "/api/login",
                    "apiTestCaseList": [
                        {
                            "name": "账号密码正确登录成功",
                            "priority": "P0",
                            "request": {
                                "method": "POST",
                                "path": "/api/login",
                                "headers": [
                                    {"key": "Content-Type", "value": "application/json"}
                                ],
                                "query": [
                                    {"key": "tenant", "value": "demo"}
                                ],
                                "body": {
                                    "bodyType": "JSON",
                                    "jsonBody": {
                                        "jsonValue": json.dumps(
                                            {"username": "demo", "password": "secret"},
                                            ensure_ascii=False,
                                        )
                                    },
                                    "bodyDataByType": {},
                                },
                                "children": [
                                    {
                                        "assertionConfig": {
                                            "assertions": [
                                                {
                                                    "assertionType": "RESPONSE_CODE",
                                                    "condition": "EQUALS",
                                                    "expectedValue": "200",
                                                },
                                                {
                                                    "assertionType": "RESPONSE_BODY",
                                                    "assertionBodyType": "JSON_PATH",
                                                    "jsonPathAssertion": {
                                                        "assertions": [
                                                            {
                                                                "expression": "code",
                                                                "condition": "EQUALS",
                                                                "expectedValue": "10000",
                                                            }
                                                        ]
                                                    },
                                                },
                                            ]
                                        }
                                    }
                                ],
                            },
                        }
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )


class _FakeResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}
    text = '{"code":10000,"message":"ok"}'

    def json(self):
        return {"code": 10000, "message": "ok"}


class AutomationExecutionTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        _ensure_table(TestCase)
        _ensure_table(TestCaseReview)
        _ensure_table(TestCaseAIReview)
        _ensure_table(ApiSchemaFile)
        _ensure_table(ApiCaseGeneration)
        ensure_automation_run_table()
        self.created_schema_ids = []
        self.created_generation_ids = []
        self.created_case_ids = []
        self.created_run_ids = []

    def tearDown(self):
        if self.created_run_ids:
            AutomationRun.objects.filter(id__in=self.created_run_ids).delete()
        if self.created_generation_ids:
            ApiCaseGeneration.objects.filter(id__in=self.created_generation_ids).delete()
        if self.created_schema_ids:
            ApiSchemaFile.objects.filter(id__in=self.created_schema_ids).delete()
        if self.created_case_ids:
            TestCase.objects.filter(id__in=self.created_case_ids).delete()

    def _create_generation(self):
        schema = ApiSchemaFile.objects.create(
            file_name="login.json",
            file_path="uploads/login.json",
            raw_json=_sample_api_result_json(),
            field_schema="[]",
        )
        self.created_schema_ids.append(schema.id)
        generation = ApiCaseGeneration.objects.create(
            schema_file=schema,
            selected_paths=json.dumps(["/api/login"]),
            count_per_api=1,
            priority="P0",
            llm_provider="qwen",
            result_json=_sample_api_result_json(),
            generated_cases=1,
            selected_api_count=1,
        )
        self.created_generation_ids.append(generation.id)
        return generation

    def _create_test_case(self):
        case = TestCase.objects.create(
            title="登录冒烟",
            description="验证登录页可打开并展示登录入口",
            test_steps="1. 打开登录页\n2. 点击登录按钮",
            expected_results="1. 页面加载成功\n2. 展示登录入口",
            requirements="登录模块需要支持用户访问登录页",
            status="approved",
            llm_provider="qwen",
        )
        self.created_case_ids.append(case.id)
        return case

    def _create_automation_run(self, case, *, passed=True, title="登录冒烟"):
        run = AutomationRun.objects.create(
            source_type="test_case",
            source_id=str(case.id),
            runner_type="playwright",
            status="passed" if passed else "failed",
            passed=passed,
            duration_ms=320 if passed else 640,
            spec_json=json.dumps({"title": title}, ensure_ascii=False),
            script_text="print('smoke')",
            error_message="" if passed else "locator not found",
            evidence_json=json.dumps({"stdout": "ok" if passed else ""}, ensure_ascii=False),
            analysis_json=json.dumps(
                {"category": "none" if passed else "selector_drift", "reason": "选择器失效"},
                ensure_ascii=False,
            ),
        )
        self.created_run_ids.append(run.id)
        return run

    def test_api_generation_case_converts_to_spec_and_executes_assertions(self):
        generation = self._create_generation()
        specs = build_api_specs_from_generation(generation, base_url="http://example.test")

        self.assertEqual(len(specs), 1)
        spec = specs[0]
        self.assertEqual(spec["runner_type"], "api_requests")
        self.assertEqual(spec["source_type"], "api_case_generation")
        self.assertEqual(spec["source_id"], str(generation.id))
        self.assertEqual(spec["api_request"]["url"], "http://example.test/api/login")
        self.assertEqual(spec["api_request"]["json"], {"username": "demo", "password": "secret"})

        with patch("apps.core.automation.runners.requests.Session.request", return_value=_FakeResponse()) as mock_request:
            result = execute_api_spec(spec)

        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "passed")
        mock_request.assert_called_once()
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["params"], {"tenant": "demo"})
        self.assertEqual(kwargs["json"], {"username": "demo", "password": "secret"})
        self.assertEqual(result["evidence"]["response"]["json"]["code"], 10000)

    def test_api_generation_run_endpoint_persists_failure_attribution(self):
        generation = self._create_generation()
        failed_response = SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "application/json"},
            text='{"code":50000,"message":"bad data"}',
            json=lambda: {"code": 50000, "message": "bad data"},
        )
        request = self.factory.post(
            f"/api/automation/api-case-generations/{generation.id}/run/",
            data=json.dumps({"base_url": "http://example.test"}),
            content_type="application/json",
        )

        with patch("apps.core.automation.runners.requests.Session.request", return_value=failed_response):
            response = api_case_generation_automation_run(request, generation.id)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertFalse(payload["run"]["passed"])
        self.assertEqual(payload["run"]["analysis"]["category"], "assertion_issue")
        self.assertIn("修复建议", payload["run"]["analysis"])

        run_id = payload["run"]["id"]
        self.created_run_ids.append(run_id)
        run = AutomationRun.objects.get(id=run_id)
        self.assertEqual(run.source_type, "api_case_generation")
        self.assertEqual(run.source_id, str(generation.id))
        self.assertEqual(run.runner_type, "api_requests")

    def test_ui_automation_management_list_filters_cases_and_summarizes_runs(self):
        passed_case = self._create_test_case()
        failed_case = TestCase.objects.create(
            title="订单列表冒烟",
            description="验证订单列表页可打开",
            test_steps="1. 打开订单列表",
            expected_results="1. 页面加载成功",
            requirements="订单中台需要支持列表查看",
            status="approved",
            llm_provider="qwen",
        )
        self.created_case_ids.append(failed_case.id)
        pending_case = TestCase.objects.create(
            title="待评审冒烟",
            description="未通过评审的 UI 用例不进入默认管理列表",
            test_steps="1. 打开页面",
            expected_results="1. 页面加载成功",
            requirements="待评审需求",
            status="pending",
            llm_provider="qwen",
        )
        self.created_case_ids.append(pending_case.id)
        self._create_automation_run(passed_case, passed=True)
        failed_run = self._create_automation_run(failed_case, passed=False, title="订单列表冒烟")

        request = self.factory.get(
            "/api/automation/ui-test-cases/",
            data={"status": "approved", "automation_status": "failed", "keyword": "订单"},
        )
        response = ui_automation_test_cases(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["passed"], 1)
        self.assertEqual(payload["summary"]["failed"], 1)
        self.assertEqual(payload["summary"]["unrun"], 0)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["id"], failed_case.id)
        self.assertEqual(payload["items"][0]["latest_automation_run"]["id"], failed_run.id)
        self.assertEqual(payload["items"][0]["latest_automation_run"]["analysis"]["category"], "selector_drift")

        unrun_request = self.factory.get(
            "/api/automation/ui-test-cases/",
            data={"status": "pending", "automation_status": "unrun"},
        )
        unrun_response = ui_automation_test_cases(unrun_request)
        unrun_payload = json.loads(unrun_response.content)
        self.assertEqual(unrun_payload["total"], 1)
        self.assertEqual(unrun_payload["items"][0]["id"], pending_case.id)
        self.assertIsNone(unrun_payload["items"][0]["latest_automation_run"])

    def test_test_case_playwright_run_requires_manual_confirmation_and_returns_latest_run(self):
        case = self._create_test_case()
        spec = build_ui_spec_from_test_case(case, base_url="http://127.0.0.1:5173")
        script = generate_playwright_script(spec)
        self.assertIn("sync_playwright", script)
        self.assertIn("登录冒烟", script)

        unconfirmed = self.factory.post(
            f"/api/automation/test-case/{case.id}/run/",
            data=json.dumps({"base_url": "http://127.0.0.1:5173", "script_text": script}),
            content_type="application/json",
        )
        response = run_test_case_automation(unconfirmed, case.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("人工确认", json.loads(response.content)["message"])

        completed = SimpleNamespace(returncode=0, stdout="smoke ok", stderr="")
        confirmed = self.factory.post(
            f"/api/automation/test-case/{case.id}/run/",
            data=json.dumps({
                "base_url": "http://127.0.0.1:5173",
                "script_text": script,
                "confirmed": True,
            }),
            content_type="application/json",
        )
        with patch("apps.core.automation.runners.subprocess.run", return_value=completed):
            response = run_test_case_automation(confirmed, case.id)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["run"]["passed"])
        self.created_run_ids.append(payload["run"]["id"])

        detail_response = get_test_case(self.factory.get(f"/api/test-case/{case.id}/"), case.id)
        detail = json.loads(detail_response.content)
        self.assertEqual(detail["latest_automation_run"]["id"], payload["run"]["id"])
        self.assertEqual(detail["latest_automation_run"]["runner_type"], "playwright")

    def test_ui_automation_script_supports_optional_login_without_embedding_password(self):
        case = self._create_test_case()
        login_info = {
            "enabled": True,
            "login_url": "/login",
            "username": "demo_user",
            "password": "secret-password",
        }
        spec = build_ui_spec_from_test_case(
            case,
            base_url="http://127.0.0.1:5173",
            login_info=login_info,
        )

        login_spec = spec["test_data"]["login"]
        self.assertTrue(login_spec["enabled"])
        self.assertEqual(login_spec["login_url"], "http://127.0.0.1:5173/login")
        self.assertEqual(login_spec["username"], "demo_user")
        self.assertEqual(login_spec["password"], "")

        script = generate_playwright_script(spec)
        self.assertIn("LINGLI_LOGIN_PASSWORD", script)
        self.assertIn("login_if_configured(page)", script)
        self.assertNotIn("secret-password", script)

        request = self.factory.post(
            f"/api/automation/test-case/{case.id}/script/",
            data=json.dumps({
                "base_url": "http://127.0.0.1:5173",
                "login_info": login_info,
            }),
            content_type="application/json",
        )
        response = build_test_case_automation_script(request, case.id)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertIn("LINGLI_LOGIN_PASSWORD", payload["script_text"])
        self.assertNotIn("secret-password", json.dumps(payload, ensure_ascii=False))

    def test_playwright_run_passes_login_env_without_persisting_password(self):
        case = self._create_test_case()
        login_info = {
            "enabled": True,
            "login_url": "/login",
            "username": "demo_user",
            "password": "secret-password",
        }
        captured_env = {}

        def fake_run(*args, **kwargs):
            captured_env.update(kwargs.get("env") or {})
            return SimpleNamespace(returncode=0, stdout="smoke ok", stderr="")

        confirmed = self.factory.post(
            f"/api/automation/test-case/{case.id}/run/",
            data=json.dumps({
                "base_url": "http://127.0.0.1:5173",
                "script_text": "print('ok')",
                "confirmed": True,
                "login_info": login_info,
            }),
            content_type="application/json",
        )
        with patch("apps.core.automation.runners.subprocess.run", side_effect=fake_run):
            response = run_test_case_automation(confirmed, case.id)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.created_run_ids.append(payload["run"]["id"])
        self.assertEqual(captured_env["LINGLI_LOGIN_ENABLED"], "1")
        self.assertEqual(captured_env["LINGLI_LOGIN_URL"], "http://127.0.0.1:5173/login")
        self.assertEqual(captured_env["LINGLI_LOGIN_USERNAME"], "demo_user")
        self.assertEqual(captured_env["LINGLI_LOGIN_PASSWORD"], "secret-password")

        run = AutomationRun.objects.get(id=payload["run"]["id"])
        self.assertNotIn("secret-password", run.spec_json)


if __name__ == "__main__":
    unittest.main()
