import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from django.conf import settings
from django.db import close_old_connections, connection
from django.utils import timezone

from .models import PlaneWorkItem, TestCase, TestCaseGenerationJob
from .title_utils import build_test_case_title
from apps.llm import LLMServiceFactory
from apps.agents.generator import TestCaseGeneratorAgent
from apps.agents.reviewer import TestCaseReviewerAgent
from utils.logger_manager import get_logger


logger = get_logger(__name__)

DEFAULT_CASE_DESIGN_METHODS = ["等价类划分", "边界值分析", "判定表", "因果图", "正交分析", "场景法"]
DEFAULT_CASE_CATEGORIES = ["功能测试"]
RUNNING_STATUSES = {"queued", "running", "saving"}

_executor = ThreadPoolExecutor(
    max_workers=int(getattr(settings, "GENERATION_JOB_WORKERS", 2) or 2),
    thread_name_prefix="generation-job",
)


def ensure_generation_job_table() -> None:
    table_name = TestCaseGenerationJob._meta.db_table
    with connection.cursor() as cursor:
        existing = set(connection.introspection.table_names(cursor))
    if table_name in existing:
        return
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(TestCaseGenerationJob)


def _json_loads(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _now():
    return timezone.now()


def _is_retryable_llm_error(exc: Exception) -> bool:
    lower_msg = str(exc).lower()
    return any(
        marker in lower_msg
        for marker in (
            "502",
            "bad gateway",
            "gateway",
            "upstream",
            "connection error",
            "connection refused",
            "timeout",
            "timed out",
        )
    )


def _ensure_plane_work_item_table() -> None:
    table_name = PlaneWorkItem._meta.db_table
    with connection.cursor() as cursor:
        existing = set(connection.introspection.table_names(cursor))
    if table_name in existing:
        return
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(PlaneWorkItem)


def _build_plane_requirements(item: PlaneWorkItem) -> str:
    return "\n".join([
        f"【Plane项目】{item.project_name}",
        f"【工作项ID】{item.work_item_id}",
        f"【工作项标题】{item.work_item_name or ''}",
        "【工作项内容】",
        item.work_item_content or "",
    ])


def _normalize_generation_preferences(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generation_profile": payload.get("generation_profile") or "balanced",
        "focus_points": payload.get("focus_points") or [],
        "focus_strength": payload.get("focus_strength") or "medium",
    }


def _normalize_list(value: Any, default: List[str]) -> List[str]:
    if not value:
        return list(default)
    if isinstance(value, list):
        return value
    return [str(value)]


def create_generation_job(payload: Dict[str, Any]) -> TestCaseGenerationJob:
    ensure_generation_job_table()
    source_type = (payload.get("source_type") or payload.get("job_type") or "requirement").strip()
    llm_config = getattr(settings, "LLM_PROVIDERS", {})
    providers = {k: v for k, v in llm_config.items() if k != "default_provider"}
    default_provider = llm_config.get("default_provider", "kimi")
    llm_provider = payload.get("llm_provider") or default_provider
    if llm_provider not in providers:
        raise ValueError(f"不支持的模型提供商: {llm_provider}")

    try:
        case_count = int(payload.get("case_count", 0) or 0)
    except Exception as exc:
        raise ValueError("case_count 必须为整数") from exc

    config = {
        "case_design_methods": _normalize_list(payload.get("case_design_methods"), DEFAULT_CASE_DESIGN_METHODS),
        "case_categories": _normalize_list(payload.get("case_categories"), DEFAULT_CASE_CATEGORIES),
        **_normalize_generation_preferences(payload),
    }

    if source_type == "plane":
        _ensure_plane_work_item_table()
        plane_item_id = payload.get("plane_item_id") or payload.get("id")
        work_item_id = payload.get("work_item_id")
        item = None
        if plane_item_id is not None:
            item = PlaneWorkItem.objects.filter(id=plane_item_id).first()
        if not item and work_item_id:
            item = PlaneWorkItem.objects.filter(work_item_id=str(work_item_id)).first()
        if not item:
            raise ValueError("未找到对应的 Plane 工作项")
        requirements = _build_plane_requirements(item)
        source_id = str(item.id)
        source_title = item.work_item_name or item.work_item_id
        config["plane_work_item_id"] = item.id
        config["work_item_id"] = item.work_item_id
    elif source_type == "requirement":
        requirements = (payload.get("requirements") or "").strip()
        if not requirements:
            raise ValueError("需求描述不能为空")
        source_id = ""
        source_title = (payload.get("source_title") or requirements.splitlines()[0][:80]).strip()
    else:
        raise ValueError(f"不支持的任务来源: {source_type}")

    return TestCaseGenerationJob.objects.create(
        source_type=source_type,
        source_id=source_id,
        source_title=source_title,
        requirements=requirements,
        llm_provider=llm_provider,
        case_count=case_count,
        config_json=_json_dumps(config),
        status="queued",
        progress=0,
        stage="排队中",
        message="任务已提交，等待后台生成",
    )


def submit_generation_job(job_id: int) -> None:
    _executor.submit(run_generation_job, job_id)


def run_generation_job(job_id: int) -> None:
    close_old_connections()
    ensure_generation_job_table()
    try:
        job = TestCaseGenerationJob.objects.get(id=job_id)
        if job.status not in RUNNING_STATUSES:
            return
        _update_job(job, status="running", progress=10, stage="生成中", message="后台任务已开始", started_at=_now())
        if job.source_type == "plane":
            result = _run_plane_generation(job)
        else:
            result = _run_requirement_generation(job)
        _update_job(
            job,
            status="completed",
            progress=100,
            stage="已完成",
            message=f"生成完成，共 {len(result['test_cases'])} 条用例",
            effective_provider=result.get("effective_provider", ""),
            result_json=_json_dumps(result["test_cases"]),
            generation_meta_json=_json_dumps(result.get("generation_meta") or {}),
            test_case_ids_json=_json_dumps(result.get("test_case_ids") or []),
            saved_count=int(result.get("saved_count") or 0),
            finished_at=_now(),
        )
    except Exception as exc:
        logger.error("后台生成任务失败: job_id=%s error=%s", job_id, exc, exc_info=True)
        try:
            job = TestCaseGenerationJob.objects.get(id=job_id)
            _update_job(
                job,
                status="failed",
                progress=100,
                stage="失败",
                message="生成失败",
                error_message=str(exc),
                finished_at=_now(),
            )
        except Exception:
            logger.error("更新失败任务状态失败: job_id=%s", job_id, exc_info=True)
    finally:
        close_old_connections()


def _update_job(job: TestCaseGenerationJob, **fields) -> None:
    for key, value in fields.items():
        setattr(job, key, value)
    job.save(update_fields=[*fields.keys(), "updated_at"])


def _provider_chain(requested_provider: str) -> List[str]:
    llm_config = getattr(settings, "LLM_PROVIDERS", {})
    providers = {k: v for k, v in llm_config.items() if k != "default_provider"}
    chain = [requested_provider]
    if requested_provider != "qwen" and "qwen" in providers:
        chain.append("qwen")
    return chain


def _create_llm_service(provider: str, temperature: float):
    llm_config = getattr(settings, "LLM_PROVIDERS", {})
    provider_config = dict(llm_config.get(provider, {}))
    provider_config.pop("temperature", None)
    return LLMServiceFactory.create(provider, **provider_config, temperature=temperature)


def _run_requirement_generation(job: TestCaseGenerationJob) -> Dict[str, Any]:
    from .views import knowledge_service

    config = _json_loads(job.config_json, {})
    quality_config = dict(getattr(settings, "TEST_CASE_GENERATION_CONFIG", {}))
    _update_job(job, progress=25, stage="调用模型", message="正在生成测试用例")
    llm_service = _create_llm_service(
        job.llm_provider,
        quality_config.get("generation_temperature", 0.3),
    )
    reviewer_agent = None
    if quality_config.get("enable_llm_review", False):
        reviewer_llm_service = _create_llm_service(
            job.llm_provider,
            quality_config.get("review_temperature", 0.2),
        )
        reviewer_agent = TestCaseReviewerAgent(reviewer_llm_service, knowledge_service)
    generator_agent = TestCaseGeneratorAgent(
        llm_service=llm_service,
        knowledge_service=knowledge_service,
        case_design_methods=config.get("case_design_methods") or DEFAULT_CASE_DESIGN_METHODS,
        case_categories=config.get("case_categories") or DEFAULT_CASE_CATEGORIES,
        case_count=job.case_count,
        reviewer_agent=reviewer_agent,
        quality_config=quality_config,
        generation_preferences={
            "generation_profile": config.get("generation_profile"),
            "focus_points": config.get("focus_points") or [],
            "focus_strength": config.get("focus_strength"),
        },
    )
    test_cases = generator_agent.generate(job.requirements, input_type="requirement")
    _update_job(job, status="saving", progress=80, stage="保存中", message="正在保存测试用例")
    created = _save_generated_test_cases(
        test_cases=test_cases,
        requirements=job.requirements,
        llm_provider=getattr(llm_service, "last_provider_used", job.llm_provider) or job.llm_provider,
        fallback_prefix=f"需求生成-{job.id}",
    )
    return {
        "test_cases": test_cases,
        "effective_provider": getattr(llm_service, "last_provider_used", job.llm_provider) or job.llm_provider,
        "generation_meta": getattr(generator_agent, "last_run_trace", {}) or {},
        "saved_count": len(created),
        "test_case_ids": [obj.id for obj in created],
    }


def _run_plane_generation(job: TestCaseGenerationJob) -> Dict[str, Any]:
    from .views import knowledge_service

    config = _json_loads(job.config_json, {})
    _ensure_plane_work_item_table()
    item = PlaneWorkItem.objects.filter(id=config.get("plane_work_item_id") or job.source_id).first()
    if not item:
        raise ValueError("未找到对应的 Plane 工作项")

    llm_config = getattr(settings, "LLM_PROVIDERS", {})
    providers = {k: v for k, v in llm_config.items() if k != "default_provider"}
    test_cases = None
    effective_provider = job.llm_provider
    generation_meta = {}
    last_exc = None

    for chain_index, active_provider in enumerate(_provider_chain(job.llm_provider)):
        if active_provider not in providers:
            continue
        max_attempts = 2 if chain_index == 0 else 1
        for attempt in range(1, max_attempts + 1):
            try:
                _update_job(
                    job,
                    progress=25 if chain_index == 0 else 35,
                    stage="调用模型",
                    message=f"正在使用 {active_provider} 生成 Plane 用例",
                )
                llm_service = LLMServiceFactory.create(active_provider, **providers.get(active_provider, {}))
                generator_agent = TestCaseGeneratorAgent(
                    llm_service=llm_service,
                    knowledge_service=knowledge_service,
                    case_design_methods=config.get("case_design_methods") or DEFAULT_CASE_DESIGN_METHODS,
                    case_categories=config.get("case_categories") or DEFAULT_CASE_CATEGORIES,
                    case_count=job.case_count,
                    generation_preferences={
                        "generation_profile": config.get("generation_profile"),
                        "focus_points": config.get("focus_points") or [],
                        "focus_strength": config.get("focus_strength"),
                    },
                )
                test_cases = generator_agent.generate(job.requirements, input_type="requirement")
                generation_meta = getattr(generator_agent, "last_run_trace", {}) or {}
                effective_provider = getattr(llm_service, "last_provider_used", active_provider) or active_provider
                break
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts and _is_retryable_llm_error(exc):
                    time.sleep(0.8)
                    continue
                if _is_retryable_llm_error(exc) and active_provider != "qwen" and "qwen" in providers:
                    logger.warning(
                        "后台 Plane 生成模型失败，切换到 qwen: requested_provider=%s current_provider=%s work_item_id=%s error=%s",
                        job.llm_provider,
                        active_provider,
                        item.work_item_id,
                        exc,
                    )
                    break
                raise
        if test_cases:
            break

    if not test_cases:
        if last_exc:
            raise last_exc
        raise ValueError("未生成任何测试用例")

    _update_job(job, status="saving", progress=80, stage="保存中", message="正在保存测试用例")
    created = _save_generated_test_cases(
        test_cases=test_cases,
        requirements=job.requirements,
        llm_provider=effective_provider,
        fallback_prefix=f"Plane-{item.work_item_id}",
    )
    return {
        "test_cases": test_cases,
        "effective_provider": effective_provider,
        "generation_meta": generation_meta,
        "saved_count": len(created),
        "test_case_ids": [obj.id for obj in created],
    }


def _save_generated_test_cases(
    test_cases: List[Dict[str, Any]],
    requirements: str,
    llm_provider: str,
    fallback_prefix: str,
) -> List[TestCase]:
    created = []
    for idx, tc in enumerate(test_cases, start=1):
        created.append(
            TestCase.objects.create(
                title=build_test_case_title(
                    description=tc.get("description", ""),
                    fallback_title=f"{fallback_prefix}-测试用例-{idx}",
                ),
                description=tc.get("description", ""),
                test_steps="\n".join(tc.get("test_steps", [])),
                expected_results="\n".join(tc.get("expected_results", [])),
                requirements=requirements,
                llm_provider=llm_provider,
                status="pending",
            )
        )
    return created


def serialize_generation_job(job: TestCaseGenerationJob) -> Dict[str, Any]:
    result = _json_loads(job.result_json, [])
    return {
        "id": job.id,
        "source_type": job.source_type,
        "source_id": job.source_id,
        "source_title": job.source_title,
        "llm_provider": job.llm_provider,
        "effective_provider": job.effective_provider,
        "case_count": job.case_count,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "message": job.message,
        "error_message": job.error_message,
        "result_count": len(result) if isinstance(result, list) else 0,
        "saved_count": job.saved_count,
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "updated_at": job.updated_at.isoformat() if job.updated_at else "",
        "started_at": job.started_at.isoformat() if job.started_at else "",
        "finished_at": job.finished_at.isoformat() if job.finished_at else "",
    }


def serialize_generation_job_detail(job: TestCaseGenerationJob) -> Dict[str, Any]:
    return {
        "job": {
            **serialize_generation_job(job),
            "requirements": job.requirements,
            "config": _json_loads(job.config_json, {}),
        },
        "test_cases": _json_loads(job.result_json, []),
        "generation_meta": _json_loads(job.generation_meta_json, {}),
        "test_case_ids": _json_loads(job.test_case_ids_json, []),
    }
