import json
from typing import Any, Dict

from django.db import connection
from django.utils import timezone

from apps.core.models import AutomationRun


def ensure_automation_run_table() -> None:
    table_name = AutomationRun._meta.db_table
    with connection.cursor() as cursor:
        existing = set(connection.introspection.table_names(cursor))
    if table_name in existing:
        return
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(AutomationRun)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def save_automation_run(
    *,
    source_type: str,
    source_id: str,
    runner_type: str,
    spec: Dict[str, Any],
    result: Dict[str, Any],
    analysis: Dict[str, Any],
    script_text: str = "",
):
    ensure_automation_run_table()
    now = timezone.now()
    return AutomationRun.objects.create(
        source_type=source_type,
        source_id=str(source_id),
        runner_type=runner_type,
        status=result.get("status") or ("passed" if result.get("passed") else "failed"),
        passed=bool(result.get("passed")),
        duration_ms=int(result.get("duration_ms") or 0),
        spec_json=_json_dumps(spec),
        script_text=script_text or "",
        error_message=result.get("error_message") or "",
        evidence_json=_json_dumps(result.get("evidence") or {}),
        analysis_json=_json_dumps(analysis or {}),
        started_at=now,
        finished_at=now,
    )


def latest_automation_run(source_type: str, source_id: str, runner_type: str = ""):
    ensure_automation_run_table()
    qs = AutomationRun.objects.filter(source_type=source_type, source_id=str(source_id))
    if runner_type:
        qs = qs.filter(runner_type=runner_type)
    return qs.order_by("-created_at", "-id").first()


def recent_automation_runs(source_type: str, source_id: str, limit: int = 5):
    ensure_automation_run_table()
    return list(
        AutomationRun.objects
        .filter(source_type=source_type, source_id=str(source_id))
        .order_by("-created_at", "-id")[:limit]
    )
