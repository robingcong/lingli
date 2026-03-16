from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator, EmptyPage
from django.conf import settings
from django.db import connection
from django.db.models import Q
import json
import time

from .models import TestCase, PlaneWorkItem
from .fetch_work_items import sync_work_items_to_db
from .title_utils import build_test_case_title
from apps.llm import LLMServiceFactory
from ..agents.generator import TestCaseGeneratorAgent
from utils.logger_manager import get_logger


logger = get_logger(__name__)


def _map_llm_error(exc: Exception) -> tuple[int, str]:
    """将上游LLM异常映射为更准确的HTTP状态码和提示。"""
    msg = str(exc)
    lower_msg = msg.lower()
    if (
        "connection error" in lower_msg
        or "failed to establish a new connection" in lower_msg
        or "connection aborted" in lower_msg
        or "connection refused" in lower_msg
        or "temporarily unavailable" in lower_msg
    ):
        return 503, "模型服务暂时不可用（连接失败），请稍后重试，或切换其他模型后再试。"
    if (
        "timeout" in lower_msg
        or "timed out" in lower_msg
        or "read timeout" in lower_msg
    ):
        return 504, "模型服务响应超时，请稍后重试，或切换其他模型后再试。"
    if (
        "502" in lower_msg
        or "bad gateway" in lower_msg
        or "gateway" in lower_msg
        or "upstream" in lower_msg
    ):
        return 502, (
            "模型网关暂时不可用（上游返回 502），请稍后重试，"
            "或切换其他模型后再试。"
        )
    return 500, f"生成失败: {msg}"


def _map_plane_error(exc: Exception) -> tuple[int, str]:
    """将 Plane 上游异常映射为更准确的 HTTP 状态码和提示。"""
    msg = str(exc)
    lower_msg = msg.lower()
    if (
        "502" in lower_msg
        or "bad gateway" in lower_msg
        or "gateway" in lower_msg
        or "upstream" in lower_msg
    ):
        return 502, "Plane 服务暂时不可用（上游返回 502），请稍后重试。"
    return 500, f"刷新 Plane 工作项失败: {msg}"


def _ensure_plane_work_item_table() -> None:
    table_name = PlaneWorkItem._meta.db_table
    with connection.cursor() as cursor:
        existing = set(connection.introspection.table_names(cursor))
    if table_name in existing:
        return
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(PlaneWorkItem)


@require_http_methods(["GET"])
def dashboard(request):
    total = TestCase.objects.count()
    pending = TestCase.objects.filter(status='pending').count()
    approved = TestCase.objects.filter(status='approved').count()
    rejected = TestCase.objects.filter(status='rejected').count()

    recent_cases = TestCase.objects.order_by('-created_at')[:10]
    recent = [
        {
            'id': tc.id,
            'description': tc.description,
            'status': tc.status,
            'created_at': tc.created_at.isoformat()
        }
        for tc in recent_cases
    ]

    return JsonResponse({
        'total': total,
        'pending': pending,
        'approved': approved,
        'rejected': rejected,
        'recent': recent
    })


@require_http_methods(["GET"])
def llm_providers(request):
    llm_config = getattr(settings, 'LLM_PROVIDERS', {})
    default_provider = llm_config.get('default_provider', 'deepseek')
    providers = []
    for key, cfg in llm_config.items():
        if key == 'default_provider':
            continue
        providers.append({
            'key': key,
            'name': cfg.get('name', key)
        })

    return JsonResponse({
        'default_provider': default_provider,
        'providers': providers
    })


@require_http_methods(["GET"])
def test_cases_list(request):
    status = request.GET.get('status', 'pending')
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 15))

    qs = TestCase.objects.filter(status=status).order_by('-created_at')
    paginator = Paginator(qs, page_size)
    try:
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    items = [
        {
            'id': tc.id,
            'title': tc.title,
            'description': tc.description,
            'requirements': tc.requirements,
            'status': tc.status,
            'created_at': tc.created_at.isoformat()
        }
        for tc in page_obj.object_list
    ]

    return JsonResponse({
        'items': items,
        'page': page_obj.number,
        'page_size': page_size,
        'total': paginator.count,
        'total_pages': paginator.num_pages
    })


@require_http_methods(["GET", "POST"])
def plane_work_items(request):
    if request.method == "POST":
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': '无效的JSON数据'}, status=400)

        max_items = payload.get('max_items', 0)
        try:
            max_items = int(max_items)
        except Exception:
            return JsonResponse({'success': False, 'message': 'max_items 必须为整数'}, status=400)

        try:
            _ensure_plane_work_item_table()
            result = sync_work_items_to_db(
                max_items=max_items,
                base_url=payload.get('base_url'),
                workspace_slug=payload.get('workspace_slug'),
                api_key=payload.get('api_key'),
            )
            return JsonResponse({
                'success': True,
                'project_count': result['project_count'],
                'item_count': result['item_count'],
                'failure_count': len(result['failures']),
                'created_count': result['created_count'],
                'updated_count': result['updated_count'],
                'synced_count': result['synced_count'],
                'failures': result['failures'][:20],
            })
        except Exception as exc:
            status, message = _map_plane_error(exc)
            return JsonResponse({'success': False, 'message': message}, status=status)

    _ensure_plane_work_item_table()
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
    keyword = (request.GET.get('keyword') or '').strip()
    project_id = (request.GET.get('project_id') or '').strip()

    qs = PlaneWorkItem.objects.all().order_by('-updated_at')
    if keyword:
        qs = qs.filter(
            Q(project_name__icontains=keyword)
            | Q(work_item_id__icontains=keyword)
            | Q(work_item_name__icontains=keyword)
            | Q(work_item_content__icontains=keyword)
        )
    if project_id:
        qs = qs.filter(project_id=project_id)

    projects = [
        {
            "project_id": row["project_id"],
            "project_name": row["project_name"],
        }
        for row in PlaneWorkItem.objects.values("project_id", "project_name")
        .exclude(project_id="")
        .order_by("project_name", "project_id")
        .distinct()
    ]

    paginator = Paginator(qs, page_size)
    try:
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages if paginator.num_pages else 1)

    items = [
        {
            'id': item.id,
            'project_id': item.project_id,
            'project_name': item.project_name,
            'work_item_id': item.work_item_id,
            'work_item_name': item.work_item_name,
            'work_item_content': item.work_item_content,
            'updated_at': item.updated_at.isoformat(),
        }
        for item in page_obj.object_list
    ]

    return JsonResponse({
        'success': True,
        'items': items,
        'projects': projects,
        'page': page_obj.number,
        'page_size': page_size,
        'total': paginator.count,
        'total_pages': paginator.num_pages,
    })


@require_http_methods(["POST"])
def plane_one_click_generate(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '无效的JSON数据'}, status=400)

    item_id = payload.get('id')
    work_item_id = payload.get('work_item_id')
    llm_provider = payload.get('llm_provider')
    case_count = payload.get('case_count', 0)

    try:
        case_count = int(case_count)
    except Exception:
        return JsonResponse({'success': False, 'message': 'case_count 必须为整数'}, status=400)

    _ensure_plane_work_item_table()
    item = None
    if item_id is not None:
        item = PlaneWorkItem.objects.filter(id=item_id).first()
    if not item and work_item_id:
        item = PlaneWorkItem.objects.filter(work_item_id=str(work_item_id)).first()
    if not item:
        return JsonResponse({'success': False, 'message': '未找到对应的 Plane 工作项'}, status=404)

    llm_config = getattr(settings, 'LLM_PROVIDERS', {})
    default_provider = llm_config.get('default_provider', 'deepseek')
    providers = {k: v for k, v in llm_config.items() if k != 'default_provider'}
    if not llm_provider:
        llm_provider = default_provider
    if llm_provider not in providers:
        return JsonResponse({'success': False, 'message': f'不支持的模型提供商: {llm_provider}'}, status=400)

    requirements = "\n".join([
        f"【Plane项目】{item.project_name}",
        f"【工作项ID】{item.work_item_id}",
        f"【工作项标题】{item.work_item_name or ''}",
        "【工作项内容】",
        item.work_item_content or "",
    ])

    default_case_design_methods = ['等价类划分', '边界值分析', '判定表', '因果图', '正交分析', '场景法']
    default_case_categories = ['功能测试', '性能测试', '兼容性测试', '安全测试']

    test_cases = None
    effective_provider = llm_provider
    provider_chain = [llm_provider]
    if llm_provider != "qwen" and "qwen" in providers:
        provider_chain.append("qwen")

    last_exc = None
    for chain_index, active_provider in enumerate(provider_chain):
        max_attempts = 2 if chain_index == 0 else 1
        for attempt in range(1, max_attempts + 1):
            try:
                # 延迟导入，避免模块加载时引入不必要的依赖链
                from .views import knowledge_service
                llm_service = LLMServiceFactory.create(active_provider, **providers.get(active_provider, {}))
                generator_agent = TestCaseGeneratorAgent(
                    llm_service=llm_service,
                    knowledge_service=knowledge_service,
                    case_design_methods=default_case_design_methods,
                    case_categories=default_case_categories,
                    case_count=case_count,
                )
                test_cases = generator_agent.generate(requirements, input_type="requirement")
                effective_provider = getattr(llm_service, "last_provider_used", active_provider) or active_provider
                break
            except Exception as exc:
                last_exc = exc
                status, _ = _map_llm_error(exc)
                if attempt < max_attempts and status in (502, 503, 504):
                    time.sleep(0.8)
                    continue
                if status in (502, 503, 504) and active_provider != "qwen" and "qwen" in providers:
                    logger.warning(
                        "plane_one_click_generate 模型网关失败，切换到 qwen: requested_provider=%s current_provider=%s work_item_id=%s error=%s",
                        llm_provider,
                        active_provider,
                        item.work_item_id,
                        exc,
                    )
                    break
                message_status, message = _map_llm_error(exc)
                return JsonResponse({'success': False, 'message': message}, status=message_status)

        if test_cases:
            break

    if not test_cases:
        if last_exc is not None:
            message_status, message = _map_llm_error(last_exc)
            return JsonResponse({'success': False, 'message': message}, status=message_status)
        return JsonResponse({'success': False, 'message': '未生成任何测试用例'}, status=500)

    to_create = []
    for idx, tc in enumerate(test_cases, start=1):
        to_create.append(
            TestCase(
                title=build_test_case_title(
                    description=tc.get('description', ''),
                    fallback_title=f"Plane-{item.work_item_id}-测试用例-{idx}",
                ),
                description=tc.get('description', ''),
                test_steps='\n'.join(tc.get('test_steps', [])),
                expected_results='\n'.join(tc.get('expected_results', [])),
                requirements=requirements,
                llm_provider=effective_provider,
                status='pending',
            )
        )
    created = TestCase.objects.bulk_create(to_create)
    logger.info(
        "plane_one_click_generate 生成并保存成功: requested_provider=%s effective_provider=%s work_item_id=%s saved_count=%s",
        llm_provider,
        effective_provider,
        item.work_item_id,
        len(created),
    )

    return JsonResponse({
        'success': True,
        'message': f'已一键生成并保存 {len(created)} 条测试用例',
        'requested_provider': llm_provider,
        'effective_provider': effective_provider,
        'saved_count': len(created),
        'test_cases': test_cases,
        'test_case_ids': [obj.id for obj in created],
        'plane_item': {
            'id': item.id,
            'work_item_id': item.work_item_id,
            'project_name': item.project_name,
            'work_item_name': item.work_item_name,
        }
    })
