import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.utils import timezone

from .specs import normalize_login_info


def _coerce_expected(value: Any) -> str:
    return str(value if value is not None else "")


def _extract_simple_json_path(payload: Any, expression: str) -> Any:
    expression = str(expression or "").strip()
    if expression.startswith("$."):
        expression = expression[2:]
    if expression.startswith("$"):
        expression = expression[1:]
    expression = expression.strip(".")
    if not expression:
        return payload
    current = payload
    for part in expression.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


def _evaluate_assertions(response, response_json: Any, assertions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    for assertion in assertions:
        assertion_type = assertion.get("assertionType")
        condition = assertion.get("condition") or "EQUALS"
        if assertion_type == "RESPONSE_CODE":
            expected = _coerce_expected(assertion.get("expectedValue"))
            actual = str(response.status_code)
            matched = actual == expected
            if condition == "NOT_EQUALS":
                matched = actual != expected
            if not matched:
                failures.append({
                    "type": "RESPONSE_CODE",
                    "expected": expected,
                    "actual": actual,
                    "condition": condition,
                })
            continue

        if assertion_type != "RESPONSE_BODY":
            continue
        json_path = assertion.get("jsonPathAssertion") or {}
        for item in json_path.get("assertions") or []:
            if not isinstance(item, dict) or item.get("enable") is False:
                continue
            expected = _coerce_expected(item.get("expectedValue"))
            actual_value = _extract_simple_json_path(response_json, item.get("expression") or "")
            actual = _coerce_expected(actual_value)
            item_condition = item.get("condition") or condition or "EQUALS"
            matched = actual == expected
            if item_condition == "NOT_EQUALS":
                matched = actual != expected
            if not matched:
                failures.append({
                    "type": "RESPONSE_BODY",
                    "expression": item.get("expression") or "",
                    "expected": expected,
                    "actual": actual,
                    "condition": item_condition,
                })
    return failures


def _result(status: str, passed: bool, duration_ms: int, evidence: Dict[str, Any], error_message: str = "") -> Dict[str, Any]:
    return {
        "status": status,
        "passed": passed,
        "duration_ms": duration_ms,
        "evidence": evidence,
        "error_message": error_message,
    }


def execute_api_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    request_spec = spec.get("api_request") or {}
    started = time.perf_counter()
    try:
        response = requests.Session().request(
            method=request_spec.get("method") or "GET",
            url=request_spec.get("url") or request_spec.get("path"),
            headers=request_spec.get("headers") or {},
            params=request_spec.get("params") or {},
            json=request_spec.get("json"),
            timeout=int(request_spec.get("timeout") or 15),
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        try:
            response_json = response.json()
        except Exception:
            response_json = None
        failures = _evaluate_assertions(response, response_json, spec.get("assertions") or [])
        passed = not failures
        evidence = {
            "request": {
                "method": request_spec.get("method") or "GET",
                "url": request_spec.get("url") or request_spec.get("path"),
                "params": request_spec.get("params") or {},
            },
            "response": {
                "status_code": response.status_code,
                "headers": dict(response.headers or {}),
                "json": response_json,
                "body_snippet": str(getattr(response, "text", "") or "")[:2000],
            },
            "assertion_failures": failures,
        }
        return _result("passed" if passed else "failed", passed, duration_ms, evidence)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return _result(
            "error",
            False,
            duration_ms,
            {
                "request": {
                    "method": request_spec.get("method") or "GET",
                    "url": request_spec.get("url") or request_spec.get("path"),
                },
                "assertion_failures": [],
            },
            str(exc),
        )


def execute_playwright_script(
    script_text: str,
    base_url: str,
    timeout: int = 60,
    login_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    artifact_dir = os.path.join(settings.MEDIA_ROOT, "automation")
    os.makedirs(artifact_dir, exist_ok=True)
    screenshot_path = os.path.join(artifact_dir, f"ui-smoke-{int(time.time() * 1000)}.png")
    env = dict(os.environ)
    env["LINGLI_UI_BASE_URL"] = base_url or env.get("LINGLI_UI_BASE_URL", "http://127.0.0.1:5173")
    env["LINGLI_SCREENSHOT_PATH"] = screenshot_path
    login = normalize_login_info(login_info, base_url=env["LINGLI_UI_BASE_URL"], include_password=True)
    env["LINGLI_LOGIN_ENABLED"] = "1" if login["enabled"] else "0"
    env["LINGLI_LOGIN_URL"] = login["login_url"]
    env["LINGLI_LOGIN_USERNAME"] = login["username"]
    env["LINGLI_LOGIN_PASSWORD"] = login["password"]

    with tempfile.TemporaryDirectory(prefix="lingli-playwright-") as tmpdir:
        script_path = os.path.join(tmpdir, "smoke.py")
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(script_text)
        completed = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    passed = completed.returncode == 0
    evidence = {
        "stdout": (completed.stdout or "")[-4000:],
        "stderr": (completed.stderr or "")[-4000:],
        "screenshot_path": screenshot_path if os.path.exists(screenshot_path) else "",
        "runner_finished_at": timezone.now().isoformat(),
    }
    return _result(
        "passed" if passed else "failed",
        passed,
        duration_ms,
        evidence,
        "" if passed else (completed.stderr or completed.stdout or f"退出码 {completed.returncode}"),
    )
