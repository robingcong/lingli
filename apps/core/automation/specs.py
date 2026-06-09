import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin


def _load_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _normalize_headers(raw_headers: Any) -> Dict[str, str]:
    if isinstance(raw_headers, dict):
        return {str(key): str(value) for key, value in raw_headers.items() if value is not None}
    headers: Dict[str, str] = {}
    if isinstance(raw_headers, list):
        for item in raw_headers:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or item.get("name") or item.get("header")
            value = item.get("value") or item.get("expectedValue")
            if key and value is not None:
                headers[str(key)] = str(value)
    return headers


def _normalize_params(raw_params: Any) -> Dict[str, str]:
    if isinstance(raw_params, dict):
        return {str(key): str(value) for key, value in raw_params.items() if value is not None}
    params: Dict[str, str] = {}
    if isinstance(raw_params, list):
        for item in raw_params:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or item.get("name") or item.get("param_name")
            value = item.get("value") or item.get("param_value")
            if key and value is not None:
                params[str(key)] = str(value)
    return params


def _extract_json_body(request_data: Dict[str, Any]) -> Optional[Any]:
    body = request_data.get("body")
    if not isinstance(body, dict):
        return None
    json_body = body.get("jsonBody") or {}
    body_data = body.get("bodyDataByType") or {}
    for candidate in (json_body.get("jsonValue"), body_data.get("jsonValue")):
        parsed = _load_json(candidate, None)
        if parsed is not None:
            return parsed
    return None


def _extract_assertions(request_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    assertions: List[Dict[str, Any]] = []
    for child in request_data.get("children") or []:
        if not isinstance(child, dict):
            continue
        config = child.get("assertionConfig") or {}
        for assertion in config.get("assertions") or []:
            if isinstance(assertion, dict):
                assertions.append(assertion)
    return assertions


def _build_url(base_url: str, path: str) -> str:
    if re.match(r"^https?://", path or ""):
        return path
    if not base_url:
        return path
    return urljoin(f"{base_url.rstrip('/')}/", (path or "").lstrip("/"))


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_login_info(
    login_info: Optional[Dict[str, Any]],
    base_url: str = "",
    *,
    include_password: bool = False,
) -> Dict[str, Any]:
    if not isinstance(login_info, dict):
        login_info = {}
    enabled = _coerce_bool(login_info.get("enabled"))
    login_url_value = str(login_info.get("login_url") or "").strip()
    login_url = _build_url(base_url, login_url_value) if login_url_value else (base_url if enabled else "")
    return {
        "enabled": enabled,
        "login_url": login_url,
        "username": str(login_info.get("username") or "").strip(),
        "password": str(login_info.get("password") or "") if include_password else "",
    }


def build_api_specs_from_generation(generation, base_url: str = "") -> List[Dict[str, Any]]:
    """Convert saved LingLi API generation JSON into executable AutomationSpec items."""
    payload = _load_json(generation.result_json, {})
    api_definitions = payload.get("apiDefinitions") if isinstance(payload, dict) else None
    if not isinstance(api_definitions, list):
        return []

    specs: List[Dict[str, Any]] = []
    for api_index, api_def in enumerate(api_definitions):
        if not isinstance(api_def, dict):
            continue
        cases = api_def.get("apiTestCaseList") or []
        if not isinstance(cases, list):
            continue
        for case_index, case_data in enumerate(cases):
            if not isinstance(case_data, dict):
                continue
            request_data = case_data.get("request") or api_def.get("request") or {}
            if not isinstance(request_data, dict):
                request_data = {}
            method = (
                request_data.get("method")
                or case_data.get("method")
                or api_def.get("method")
                or "GET"
            )
            path = (
                request_data.get("path")
                or case_data.get("path")
                or api_def.get("path")
                or ""
            )
            json_body = _extract_json_body(request_data)
            headers = _normalize_headers(request_data.get("headers"))
            if json_body is not None and not any(key.lower() == "content-type" for key in headers):
                headers["Content-Type"] = "application/json"
            spec = {
                "version": "automation-spec/v1",
                "source_type": "api_case_generation",
                "source_id": str(generation.id),
                "source_case_id": f"{generation.id}:{api_index}:{case_index}",
                "runner_type": "api_requests",
                "title": case_data.get("name") or api_def.get("name") or f"API case {case_index + 1}",
                "preconditions": [],
                "test_data": {
                    "base_url": base_url,
                    "priority": case_data.get("priority") or generation.priority,
                },
                "api_request": {
                    "method": str(method).upper(),
                    "path": path,
                    "url": _build_url(base_url, path),
                    "headers": headers,
                    "params": _normalize_params(request_data.get("query")),
                    "rest": _normalize_params(request_data.get("rest")),
                    "json": json_body,
                    "timeout": 15,
                },
                "assertions": _extract_assertions(request_data),
                "cleanup": [],
            }
            specs.append(spec)
    return specs


def _split_lines(value: str) -> List[str]:
    lines = []
    for line in str(value or "").splitlines():
        cleaned = re.sub(r"^\s*\d+[.、)]\s*", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def build_ui_spec_from_test_case(
    test_case,
    base_url: str = "",
    login_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "version": "automation-spec/v1",
        "source_type": "test_case",
        "source_id": str(test_case.id),
        "runner_type": "playwright",
        "title": test_case.title or test_case.description,
        "preconditions": [],
        "test_data": {
            "base_url": base_url,
            "login": normalize_login_info(login_info, base_url=base_url),
        },
        "ui_steps": [
            {"index": index + 1, "action": step}
            for index, step in enumerate(_split_lines(test_case.test_steps))
        ],
        "assertions": [
            {"index": index + 1, "expectation": item}
            for index, item in enumerate(_split_lines(test_case.expected_results))
        ],
        "cleanup": [],
    }


def generate_playwright_script(spec: Dict[str, Any]) -> str:
    title = str(spec.get("title") or "LingLi UI smoke").replace('"""', '\\"\\"\\"')
    steps = spec.get("ui_steps") or []
    expectations = spec.get("assertions") or []
    login = ((spec.get("test_data") or {}).get("login") or {})
    login_helpers = ""
    login_call = ""
    if login.get("enabled"):
        login_helpers = '''

def first_visible(page, selectors):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=800):
                return locator
        except Exception:
            continue
    return None


def login_if_configured(page):
    if os.getenv("LINGLI_LOGIN_ENABLED") != "1":
        return
    login_url = os.getenv("LINGLI_LOGIN_URL") or BASE_URL
    username = os.getenv("LINGLI_LOGIN_USERNAME", "")
    password = os.getenv("LINGLI_LOGIN_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("登录信息不完整：请填写账号和密码。")

    page.goto(login_url, wait_until="networkidle")
    username_input = first_visible(page, [
        "input[name='username']",
        "input[name='account']",
        "input[name='email']",
        "input[type='email']",
        "input[placeholder*='账号']",
        "input[placeholder*='用户名']",
        "input[placeholder*='邮箱']",
        "input[placeholder*='Username']",
        "input[placeholder*='Email']",
        "input[type='text']",
        "input:not([type])",
    ])
    password_input = first_visible(page, [
        "input[name='password']",
        "input[type='password']",
        "input[placeholder*='密码']",
        "input[placeholder*='Password']",
    ])
    if username_input is None or password_input is None:
        raise RuntimeError("未找到账号或密码输入框。")

    username_input.fill(username)
    password_input.fill(password)
    submit = first_visible(page, [
        "button[type='submit']",
        "button:has-text('登录')",
        "button:has-text('登陆')",
        "button:has-text('Login')",
        "input[type='submit']",
    ])
    if submit is None:
        raise RuntimeError("未找到登录按钮。")
    submit.click()
    page.wait_for_load_state("networkidle")
'''
        login_call = "        login_if_configured(page)\n"
    step_comments = "\n".join(
        f"        # Step {item.get('index')}: {item.get('action')}"
        for item in steps
        if isinstance(item, dict)
    )
    expectation_comments = "\n".join(
        f"        # Expect {item.get('index')}: {item.get('expectation')}"
        for item in expectations
        if isinstance(item, dict)
    )
    return f'''from playwright.sync_api import sync_playwright, expect
import os

BASE_URL = os.getenv("LINGLI_UI_BASE_URL", "http://127.0.0.1:5173")
SCREENSHOT_PATH = os.getenv("LINGLI_SCREENSHOT_PATH", "automation-ui-smoke.png")
{login_helpers}


def run():
    """{title}"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={{"width": 1366, "height": 900}})
{login_call}        page.goto(BASE_URL, wait_until="networkidle")
{step_comments or "        # Add reviewed business interactions here."}
{expectation_comments or "        # Add reviewed assertions here."}
        expect(page.locator("body")).to_be_visible()
        page.screenshot(path=SCREENSHOT_PATH, full_page=True)
        browser.close()


if __name__ == "__main__":
    run()
'''
