from typing import Dict, Any, List, Optional, Set, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import re
import time
import uuid
from difflib import SequenceMatcher

from django.conf import settings
from langchain_core.messages import HumanMessage, SystemMessage

from ..llm.base import BaseLLMService
from ..knowledge.service import KnowledgeService
from ..knowledge.schemas import RAGContextResult
from .prompts import TestCaseGeneratorPrompt
from .reviewer import TestCaseReviewerAgent
from utils.logger_manager import get_logger


@dataclass
class NormalizedRequirementBundle:
    raw_input: str
    input_type: str
    summary: str
    functional_focus_tags: List[str]
    nonfunctional_focus_tags: List[str]


@dataclass
class RequirementFeature:
    feature_id: str
    title: str
    evidence: str
    priority: int = 0
    signals: List[str] = field(default_factory=list)


@dataclass
class GenerationSubtask:
    agent_role: str
    coverage_tags: List[str]
    request_count: int
    feature_id: str = ""
    feature_title: str = ""
    requirement_excerpt: str = ""


@dataclass
class GenerationPlan:
    target_count: int
    required_coverages: List[str]
    features: List[RequirementFeature]
    subtasks: List[GenerationSubtask]


@dataclass
class CoverageMergeResult:
    deduped_cases: List[Dict[str, Any]]
    qualified_cases: List[Dict[str, Any]]
    retained_cases: List[Dict[str, Any]]
    missing_coverages: List[str]


@dataclass
class GenerationPreferences:
    generation_profile: str
    focus_points: List[str]
    focus_strength: str


class RequirementDecomposerAgent:
    """把一段需求拆成可分配生成任务的功能点。"""

    _ACTION_PATTERNS = (
        re.compile(r"从(?P<object>[^，。；;]{2,24}?)选择(?P<target>[^，。；;]{2,30}?)(?:执行任务|进行|完成|$)"),
        re.compile(r"(?P<title>多架[^，。；;]{2,24}?执行任务)"),
        re.compile(r"(?P<title>[^，。；;]{2,24}?任务规划)"),
    )

    def decompose(self, input_text: str) -> List[RequirementFeature]:
        text = self._clean_text(input_text)
        titles: List[str] = []

        heading = self._extract_heading(text)
        if heading:
            self._append_unique(titles, heading)

        for pattern in self._ACTION_PATTERNS:
            for match in pattern.finditer(text):
                if "object" in match.groupdict():
                    title = f"从{match.group('object')}选择{match.group('target')}"
                else:
                    title = match.group("title")
                self._append_unique(titles, self._normalize_title(title))

        for segment in self._split_segments(text):
            normalized = self._normalize_title(segment)
            if self._is_useful_feature_title(normalized):
                self._append_unique(titles, normalized)

        if not titles:
            fallback = self._normalize_title(text[:40]) or "需求核心功能"
            titles = [fallback]

        features = []
        for index, title in enumerate(titles[:8], start=1):
            features.append(
                RequirementFeature(
                    feature_id=f"F{index:02d}",
                    title=title,
                    evidence=self._evidence_for_title(text, title),
                    priority=max(0, 100 - index),
                    signals=self._detect_signals(title),
                )
            )
        return features

    def _clean_text(self, text: str) -> str:
        cleaned = re.sub(r"<[^>]+>", "\n", text or "")
        cleaned = re.sub(r"&nbsp;|&#160;", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _extract_heading(self, text: str) -> str:
        match = re.match(r"^\s*([^：:。；;，,]{2,24})[：:]", text)
        if not match:
            return ""
        return self._normalize_title(match.group(1))

    def _split_segments(self, text: str) -> List[str]:
        return [segment.strip() for segment in re.split(r"[。；;\n，,：:]", text) if segment.strip()]

    def _normalize_title(self, title: str) -> str:
        normalized = re.sub(r"^(系统)?(支持|可|可以|能够|需要|实现)", "", title or "").strip()
        normalized = re.sub(r"(功能|模块)$", "", normalized).strip()
        normalized = re.sub(r"\s+", "", normalized)
        return normalized.strip("：:。；;，, ")

    def _is_useful_feature_title(self, title: str) -> bool:
        if not title or len(title) < 4 or len(title) > 28:
            return False
        if title in {"系统支持", "功能说明", "需求描述"}:
            return False
        if "选择" in title and "执行任务" in title:
            return False
        markers = ("规划", "选择", "执行", "创建", "编辑", "删除", "查询", "配置", "提交", "审批", "上传", "下载")
        return any(marker in title for marker in markers)

    def _append_unique(self, titles: List[str], title: str) -> None:
        if not title:
            return
        normalized = self._normalize_title(title)
        if normalized and normalized not in titles:
            titles.append(normalized)

    def _evidence_for_title(self, text: str, title: str) -> str:
        index = text.find(title)
        if index == -1:
            compact = text[:180]
            return compact
        start = max(0, index - 40)
        end = min(len(text), index + len(title) + 80)
        return text[start:end]

    def _detect_signals(self, title: str) -> List[str]:
        signal_map = {
            "页面交互": ("选择", "点击", "列表", "按钮", "表单"),
            "业务链路": ("规划", "执行", "提交", "审批"),
            "状态流转": ("状态", "执行", "完成", "取消"),
            "数据一致性": ("列表", "保存", "回显", "同步"),
        }
        signals = []
        for signal, keywords in signal_map.items():
            if any(keyword in title for keyword in keywords):
                signals.append(signal)
        return signals


class GenerationPlannerAgent:
    """根据功能点、覆盖维度和目标数量规划生成子任务。"""

    NONFUNCTIONAL_TAGS = {"性能", "安全", "兼容性", "稳定性"}

    def __init__(self, decomposer: RequirementDecomposerAgent, coverage_auditor: "CoverageAuditorAgent"):
        self.decomposer = decomposer
        self.coverage_auditor = coverage_auditor

    def plan(
        self,
        bundle: NormalizedRequirementBundle,
        target_count: int,
        preferences: GenerationPreferences,
        features: Optional[List[RequirementFeature]] = None,
    ) -> GenerationPlan:
        required_coverages = self._required_coverages(bundle, target_count, preferences)
        features = features or self.decomposer.decompose(bundle.raw_input)
        selected_features = features or [RequirementFeature("F01", "需求核心功能", bundle.summary)]
        counts = self._distribute_counts(target_count, len(selected_features))
        subtasks = []
        for index, (feature, request_count) in enumerate(zip(selected_features, counts)):
            coverage_tags = self._coverage_for_feature(required_coverages, feature, index)
            agent_role = (
                "nonfunctional-case-generator"
                if any(tag in self.NONFUNCTIONAL_TAGS for tag in coverage_tags)
                else "functional-case-generator"
            )
            subtasks.append(
                GenerationSubtask(
                    agent_role=agent_role,
                    coverage_tags=coverage_tags,
                    request_count=request_count,
                    feature_id=feature.feature_id,
                    feature_title=feature.title,
                    requirement_excerpt=feature.evidence,
                )
            )
        return GenerationPlan(
            target_count=target_count,
            required_coverages=required_coverages,
            features=features,
            subtasks=subtasks,
        )

    def _required_coverages(
        self,
        bundle: NormalizedRequirementBundle,
        target_count: int,
        preferences: GenerationPreferences,
    ) -> List[str]:
        required = self.coverage_auditor.required_coverages_for_target(target_count, bundle)
        for point in preferences.focus_points:
            if point in {"性能", "安全", "兼容性", "稳定性"} and point not in bundle.nonfunctional_focus_tags:
                continue
            if point not in required:
                required.append(point)
        return required

    def _distribute_counts(self, target_count: int, feature_count: int) -> List[int]:
        if feature_count <= 0:
            return []
        base = max(1, target_count // feature_count)
        remainder = max(0, target_count - base * feature_count)
        return [base + (1 if index < remainder else 0) for index in range(feature_count)]

    def _coverage_for_feature(
        self,
        required_coverages: List[str],
        feature: RequirementFeature,
        index: int,
    ) -> List[str]:
        tags: List[str] = []
        for signal in feature.signals:
            if signal not in tags:
                tags.append(signal)
        if required_coverages:
            tags.append(required_coverages[index % len(required_coverages)])
            if len(required_coverages) > 1:
                tags.append(required_coverages[(index + 1) % len(required_coverages)])
        deduped: List[str] = []
        for tag in tags:
            if tag and tag not in deduped:
                deduped.append(tag)
        return deduped or ["主流程"]


class LightweightCaseReviewerAgent:
    """不用额外调用 LLM 的本地轻量评审器。"""

    def __init__(self, coverage_auditor: "CoverageAuditorAgent"):
        self.coverage_auditor = coverage_auditor

    def review_cases(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        qualified_cases = []
        for case in test_cases:
            steps = case.get("test_steps") or []
            expected = case.get("expected_results") or []
            if not case.get("description") or not steps or not expected:
                continue
            if len(steps) != len(expected):
                continue
            next_case = dict(case)
            coverage_tags = sorted(self.coverage_auditor.detect_coverage_tags(next_case))
            next_case["_coverage_tags"] = coverage_tags
            next_case["_quality_score"] = self._score_case(next_case, coverage_tags)
            next_case["_quality_recommendation"] = "轻量评审通过"
            next_case["_quality_review"] = {
                "mode": "local_lightweight",
                "checks": ["required_fields", "step_expected_alignment", "coverage_keyword_signal"],
            }
            qualified_cases.append(next_case)
        return qualified_cases

    def _score_case(self, case: Dict[str, Any], coverage_tags: List[str]) -> int:
        score = 7
        if coverage_tags:
            score += 1
        if len(case.get("test_steps") or []) >= 2:
            score += 1
        return min(score, 9)


class CoverageMergerAgent:
    """合并多 worker 候选用例，并优先保留功能点和覆盖维度更完整的结果。"""

    def __init__(
        self,
        coverage_auditor: "CoverageAuditorAgent",
        deduplicate_cases,
        quality_filter_cases,
        select_cases_for_target,
    ):
        self.coverage_auditor = coverage_auditor
        self.deduplicate_cases = deduplicate_cases
        self.quality_filter_cases = quality_filter_cases
        self.select_cases_for_target = select_cases_for_target

    def merge(
        self,
        candidate_cases: List[Dict[str, Any]],
        target_count: int,
        bundle: NormalizedRequirementBundle,
        plan: GenerationPlan,
    ) -> CoverageMergeResult:
        # 极速生成遵循“模型返回多少展示多少”，不再用去重压缩返回数量。
        deduped_cases = list(candidate_cases)
        qualified_cases = self.quality_filter_cases(deduped_cases)
        retained_cases = self.select_cases_for_target(qualified_cases, target_count)
        missing_coverages = self.coverage_auditor.collect_missing_coverages(
            retained_cases,
            target_count,
            bundle,
        )
        return CoverageMergeResult(
            deduped_cases=deduped_cases,
            qualified_cases=qualified_cases,
            retained_cases=retained_cases,
            missing_coverages=missing_coverages,
        )


class AgentRunTrace:
    def __init__(self, mode: str, target_count: int, config_snapshot: Dict[str, Any]):
        self._started_at = time.perf_counter()
        self._data: Dict[str, Any] = {
            "request_id": uuid.uuid4().hex,
            "mode": mode,
            "status": "running",
            "target_count": target_count,
            "returned_count": 0,
            "total_elapsed_ms": 0.0,
            "config": config_snapshot,
            "metadata": {},
            "steps": [],
            "errors": [],
        }

    @contextmanager
    def stage(self, name: str, **metadata):
        started_at = time.perf_counter()
        step = {
            "name": name,
            "elapsed_ms": 0.0,
            "metadata": dict(metadata),
        }
        try:
            yield step
        except Exception as exc:
            step["error"] = str(exc)
            raise
        finally:
            step["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
            self._data["steps"].append(step)

    def update(self, **metadata) -> None:
        self._data["metadata"].update(metadata)

    def fail(self, exc: Exception) -> None:
        self._data["errors"].append(str(exc))

    def finish(self, status: str, returned_count: int) -> Dict[str, Any]:
        self._data["status"] = status
        self._data["returned_count"] = returned_count
        self._data["total_elapsed_ms"] = round((time.perf_counter() - self._started_at) * 1000, 2)
        return self.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self._data,
            "metadata": dict(self._data["metadata"]),
            "steps": [
                {
                    **step,
                    "metadata": dict(step.get("metadata") or {}),
                }
                for step in self._data["steps"]
            ],
            "errors": list(self._data["errors"]),
        }


class RequirementNormalizerAgent:
    FUNCTIONAL_FOCUS_TAGS = ["主流程", "关键分支", "边界条件", "异常处理"]
    CATEGORY_TO_COVERAGE = {
        "性能测试": "性能",
        "安全测试": "安全",
        "兼容性测试": "兼容性",
        "稳定性测试": "稳定性",
    }

    def normalize(
        self,
        input_text: str,
        input_type: str,
        case_categories: List[str],
    ) -> NormalizedRequirementBundle:
        clean_text = (input_text or "").strip()
        summary_lines = [line.strip() for line in clean_text.splitlines() if line.strip()][:8]
        summary = "\n".join(f"- {line}" for line in summary_lines) if summary_lines else clean_text
        requested_nonfunctional = []
        for category in case_categories:
            coverage = self.CATEGORY_TO_COVERAGE.get(category)
            if coverage and coverage not in requested_nonfunctional:
                requested_nonfunctional.append(coverage)
        return NormalizedRequirementBundle(
            raw_input=clean_text,
            input_type=input_type,
            summary=summary,
            functional_focus_tags=list(self.FUNCTIONAL_FOCUS_TAGS),
            nonfunctional_focus_tags=requested_nonfunctional,
        )


class CoverageAuditorAgent:
    def __init__(self, coverage_keywords: Dict[str, tuple[str, ...]]):
        self.coverage_keywords = coverage_keywords

    def required_coverages_for_target(
        self,
        target_count: int,
        bundle: NormalizedRequirementBundle,
    ) -> List[str]:
        required = list(bundle.functional_focus_tags)
        for tag in bundle.nonfunctional_focus_tags:
            if tag not in required:
                required.append(tag)
        return required

    def detect_coverage_tags(self, case: Dict[str, Any]) -> Set[str]:
        text = " ".join(
            [case.get("description", "")]
            + case.get("test_steps", [])
            + case.get("expected_results", [])
        ).lower()
        coverage_tags: Set[str] = set()
        for tag, keywords in self.coverage_keywords.items():
            if any(keyword.lower() in text for keyword in keywords):
                coverage_tags.add(tag)
        return coverage_tags

    def collect_missing_coverages(
        self,
        cases: List[Dict[str, Any]],
        target_count: int,
        bundle: NormalizedRequirementBundle,
    ) -> List[str]:
        covered: Set[str] = set()
        for case in cases:
            covered.update(case.get("_coverage_tags") or self.detect_coverage_tags(case))
        return [tag for tag in self.required_coverages_for_target(target_count, bundle) if tag not in covered]


class ParallelGenerationWorkerAgent:
    def __init__(
        self,
        agent_role: str,
        llm_service: BaseLLMService,
        prompt: TestCaseGeneratorPrompt,
        parser,
        logger,
    ):
        self.agent_role = agent_role
        self.llm_service = llm_service
        self.prompt = prompt
        self.parser = parser
        self.logger = logger

    def generate(
        self,
        requirements: str,
        case_design_methods: str,
        case_categories: str,
        knowledge_context: Union[str, RAGContextResult],
        subtask: GenerationSubtask,
        existing_case_summaries: List[str],
        retry_round: int,
        requirement_summary: str,
    ) -> List[Dict[str, Any]]:
        messages = self.prompt.format_messages(
            requirements=requirements,
            case_design_methods=case_design_methods,
            case_categories=case_categories,
            case_count=0,
            knowledge_context=knowledge_context,
            missing_coverage_tags=subtask.coverage_tags,
            existing_case_summaries=existing_case_summaries,
            retry_round=retry_round,
            agent_role=self.agent_role,
            focus_coverage_tags=subtask.coverage_tags,
            requirement_summary=requirement_summary,
        )
        self.logger.info(
            "%s 构建后大模型提示词+用户需求消息: \n%s\n%s\n%s",
            self.agent_role,
            "=" * 50,
            messages,
            "=" * 50,
        )
        response = self.llm_service.invoke(messages)
        result = response.content if hasattr(response, "content") else str(response)
        self.logger.info("%s LLM原始响应: \n%s\n%s\n%s", self.agent_role, "=" * 50, result, "=" * 50)
        return self.parser(result)


class TestCaseGeneratorAgent:
    """测试用例生成Agent"""

    GENERATION_PROFILE_RULES = {
        "balanced": {
            "label": "均衡生成",
            "rules": [
                "均衡覆盖功能、异常、边界和非功能场景。",
                "不要让某一种场景压倒其他关键覆盖维度。",
            ],
        },
        "feature_first": {
            "label": "功能点优先",
            "rules": [
                "尽量拆出更多功能点，每个明确按钮、入口、字段、状态、列表、详情都可以独立成 case。",
                "优先扩大功能覆盖面，避免只围绕一个主流程反复变化描述。",
            ],
        },
        "exception_first": {
            "label": "异常边界优先",
            "rules": [
                "增加失败路径、非法输入、边界值、空值、超时、中断、重复提交和错误提示场景。",
                "异常 case 必须写清触发条件、系统提示和恢复结果。",
            ],
        },
        "business_flow": {
            "label": "业务链路优先",
            "rules": [
                "围绕真实业务闭环生成，写清前置条件、操作路径、数据变化、列表回显和上下游联动。",
                "优先覆盖跨页面、跨状态、跨模块的数据一致性验证。",
            ],
        },
        "nonfunctional_first": {
            "label": "非功能优先",
            "rules": [
                "增加性能、安全、兼容性、稳定性相关 case 的占比。",
                "非功能 case 必须给出可观察指标、触发条件和验收标准。",
            ],
        },
    }
    FOCUS_STRENGTH_RULES = {
        "light": "轻度：只作为补充倾向，不改变整体覆盖均衡。",
        "medium": "中度：明显提高这些偏向点的覆盖优先级。",
        "strong": "强度：优先围绕这些偏向点生成；如果数量有限，先满足偏向点。",
    }
    ALLOWED_FOCUS_POINTS = {
        "主流程",
        "功能子点",
        "页面交互",
        "业务链路",
        "状态流转",
        "权限差异",
        "边界条件",
        "异常处理",
        "数据一致性",
        "上下游联动",
        "性能",
        "安全",
        "兼容性",
        "稳定性",
    }

    COVERAGE_KEYWORDS = {
        "主流程": ("主流程", "正常", "成功", "标准", "基础", "happy path"),
        "关键分支": ("分支", "条件", "角色", "状态", "不同路径", "切换"),
        "边界条件": ("边界", "最大", "最小", "上限", "下限", "临界", "长度", "超长", "超短"),
        "异常处理": ("异常", "错误", "失败", "拒绝", "无效", "不存在", "超时", "告警"),
        "性能": ("性能", "响应时间", "耗时", "并发", "吞吐", "负载", "容量", "压力"),
        "兼容性": ("兼容", "浏览器", "平台", "版本", "机型", "分辨率"),
        "安全": ("安全", "权限", "鉴权", "认证", "授权", "token", "越权", "注入", "敏感"),
        "稳定性": ("稳定", "恢复", "重试", "幂等", "断网", "重连", "重启", "抖动"),
    }

    STOPWORDS = {"测试", "用例", "验证", "校验", "检查", "流程", "场景"}

    def __init__(
        self,
        llm_service: BaseLLMService,
        knowledge_service: KnowledgeService,
        case_design_methods: List[str],
        case_categories: List[str],
        case_count: int = 10,
        reviewer_agent: Optional[TestCaseReviewerAgent] = None,
        quality_config: Optional[Dict[str, Any]] = None,
        generation_preferences: Optional[Dict[str, Any]] = None,
    ):
        self.llm_service = llm_service
        self.case_design_methods = case_design_methods
        self.case_categories = case_categories
        self.case_count = case_count
        self.knowledge_service = knowledge_service
        self.prompt = TestCaseGeneratorPrompt()
        self.logger = get_logger(self.__class__.__name__)
        default_quality_config = dict(getattr(settings, "TEST_CASE_GENERATION_CONFIG", {}))
        self.quality_config = {
            **default_quality_config,
            **(quality_config or {}),
        }
        self.reviewer_agent = reviewer_agent or TestCaseReviewerAgent(llm_service, knowledge_service)
        self._review_cache: Dict[str, Dict[str, Any]] = {}
        self.fast_mode = bool(self.quality_config.get("fast_mode", True))
        self.enable_llm_review = bool(self.quality_config.get("enable_llm_review", False))
        self.fast_single_call = bool(self.quality_config.get("fast_single_call", True))
        self.generation_preferences = self._normalize_generation_preferences(generation_preferences or {})
        self.last_run_trace: Dict[str, Any] = {}
        self.requirement_normalizer = RequirementNormalizerAgent()
        self.coverage_auditor = CoverageAuditorAgent(self.COVERAGE_KEYWORDS)
        self.requirement_decomposer = RequirementDecomposerAgent()
        self.generation_planner = GenerationPlannerAgent(self.requirement_decomposer, self.coverage_auditor)
        self.lightweight_reviewer = LightweightCaseReviewerAgent(self.coverage_auditor)
        self.coverage_merger = CoverageMergerAgent(
            coverage_auditor=self.coverage_auditor,
            deduplicate_cases=self._deduplicate_test_cases,
            quality_filter_cases=self._quality_filter_cases,
            select_cases_for_target=self._select_cases_for_target,
        )
        self.functional_generator = ParallelGenerationWorkerAgent(
            agent_role="functional-case-generator",
            llm_service=llm_service,
            prompt=self.prompt,
            parser=self._parse_generated_cases,
            logger=self.logger,
        )
        self.nonfunctional_generator = ParallelGenerationWorkerAgent(
            agent_role="nonfunctional-case-generator",
            llm_service=llm_service,
            prompt=self.prompt,
            parser=self._parse_generated_cases,
            logger=self.logger,
        )

    def generate(self, input_text: str, input_type: str = "requirement") -> List[Dict[str, Any]]:
        """生成测试用例"""
        self.logger.info("开始生成测试用例,进入生成测试用例的TestCaseGeneratorAgent")
        effective_target_count = self._get_effective_target_count()
        trace = AgentRunTrace(
            mode=self._generation_mode(),
            target_count=effective_target_count,
            config_snapshot=self._trace_config_snapshot(),
        )
        self.last_run_trace = trace.to_dict()
        final_cases: List[Dict[str, Any]] = []
        status = "failed"

        try:
            with trace.stage("knowledge_retrieval") as step:
                knowledge_context = self._get_knowledge_context(input_text)
                knowledge_preview = (
                    knowledge_context.context_text
                    if isinstance(knowledge_context, RAGContextResult)
                    else str(knowledge_context or "")
                )
                step["metadata"].update({
                    "has_context": bool(knowledge_preview.strip()),
                    "context_chars": len(knowledge_preview),
                })
            self.logger.info(f"获取到知识库上下文: \n{'='*50}\n{knowledge_preview}\n{'='*50}")

            with trace.stage("requirement_normalization") as step:
                requirement_bundle = self.requirement_normalizer.normalize(
                    input_text=input_text,
                    input_type=input_type,
                    case_categories=self.case_categories,
                )
                step["metadata"].update({
                    "input_type": input_type,
                    "summary_chars": len(requirement_bundle.summary),
                })

            with trace.stage("requirement_decomposition") as step:
                requirement_features = self.requirement_decomposer.decompose(requirement_bundle.raw_input)
                step["metadata"].update({
                    "feature_count": len(requirement_features),
                    "features": [
                        {
                            "feature_id": feature.feature_id,
                            "title": feature.title,
                            "signals": feature.signals,
                        }
                        for feature in requirement_features
                    ],
                })

            with trace.stage("generation_planning") as step:
                generation_plan = self.generation_planner.plan(
                    bundle=requirement_bundle,
                    target_count=effective_target_count,
                    preferences=self.generation_preferences,
                    features=requirement_features,
                )
                plan_payload = {
                    "required_coverages": generation_plan.required_coverages,
                    "subtask_count": len(generation_plan.subtasks),
                    "subtasks": [
                        {
                            "agent_role": subtask.agent_role,
                            "feature_id": subtask.feature_id,
                            "feature_title": subtask.feature_title,
                            "coverage_tags": subtask.coverage_tags,
                            "request_count": subtask.request_count,
                        }
                        for subtask in generation_plan.subtasks
                    ],
                }
                step["metadata"].update(plan_payload)
                trace.update(
                    feature_count=len(generation_plan.features),
                    planned_subtask_count=len(generation_plan.subtasks),
                    required_coverages=generation_plan.required_coverages,
                )

            retained_cases: List[Dict[str, Any]] = []
            if self.fast_mode and self.fast_single_call:
                with trace.stage(
                    "llm_generation",
                    requested_count=effective_target_count,
                    subtask_count=len(generation_plan.subtasks),
                ) as step:
                    step["metadata"]["mode"] = "planned_parallel"

                with trace.stage("parallel_generation", subtask_count=len(generation_plan.subtasks)) as step:
                    candidate_cases = self._run_generation_subtasks(
                        generation_subtasks=generation_plan.subtasks,
                        requirement_bundle=requirement_bundle,
                        knowledge_context=knowledge_context,
                        existing_case_summaries=[],
                        retry_round=0,
                    )
                    step["metadata"]["candidate_count"] = len(candidate_cases)

                with trace.stage("quality_filtering", candidate_count=len(candidate_cases)) as step:
                    merge_result = self.coverage_merger.merge(
                        candidate_cases=candidate_cases,
                        target_count=effective_target_count,
                        bundle=requirement_bundle,
                        plan=generation_plan,
                    )
                    retained_cases = merge_result.retained_cases
                    missing_coverages = merge_result.missing_coverages
                    step["metadata"].update({
                        "deduped_count": len(merge_result.deduped_cases),
                        "qualified_count": len(merge_result.qualified_cases),
                        "retained_count": len(retained_cases),
                        "missing_coverages": missing_coverages,
                    })
                    trace.update(
                        candidate_count=len(candidate_cases),
                        deduped_count=len(merge_result.deduped_cases),
                        qualified_count=len(merge_result.qualified_cases),
                        retained_count=len(retained_cases),
                        missing_coverages=missing_coverages,
                    )
                self.logger.info(
                    "极速规划并行生成结束：候选=%d，保留=%d，缺失覆盖=%s",
                    len(candidate_cases),
                    len(retained_cases),
                    missing_coverages,
                )
                if not retained_cases:
                    raise ValueError("没有找到任何合法且达标的测试用例")
                with trace.stage("finalization", retained_count=len(retained_cases)) as step:
                    final_cases = self._finalize_cases(retained_cases, effective_target_count)
                    step["metadata"]["returned_count"] = len(final_cases)
                    trace.update(returned_count=len(final_cases))
                status = "success"
                return final_cases

            max_total_rounds = max(1, int(self.quality_config.get("max_total_rounds", 3)))
            if self.fast_mode:
                max_total_rounds = 1

            total_candidate_count = 0
            for round_index in range(max_total_rounds):
                with trace.stage(f"round_{round_index + 1}_planning") as step:
                    missing_coverages = self.coverage_auditor.collect_missing_coverages(
                        retained_cases,
                        effective_target_count,
                        requirement_bundle,
                    )
                    if round_index > 0 and len(retained_cases) >= effective_target_count and not missing_coverages:
                        step["metadata"].update({
                            "skipped": True,
                            "reason": "target_count_and_coverage_satisfied",
                        })
                        break

                    request_count = self._get_request_case_count(
                        effective_target_count,
                        len(retained_cases),
                        round_index,
                    )
                    generation_subtasks = self._build_generation_subtasks(
                        requirement_bundle=requirement_bundle,
                        missing_coverages=missing_coverages,
                        request_count=request_count,
                        round_index=round_index,
                    )
                    step["metadata"].update({
                        "missing_coverages": missing_coverages,
                        "request_count": request_count,
                        "subtasks": [
                            {
                                "agent_role": subtask.agent_role,
                                "coverage_tags": subtask.coverage_tags,
                                "request_count": subtask.request_count,
                            }
                            for subtask in generation_subtasks
                        ],
                    })

                with trace.stage(f"round_{round_index + 1}_generation") as step:
                    candidate_cases = self._run_generation_subtasks(
                        generation_subtasks=generation_subtasks,
                        requirement_bundle=requirement_bundle,
                        knowledge_context=knowledge_context,
                        existing_case_summaries=self._build_case_summaries(retained_cases),
                        retry_round=round_index,
                    )
                    total_candidate_count += len(candidate_cases)
                    step["metadata"]["candidate_count"] = len(candidate_cases)

                with trace.stage(f"round_{round_index + 1}_quality_filtering") as step:
                    merged_cases = self._deduplicate_test_cases(retained_cases + candidate_cases)
                    qualified_cases = self._quality_filter_cases(merged_cases)
                    retained_cases = self._select_cases_for_target(qualified_cases, effective_target_count)
                    round_missing_coverages = self.coverage_auditor.collect_missing_coverages(
                        retained_cases,
                        effective_target_count,
                        requirement_bundle,
                    )
                    step["metadata"].update({
                        "merged_count": len(merged_cases),
                        "qualified_count": len(qualified_cases),
                        "retained_count": len(retained_cases),
                        "missing_coverages": round_missing_coverages,
                    })

                self.logger.info(
                    "第 %d 轮结束：候选=%d，保留=%d，缺失覆盖=%s",
                    round_index + 1,
                    len(candidate_cases),
                    len(retained_cases),
                    round_missing_coverages,
                )

            trace.update(
                candidate_count=total_candidate_count,
                retained_count=len(retained_cases),
                missing_coverages=self.coverage_auditor.collect_missing_coverages(
                    retained_cases,
                    effective_target_count,
                    requirement_bundle,
                ),
            )

            if not retained_cases:
                raise ValueError("没有找到任何合法且达标的测试用例")

            with trace.stage("finalization", retained_count=len(retained_cases)) as step:
                final_cases = self._finalize_cases(retained_cases, effective_target_count)
                step["metadata"]["returned_count"] = len(final_cases)
                trace.update(returned_count=len(final_cases))
            if not final_cases:
                raise ValueError("没有找到任何合法且达标的测试用例")
            status = "success"
            return final_cases
        except Exception as exc:
            trace.fail(exc)
            raise
        finally:
            self.last_run_trace = trace.finish(status=status, returned_count=len(final_cases))

    def _generation_mode(self) -> str:
        if self.fast_mode and self.fast_single_call:
            return "fast_single_call"
        if self.fast_mode:
            return "fast_parallel"
        if self.enable_llm_review:
            return "deep_with_review"
        return "deep_local_filter"

    def _trace_config_snapshot(self) -> Dict[str, Any]:
        return {
            "fast_mode": self.fast_mode,
            "fast_single_call": self.fast_single_call,
            "enable_llm_review": self.enable_llm_review,
            "case_count": self.case_count,
            "case_categories": list(self.case_categories),
            "case_design_methods": list(self.case_design_methods),
            "generation_preferences": self._generation_preferences_dict(),
            "default_target_count": self.quality_config.get("default_target_count"),
            "max_total_rounds": self.quality_config.get("max_total_rounds"),
        }

    def _normalize_generation_preferences(self, preferences: Dict[str, Any]) -> GenerationPreferences:
        profile = str(
            preferences.get("generation_profile")
            or preferences.get("profile")
            or "balanced"
        ).strip()
        if profile not in self.GENERATION_PROFILE_RULES:
            profile = "balanced"

        raw_focus_points = preferences.get("focus_points") or []
        if isinstance(raw_focus_points, str):
            raw_focus_points = [raw_focus_points]
        focus_points = []
        for item in raw_focus_points:
            point = str(item).strip()
            if point in self.ALLOWED_FOCUS_POINTS and point not in focus_points:
                focus_points.append(point)

        strength = str(preferences.get("focus_strength") or "medium").strip()
        if strength not in self.FOCUS_STRENGTH_RULES:
            strength = "medium"
        return GenerationPreferences(
            generation_profile=profile,
            focus_points=focus_points,
            focus_strength=strength,
        )

    def _generation_preferences_dict(self) -> Dict[str, Any]:
        return {
            "generation_profile": self.generation_preferences.generation_profile,
            "focus_points": list(self.generation_preferences.focus_points),
            "focus_strength": self.generation_preferences.focus_strength,
        }

    def _get_effective_target_count(self) -> int:
        if self.case_count and self.case_count > 0:
            return self.case_count
        return max(1, int(self.quality_config.get("default_target_count", 8)))

    def _get_request_case_count(self, target_count: int, current_count: int, round_index: int) -> int:
        remaining = max(target_count - current_count, 0)
        multiplier = max(1, int(self.quality_config.get("candidate_multiplier", 2)))
        minimum = max(1, int(self.quality_config.get("minimum_candidate_count", 8)))
        if round_index == 0:
            return max(remaining * multiplier, minimum)
        return max(remaining * multiplier, max(1, len(self._required_coverages_for_target(target_count))))

    def _build_generation_subtasks(
        self,
        requirement_bundle: NormalizedRequirementBundle,
        missing_coverages: List[str],
        request_count: int,
        round_index: int,
    ) -> List[GenerationSubtask]:
        functional_focus = [
            item for item in missing_coverages if item in requirement_bundle.functional_focus_tags
        ]
        nonfunctional_focus = [
            item for item in missing_coverages if item in requirement_bundle.nonfunctional_focus_tags
        ]
        if round_index == 0 and not functional_focus:
            functional_focus = list(requirement_bundle.functional_focus_tags)
        if round_index == 0 and not nonfunctional_focus and requirement_bundle.nonfunctional_focus_tags:
            nonfunctional_focus = list(requirement_bundle.nonfunctional_focus_tags)

        planned = []
        if functional_focus:
            planned.append(("functional-case-generator", functional_focus))
        if nonfunctional_focus:
            planned.append(("nonfunctional-case-generator", nonfunctional_focus))
        if not planned:
            planned.append(("functional-case-generator", list(requirement_bundle.functional_focus_tags)))

        base_count = max(1, request_count // len(planned))
        remainder = max(0, request_count - base_count * len(planned))
        subtasks = []
        for index, (agent_role, coverage_tags) in enumerate(planned):
            subtasks.append(
                GenerationSubtask(
                    agent_role=agent_role,
                    coverage_tags=coverage_tags,
                    request_count=base_count + (1 if index < remainder else 0),
                )
            )
        return subtasks

    def _run_generation_subtasks(
        self,
        generation_subtasks: List[GenerationSubtask],
        requirement_bundle: NormalizedRequirementBundle,
        knowledge_context: Union[str, RAGContextResult],
        existing_case_summaries: List[str],
        retry_round: int,
    ) -> List[Dict[str, Any]]:
        if not generation_subtasks:
            return []
        if len(generation_subtasks) == 1:
            return self._run_single_generation_subtask(
                generation_subtasks[0],
                requirement_bundle,
                knowledge_context,
                existing_case_summaries,
                retry_round,
            )

        results_by_index: Dict[int, List[Dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=len(generation_subtasks), thread_name_prefix="case-agent") as executor:
            future_map = {
                executor.submit(
                    self._run_single_generation_subtask,
                    subtask,
                    requirement_bundle,
                    knowledge_context,
                    existing_case_summaries,
                    retry_round,
                ): (index, subtask)
                for index, subtask in enumerate(generation_subtasks)
            }
            for future in as_completed(future_map):
                index, _subtask = future_map[future]
                results_by_index[index] = future.result()

        merged_results: List[Dict[str, Any]] = []
        for index in range(len(generation_subtasks)):
            merged_results.extend(results_by_index.get(index, []))
        return merged_results

    def _run_single_generation_subtask(
        self,
        subtask: GenerationSubtask,
        requirement_bundle: NormalizedRequirementBundle,
        knowledge_context: Union[str, RAGContextResult],
        existing_case_summaries: List[str],
        retry_round: int,
    ) -> List[Dict[str, Any]]:
        worker = (
            self.nonfunctional_generator
            if subtask.agent_role == "nonfunctional-case-generator"
            else self.functional_generator
        )
        return worker.generate(
            requirements=requirement_bundle.raw_input,
            case_design_methods=",".join(self.case_design_methods) if self.case_design_methods else "",
            case_categories=",".join(self.case_categories) if self.case_categories else "",
            knowledge_context=knowledge_context,
            subtask=subtask,
            existing_case_summaries=existing_case_summaries,
            retry_round=retry_round,
            requirement_summary=self._build_subtask_requirement_summary(requirement_bundle, subtask),
        )

    def _build_subtask_requirement_summary(
        self,
        requirement_bundle: NormalizedRequirementBundle,
        subtask: GenerationSubtask,
    ) -> str:
        summary_lines = [self._append_generation_preferences_to_summary(requirement_bundle.summary)]
        if subtask.feature_title:
            summary_lines.extend(
                [
                    "",
                    f"需求功能点：{subtask.feature_title}",
                    f"功能点ID：{subtask.feature_id or '未分配'}",
                    f"功能点证据：{subtask.requirement_excerpt or subtask.feature_title}",
                    "本 worker 只生成该功能点相关 case，避免扩散到其他功能点。",
                    "本 worker 不限制返回数量；围绕该功能点生成所有有价值且不重复的 case。",
                ]
            )
        return "\n".join(summary_lines)

    def _generate_fast_candidates(
        self,
        requirement_bundle: NormalizedRequirementBundle,
        knowledge_context: Union[str, RAGContextResult],
        target_count: int,
    ) -> List[Dict[str, Any]]:
        messages = self._build_fast_generation_messages(
            requirement_bundle=requirement_bundle,
            knowledge_context=knowledge_context,
            target_count=target_count,
        )
        self.logger.info("fast-case-generator 构建后短提示词: \n%s\n%s\n%s", "=" * 50, messages, "=" * 50)
        response = self.llm_service.invoke(messages)
        result = response.content if hasattr(response, "content") else str(response)
        self.logger.info("fast-case-generator LLM原始响应: \n%s\n%s\n%s", "=" * 50, result, "=" * 50)
        return self._parse_generated_cases(result)

    def _build_fast_generation_messages(
        self,
        requirement_bundle: NormalizedRequirementBundle,
        knowledge_context: Union[str, RAGContextResult],
        target_count: int,
    ) -> List[Any]:
        required_coverages = self.coverage_auditor.required_coverages_for_target(
            target_count,
            requirement_bundle,
        )
        requirement_text = self._compact_requirement_text(requirement_bundle.raw_input, max_chars=1200)
        knowledge_text = self._compact_knowledge_text(knowledge_context, max_chars=500)
        categories = "、".join(self.case_categories) if self.case_categories else "功能测试"
        methods = "、".join(self.case_design_methods[:4]) if self.case_design_methods else "等价类、边界值、场景法"
        preference_lines = self._format_generation_preference_lines()
        system = "\n".join(
            [
                "你是熟悉业务系统测试设计的高级测试专家。",
                "目标：基于需求和知识库证据，快速生成业务贴合、可执行、可验证、不重复的测试用例。",
                "只输出 JSON 数组，不要 Markdown，不要解释。",
                "每个元素必须包含 description、test_steps、expected_results。",
                "test_steps 与 expected_results 数量必须一致。",
                "每条用例最多 4 个步骤，句子要短，但必须写清业务动作和可观察结果。",
            ]
        )
        human = "\n".join(
            [
                f"请尽可能完整生成测试用例，类型：{categories}。",
                f"优先使用方法：{methods}。",
                f"必须尽量覆盖：{'、'.join(required_coverages)}。",
                "未选择的测试类型不要生成独立 case；性能、安全、兼容、稳定性仅在测试类型、偏向点或需求原文明示时输出。",
                *preference_lines,
                "生成原则：",
                "1. 优先围绕需求中的真实业务链路生成，不要泛化到无关功能。",
                "2. 每条用例必须明确测试对象、操作动作、关键状态和业务结果。",
                "3. 覆盖成功路径、失败路径、状态切换、权限差异、异常提示中的高价值场景。",
                "4. 如果需求涉及按钮、弹窗、列表、详情、上传、调度、审批、启停、更新、删除，必须体现真实交互。",
                "5. description 禁止写“验证功能正常”这类空泛描述。",
                "强约束：不要为了凑数量生成重复或低价值 case；每条 test_steps 最多 4 条，expected_results 最多 4 条。",
                "",
                "需求：",
                requirement_text,
                "",
                "知识库证据：",
                knowledge_text or "无",
                "",
                "返回 JSON 数组，格式示例：",
                '[{"description":"...","test_steps":["1. ...","2. ..."],"expected_results":["1. ...","2. ..."]}]',
            ]
        )
        return [SystemMessage(content=system), HumanMessage(content=human)]

    def _format_generation_preference_lines(self) -> List[str]:
        profile = self.GENERATION_PROFILE_RULES[self.generation_preferences.generation_profile]
        strength_rule = self.FOCUS_STRENGTH_RULES[self.generation_preferences.focus_strength]
        focus_points = "、".join(self.generation_preferences.focus_points) or "未指定，按生成模式自动判断"
        lines = [
            "个性化生成偏向：",
            f"- 生成模式：{profile['label']}。",
            f"- 偏向点：{focus_points}。",
            f"- 偏向强度：{strength_rule}",
            "- 偏向执行规则：",
        ]
        lines.extend(f"  - {rule}" for rule in profile["rules"])
        if self.generation_preferences.focus_points:
            lines.append("  - 选中的偏向点必须优先覆盖；每条 case 尽量体现至少一个偏向点。")
        return lines

    def _append_generation_preferences_to_summary(self, summary: str) -> str:
        return "\n".join([summary, *self._format_generation_preference_lines()])

    def _parse_generated_cases(self, result: str) -> List[Dict[str, Any]]:
        try:
            json_str = self._extract_json_from_response(result)
            if not json_str:
                raise ValueError("无法从响应中提取有效的JSON数据")
            test_cases = json.loads(json_str)
            self.logger.info("_validate_test_cases处理前的用例个数: %d", len(test_cases))
            return self._validate_test_cases(test_cases)
        except Exception as e:
            raise ValueError(f"无法解析生成的测试用例: {str(e)}\n原始响应: {result}")

    def _get_knowledge_context(self, input_text: str) -> Union[str, RAGContextResult]:
        """获取相关知识上下文"""
        try:
            if hasattr(self.knowledge_service, "search_relevant_knowledge_context"):
                top_k = 2 if self.fast_mode else 3
                max_chars_per_chunk = 220 if self.fast_mode else 350
                max_total_chars = 500 if self.fast_mode else 1200
                knowledge = self.knowledge_service.search_relevant_knowledge_context(
                    input_text,
                    top_k=top_k,
                    max_chars_per_chunk=max_chars_per_chunk,
                    max_total_chars=max_total_chars,
                )
            else:
                knowledge = self.knowledge_service.search_relevant_knowledge(input_text)
            if knowledge:
                return knowledge
        except Exception as e:
            self.logger.warning(f"获取知识上下文失败: {str(e)}")
        return ""

    def _validate_test_cases(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """验证并修复测试用例格式"""
        valid_test_cases = []
        required_fields = {"description", "test_steps", "expected_results"}

        for i, test_case in enumerate(test_cases):
            try:
                if not isinstance(test_case, dict):
                    self.logger.warning(f"测试用例 #{i+1} 不是字典格式，已跳过")
                    continue

                missing_fields = required_fields - set(test_case.keys())
                if missing_fields:
                    self.logger.warning(f"测试用例 #{i+1} 缺少必要字段: {missing_fields}，已跳过")
                    continue

                if not isinstance(test_case["description"], str):
                    self.logger.warning(f"测试用例 #{i+1} 的description不是字符串格式，已跳过")
                    continue

                if not isinstance(test_case["test_steps"], list):
                    self.logger.warning(f"测试用例 #{i+1} 的test_steps格式无法修复，已跳过")
                    continue

                if not isinstance(test_case["expected_results"], list):
                    self.logger.warning(f"测试用例 #{i+1} 的expected_results格式无法修复，已跳过")
                    continue

                if not test_case["description"].strip():
                    self.logger.warning(f"测试用例 #{i+1} 的description为空，已跳过")
                    continue

                if not test_case["test_steps"]:
                    self.logger.warning(f"测试用例 #{i+1} 的test_steps为空，已跳过")
                    continue

                if not test_case["expected_results"]:
                    self.logger.warning(f"测试用例 #{i+1} 的expected_results为空，已跳过")
                    continue

                normalized_case = {
                    "description": test_case["description"].strip(),
                    "test_steps": [str(step).strip() for step in test_case["test_steps"] if str(step).strip()],
                    "expected_results": [str(result).strip() for result in test_case["expected_results"] if str(result).strip()],
                }
                if not normalized_case["test_steps"] or not normalized_case["expected_results"]:
                    continue
                valid_test_cases.append(normalized_case)
            except Exception as e:
                self.logger.warning(f"处理测试用例 #{i+1} 时出错: {str(e)}，已跳过")
                continue

        if not valid_test_cases:
            raise ValueError("没有找到任何合法的测试用例")

        self.logger.info(f"共处理 {len(test_cases)} 个测试用例，其中 {len(valid_test_cases)} 个合法")
        return valid_test_cases

    def _deduplicate_test_cases(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped_cases: List[Dict[str, Any]] = []
        for case in test_cases:
            merged = False
            for index, existing in enumerate(deduped_cases):
                if self._is_duplicate_case(existing, case):
                    deduped_cases[index] = self._pick_better_case(existing, case)
                    merged = True
                    break
            if not merged:
                deduped_cases.append(case)
        return deduped_cases

    def _is_duplicate_case(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        left_description = self._normalize_text(left.get("description", ""))
        right_description = self._normalize_text(right.get("description", ""))
        if left_description == right_description:
            return True

        description_similarity = SequenceMatcher(None, left_description, right_description).ratio()
        if description_similarity >= float(self.quality_config.get("dedupe_similarity_threshold", 0.72)):
            return True

        left_keywords = self._extract_keywords(left)
        right_keywords = self._extract_keywords(right)
        overlap = self._keyword_overlap(left_keywords, right_keywords)
        if overlap >= float(self.quality_config.get("keyword_overlap_threshold", 0.6)):
            left_steps = self._normalize_text(" ".join(left.get("test_steps", [])))
            right_steps = self._normalize_text(" ".join(right.get("test_steps", [])))
            return SequenceMatcher(None, left_steps, right_steps).ratio() >= 0.7
        return False

    def _pick_better_case(self, left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
        left_score = int(left.get("_quality_score", 0) or 0)
        right_score = int(right.get("_quality_score", 0) or 0)
        if left_score != right_score:
            return left if left_score > right_score else right
        return left if self._case_richness(left) >= self._case_richness(right) else right

    def _case_richness(self, case: Dict[str, Any]) -> int:
        return (
            len(case.get("description", ""))
            + sum(len(item) for item in case.get("test_steps", []))
            + sum(len(item) for item in case.get("expected_results", []))
        )

    def _extract_keywords(self, case: Dict[str, Any]) -> Set[str]:
        text = " ".join(
            [case.get("description", "")]
            + case.get("test_steps", [])
            + case.get("expected_results", [])
        )
        tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,6}", text.lower())
        return {token for token in tokens if token not in self.STOPWORDS}

    def _keyword_overlap(self, left: Set[str], right: Set[str]) -> float:
        if not left or not right:
            return 0.0
        union = left | right
        if not union:
            return 0.0
        return len(left & right) / len(union)

    def _review_and_filter_cases(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        qualified_cases = []
        min_review_score = int(self.quality_config.get("min_review_score", 7))
        review_payloads = self._review_cases_batch(test_cases)
        for case, review_payload in zip(test_cases, review_payloads):
            score = int(review_payload.get("score") or 0)
            recommendation = str(review_payload.get("recommendation") or "")
            next_case = dict(case)
            next_case["_quality_score"] = score
            next_case["_quality_recommendation"] = recommendation
            next_case["_quality_review"] = review_payload.get("parsed") or {}
            next_case["_coverage_tags"] = sorted(self._detect_coverage_tags(next_case))
            if score >= min_review_score and recommendation != "不通过":
                qualified_cases.append(next_case)
        return qualified_cases

    def _quality_filter_cases(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self.enable_llm_review and not self.fast_mode:
            return self._review_and_filter_cases(test_cases)
        return self._local_quality_filter_cases(test_cases)

    def _local_quality_filter_cases(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        qualified_cases = self.lightweight_reviewer.review_cases(test_cases)
        skipped_count = len(test_cases) - len(qualified_cases)
        if skipped_count:
            self.logger.info("轻量评审过滤掉 %d 条格式或步骤不达标的用例", skipped_count)
        return qualified_cases

    def _review_cases_batch(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not test_cases:
            return []

        review_payloads: List[Optional[Dict[str, Any]]] = [None] * len(test_cases)
        uncached_cases: List[Dict[str, Any]] = []
        uncached_indexes: List[int] = []
        for index, test_case in enumerate(test_cases):
            cache_key = self._review_cache_key(test_case)
            cached = self._review_cache.get(cache_key)
            if cached is not None:
                review_payloads[index] = cached
                continue
            uncached_cases.append(test_case)
            uncached_indexes.append(index)

        if not uncached_cases:
            return [payload or {} for payload in review_payloads]

        batch_review = getattr(self.reviewer_agent, "review_case_batch", None)
        if callable(batch_review):
            try:
                fresh_payloads = batch_review(uncached_cases)
            except Exception as exc:
                self.logger.warning("批量评审失败，回退到逐条评审: %s", exc)
                fresh_payloads = [self.reviewer_agent.review_case_data(case) for case in uncached_cases]
        else:
            fresh_payloads = [self.reviewer_agent.review_case_data(case) for case in uncached_cases]

        for index, test_case, payload in zip(uncached_indexes, uncached_cases, fresh_payloads):
            safe_payload = payload or {}
            self._review_cache[self._review_cache_key(test_case)] = safe_payload
            review_payloads[index] = safe_payload
        return [payload or {} for payload in review_payloads]

    def _review_cache_key(self, test_case: Dict[str, Any]) -> str:
        payload = {
            "description": str(test_case.get("description", "")).strip(),
            "test_steps": [str(item).strip() for item in test_case.get("test_steps", [])],
            "expected_results": [str(item).strip() for item in test_case.get("expected_results", [])],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _required_coverages_for_target(self, target_count: int) -> List[str]:
        bundle = self.requirement_normalizer.normalize("", "requirement", self.case_categories)
        return self.coverage_auditor.required_coverages_for_target(target_count, bundle)

    def _detect_coverage_tags(self, case: Dict[str, Any]) -> Set[str]:
        return self.coverage_auditor.detect_coverage_tags(case)

    def _collect_missing_coverages(self, cases: List[Dict[str, Any]], target_count: int) -> List[str]:
        bundle = self.requirement_normalizer.normalize("", "requirement", self.case_categories)
        return self.coverage_auditor.collect_missing_coverages(cases, target_count, bundle)

    def _select_cases_for_target(self, cases: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
        return sorted(
            cases,
            key=lambda case: (
                int(case.get("_quality_score", 0)),
                len(case.get("_coverage_tags", [])),
                self._case_richness(case),
            ),
            reverse=True,
        )

    def _build_case_summaries(self, cases: List[Dict[str, Any]]) -> List[str]:
        summaries = []
        for case in cases[:8]:
            coverages = "、".join(case.get("_coverage_tags") or self._detect_coverage_tags(case))
            if coverages:
                summaries.append(f"{case.get('description', '')}（覆盖：{coverages}）")
            else:
                summaries.append(case.get("description", ""))
        return summaries

    def _finalize_cases(self, cases: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
        finalized = []
        selected_cases = self._select_cases_for_target(cases, target_count)
        for case in selected_cases:
            cleaned_case = {
                key: value
                for key, value in case.items()
                if not key.startswith("_")
            }
            finalized.append(cleaned_case)
        return finalized

    def _normalize_text(self, text: str) -> str:
        normalized = re.sub(r"[\W_]+", "", str(text).lower())
        normalized = normalized.replace("校验", "验证").replace("帐号", "账号")
        return normalized

    def _compact_requirement_text(self, text: str, max_chars: int) -> str:
        compact = re.sub(r"<[^>]+>", "\n", text or "")
        compact = re.sub(r"&nbsp;|&#160;", " ", compact)
        compact = re.sub(r"\n{2,}", "\n", compact)
        compact = re.sub(r"[ \t]{2,}", " ", compact).strip()
        return compact[:max_chars]

    def _compact_knowledge_text(self, knowledge_context: Union[str, RAGContextResult], max_chars: int) -> str:
        if isinstance(knowledge_context, RAGContextResult):
            text = knowledge_context.context_text or ""
        else:
            text = str(knowledge_context or "")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text[:max_chars]

    def _extract_json_from_response(self, response: str) -> str:
        """从响应中提取JSON部分并进行基础修复"""
        result = ""
        right_format_pattern = r"^\[([\s\S]*)\]$"
        match = re.search(right_format_pattern, response)
        if match:
            result = match.group(0)
        else:
            last_comma_index = response.rfind("},")
            if last_comma_index != -1:
                result = response[: last_comma_index + 1] + "]"
        return result
