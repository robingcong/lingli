import json
from typing import Any

from apps.core.automation.persistence import latest_automation_run, recent_automation_runs


def _json_loads(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def serialize_automation_run(run) -> dict:
    if not run:
        return None
    return {
        "id": run.id,
        "source_type": run.source_type,
        "source_id": run.source_id,
        "runner_type": run.runner_type,
        "status": run.status,
        "passed": run.passed,
        "duration_ms": run.duration_ms,
        "error_message": run.error_message,
        "evidence": _json_loads(run.evidence_json, {}),
        "analysis": _json_loads(run.analysis_json, {}),
        "spec": _json_loads(run.spec_json, {}),
        "script_text": run.script_text,
        "created_at": run.created_at.isoformat() if run.created_at else "",
        "updated_at": run.updated_at.isoformat() if run.updated_at else "",
    }


def serialize_latest_automation_run(source_type: str, source_id: str) -> dict:
    return serialize_automation_run(latest_automation_run(source_type, source_id))


def serialize_recent_automation_runs(source_type: str, source_id: str, limit: int = 5) -> list[dict]:
    return [
        serialize_automation_run(run)
        for run in recent_automation_runs(source_type, source_id, limit=limit)
    ]
