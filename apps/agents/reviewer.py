from typing import Dict, Any, List
import json

from ..llm.base import BaseLLMService
from ..knowledge.service import KnowledgeService
from ..core.models import TestCase
from .prompts import TestCaseReviewerPrompt
from utils.logger_manager import get_logger


class TestCaseReviewerAgent:
    """测试用例评审Agent"""

    def __init__(self, llm_service: BaseLLMService, knowledge_service: KnowledgeService):
        self.llm_service = llm_service
        self.knowledge_service = knowledge_service
        self.prompt = TestCaseReviewerPrompt()
        self.logger = get_logger(self.__class__.__name__)

    def review(self, test_case: TestCase) -> str:
        """评审测试用例并返回原始JSON字符串。"""
        payload = self.review_case_data(
            {
                "description": test_case.description,
                "test_steps": test_case.test_steps,
                "expected_results": test_case.expected_results,
            }
        )
        return payload["raw_text"]

    def review_case_data(self, test_case_data: Dict[str, Any]) -> Dict[str, Any]:
        """评审测试用例数据并返回结构化结果。"""
        try:
            self.logger.info("待评审的测试用例数据: \n%s", test_case_data)
            messages = self.prompt.format_messages(test_case_data)
            self.logger.info("构建后的评审提示词: \n%s", messages)

            result = self.llm_service.invoke(messages)
            raw_text = result.content if hasattr(result, "content") else str(result)
            cleaned = self._extract_json(raw_text)
            if cleaned != raw_text:
                self.logger.info("评审结果已截取为JSON片段")

            parsed = self._parse_review_json(cleaned)
            return {
                "raw_text": cleaned,
                "parsed": parsed,
                "score": parsed.get("score"),
                "recommendation": parsed.get("recommendation", ""),
            }
        except Exception as e:
            self.logger.error("评审过程出错: %s", str(e), exc_info=True)
            raise Exception(f"评审失败: {str(e)}")

    def review_case_batch(self, test_cases_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量评审测试用例并返回与输入等长的结构化结果列表。"""
        if not test_cases_data:
            return []

        try:
            self.logger.info("待批量评审的测试用例数量: %s", len(test_cases_data))
            messages = self.prompt.format_batch_messages(test_cases_data)
            self.logger.info("构建后的批量评审提示词: \n%s", messages)

            result = self.llm_service.invoke(messages)
            raw_text = result.content if hasattr(result, "content") else str(result)
            cleaned = self._extract_json(raw_text)
            if cleaned != raw_text:
                self.logger.info("批量评审结果已截取为JSON片段")

            parsed_items = self._parse_review_json_array(cleaned)
            if len(parsed_items) != len(test_cases_data):
                raise ValueError(
                    f"批量评审结果数量不匹配: expected={len(test_cases_data)}, actual={len(parsed_items)}"
                )

            payloads: List[Dict[str, Any]] = []
            for item in parsed_items:
                payloads.append(
                    {
                        "raw_text": json.dumps(item, ensure_ascii=False),
                        "parsed": item,
                        "score": item.get("score"),
                        "recommendation": item.get("recommendation", ""),
                    }
                )
            return payloads
        except Exception as e:
            self.logger.error("批量评审过程出错: %s", str(e), exc_info=True)
            raise Exception(f"批量评审失败: {str(e)}")

    def _parse_review_json(self, text: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {
            "score": 0,
            "recommendation": "不通过",
            "comments": text,
            "missing_scenarios": [],
        }

    def _extract_json(self, text: str) -> str:
        """从模型输出中截取JSON对象或数组字符串"""
        if not isinstance(text, str):
            return str(text)

        content = text.strip()
        if content.startswith("```"):
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1].replace("json", "").strip()

        if content.startswith("["):
            end_arr = content.rfind("]")
            if end_arr != -1:
                return content[: end_arr + 1].strip()

        if content.startswith("{"):
            end_obj = content.rfind("}")
            if end_obj != -1:
                return content[: end_obj + 1].strip()

        start_arr = content.find("[")
        end_arr = content.rfind("]")
        start_obj = content.find("{")
        end_obj = content.rfind("}")
        if start_arr != -1 and end_arr != -1 and (start_obj == -1 or start_arr < start_obj):
            return content[start_arr:end_arr + 1].strip()
        if start_obj != -1 and end_obj != -1:
            return content[start_obj:end_obj + 1].strip()

        return content

    def _parse_review_json_array(self, text: str) -> List[Dict[str, Any]]:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                normalized = []
                for item in parsed:
                    if isinstance(item, dict):
                        normalized.append(item)
                    else:
                        normalized.append(self._parse_review_json(str(item)))
                return normalized
        except Exception:
            pass
        return []
