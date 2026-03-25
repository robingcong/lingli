from typing import Dict, Any, List, Optional, Set, Union
import json
import re
from difflib import SequenceMatcher

from django.conf import settings

from ..llm.base import BaseLLMService
from ..knowledge.service import KnowledgeService
from ..knowledge.schemas import RAGContextResult
from .prompts import TestCaseGeneratorPrompt
from .reviewer import TestCaseReviewerAgent
from utils.logger_manager import get_logger


class TestCaseGeneratorAgent:
    """测试用例生成Agent"""

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

    def generate(self, input_text: str, input_type: str = "requirement") -> List[Dict[str, Any]]:
        """生成测试用例"""
        self.logger.info("开始生成测试用例,进入生成测试用例的TestCaseGeneratorAgent")
        knowledge_context = self._get_knowledge_context(input_text)
        knowledge_preview = (
            knowledge_context.context_text
            if isinstance(knowledge_context, RAGContextResult)
            else str(knowledge_context or "")
        )
        self.logger.info(f"获取到知识库上下文: \n{'='*50}\n{knowledge_preview}\n{'='*50}")

        effective_target_count = self._get_effective_target_count()
        retained_cases: List[Dict[str, Any]] = []
        max_total_rounds = max(1, int(self.quality_config.get("max_total_rounds", 3)))

        for round_index in range(max_total_rounds):
            missing_coverages = self._collect_missing_coverages(retained_cases, effective_target_count)
            if round_index > 0 and len(retained_cases) >= effective_target_count and not missing_coverages:
                break

            request_count = self._get_request_case_count(effective_target_count, len(retained_cases), round_index)
            candidate_cases = self._generate_candidate_cases(
                input_text=input_text,
                knowledge_context=knowledge_context,
                request_count=request_count,
                missing_coverages=missing_coverages,
                existing_case_summaries=self._build_case_summaries(retained_cases),
                retry_round=round_index,
            )

            merged_cases = self._deduplicate_test_cases(retained_cases + candidate_cases)
            qualified_cases = self._review_and_filter_cases(merged_cases)
            retained_cases = self._select_cases_for_target(qualified_cases, effective_target_count)

            self.logger.info(
                "第 %d 轮结束：候选=%d，保留=%d，缺失覆盖=%s",
                round_index + 1,
                len(candidate_cases),
                len(retained_cases),
                self._collect_missing_coverages(retained_cases, effective_target_count),
            )

        if not retained_cases:
            raise ValueError("没有找到任何合法且达标的测试用例")

        final_cases = self._finalize_cases(retained_cases, effective_target_count)
        if not final_cases:
            raise ValueError("没有找到任何合法且达标的测试用例")
        return final_cases

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

    def _generate_candidate_cases(
        self,
        input_text: str,
        knowledge_context: Union[str, RAGContextResult],
        request_count: int,
        missing_coverages: List[str],
        existing_case_summaries: List[str],
        retry_round: int,
    ) -> List[Dict[str, Any]]:
        case_design_methods = ",".join(self.case_design_methods) if self.case_design_methods else ""
        case_categories = ",".join(self.case_categories) if self.case_categories else ""
        messages = self.prompt.format_messages(
            requirements=input_text,
            case_design_methods=case_design_methods,
            case_categories=case_categories,
            case_count=request_count,
            knowledge_context=knowledge_context,
            missing_coverage_tags=missing_coverages,
            existing_case_summaries=existing_case_summaries,
            retry_round=retry_round,
        )
        self.logger.info(f"构建后大模型提示词+用户需求消息: \n{'='*50}\n{messages}\n{'='*50}")

        result = ""
        try:
            response = self.llm_service.invoke(messages)
            result = response.content if hasattr(response, "content") else str(response)
            self.logger.info(f"LLM原始响应: \n{'='*50}\n{result}\n{'='*50}")
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
                knowledge = self.knowledge_service.search_relevant_knowledge_context(input_text)
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

    def _review_cases_batch(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not test_cases:
            return []

        batch_review = getattr(self.reviewer_agent, "review_case_batch", None)
        if callable(batch_review):
            try:
                return batch_review(test_cases)
            except Exception as exc:
                self.logger.warning("批量评审失败，回退到逐条评审: %s", exc)

        return [self.reviewer_agent.review_case_data(case) for case in test_cases]

    def _required_coverages_for_target(self, target_count: int) -> List[str]:
        required = ["主流程", "关键分支", "边界条件", "异常处理"]
        if target_count >= 6:
            required.extend(["性能", "安全"])
        if target_count >= 8:
            required.extend(["兼容性", "稳定性"])
        return required

    def _detect_coverage_tags(self, case: Dict[str, Any]) -> Set[str]:
        text = " ".join(
            [case.get("description", "")]
            + case.get("test_steps", [])
            + case.get("expected_results", [])
        ).lower()
        coverage_tags: Set[str] = set()
        for tag, keywords in self.COVERAGE_KEYWORDS.items():
            if any(keyword.lower() in text for keyword in keywords):
                coverage_tags.add(tag)
        return coverage_tags

    def _collect_missing_coverages(self, cases: List[Dict[str, Any]], target_count: int) -> List[str]:
        covered: Set[str] = set()
        for case in cases:
            covered.update(case.get("_coverage_tags") or self._detect_coverage_tags(case))
        return [tag for tag in self._required_coverages_for_target(target_count) if tag not in covered]

    def _select_cases_for_target(self, cases: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
        sorted_cases = sorted(
            cases,
            key=lambda case: (
                int(case.get("_quality_score", 0)),
                len(case.get("_coverage_tags", [])),
                self._case_richness(case),
            ),
            reverse=True,
        )
        if self.case_count <= 0:
            return sorted_cases

        selected: List[Dict[str, Any]] = []
        selected_ids: Set[str] = set()
        for coverage in self._required_coverages_for_target(target_count):
            for case in sorted_cases:
                marker = self._normalize_text(case.get("description", ""))
                if marker in selected_ids:
                    continue
                if coverage in (case.get("_coverage_tags") or []):
                    selected.append(case)
                    selected_ids.add(marker)
                    break

        for case in sorted_cases:
            if len(selected) >= target_count:
                break
            marker = self._normalize_text(case.get("description", ""))
            if marker in selected_ids:
                continue
            selected.append(case)
            selected_ids.add(marker)
        return selected[:target_count]

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
