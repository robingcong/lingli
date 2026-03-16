import unittest

from apps.agents.prompts import (
    TestCaseGeneratorPrompt,
    TestCaseReviewerPrompt,
    PrdAnalyserPrompt,
    APITestCaseGeneratorPrompt,
)


class PromptQualityTests(unittest.TestCase):
    def test_test_case_generator_has_strict_contract_and_self_check(self):
        prompt = TestCaseGeneratorPrompt()
        messages = prompt.format_messages(
            requirements="用户登录",
            case_design_methods="等价类划分法",
            case_categories="功能测试",
            knowledge_context="",
            case_count=3,
        )
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        self.assertIn("输出前自检", merged)
        self.assertIn("仅输出JSON", merged)
        self.assertIn("test_steps 与 expected_results 条数必须一致", merged)

    def test_test_case_generator_requires_broad_functional_and_nonfunctional_coverage(self):
        prompt = TestCaseGeneratorPrompt()
        messages = prompt.format_messages(
            requirements="用户登录",
            case_design_methods="等价类划分法",
            case_categories="功能测试",
            knowledge_context="",
            case_count=5,
        )
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        self.assertIn("主流程", merged)
        self.assertIn("关键分支", merged)
        self.assertIn("边界条件", merged)
        self.assertIn("异常处理", merged)
        self.assertIn("性能", merged)
        self.assertIn("兼容性", merged)
        self.assertIn("安全", merged)
        self.assertIn("稳定性", merged)
        self.assertIn("至少参考目标 5 条", merged)
        self.assertIn("覆盖不足应继续补充", merged)

    def test_test_case_generator_strengthens_system_function_content_prompts(self):
        prompt = TestCaseGeneratorPrompt()
        messages = prompt.format_messages(
            requirements="""
            无人机驾驶舱支持点击指点飞行按钮，在地图上选择位置后调度无人机前往。
            用户可在详情页查看任务状态、提示信息，并支持刷新后回显结果。
            非管理员不可执行调度操作。
            """,
            case_design_methods="场景法",
            case_categories="功能测试",
            knowledge_context="",
            case_count=6,
        )
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        self.assertIn("系统功能内容专用规则", merged)
        self.assertIn("功能子点", merged)
        self.assertIn("页面入口", merged)
        self.assertIn("刷新回显", merged)
        self.assertIn("联动校验", merged)
        self.assertIn("禁止输出空泛描述", merged)

    def test_reviewer_has_machine_readable_json_contract(self):
        prompt = TestCaseReviewerPrompt()
        messages = prompt.format_messages(
            {
                "description": "描述",
                "test_steps": ["1. 步骤"],
                "expected_results": ["1. 结果"],
            }
        )
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        self.assertIn("仅输出JSON对象", merged)
        self.assertIn("禁止输出任何解释性文本", merged)
        self.assertIn("score", merged)

    def test_prd_prompt_has_schema_and_coverage_requirements(self):
        prompt = PrdAnalyserPrompt()
        messages = prompt.format_messages("# PRD")
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        self.assertIn("覆盖率要求", merged)
        self.assertIn("输出前自检", merged)
        self.assertIn("test_points", merged)

    def test_api_prompt_retry_injects_strict_json_rules(self):
        prompt = APITestCaseGeneratorPrompt()
        messages = prompt.format_messages(
            api_info={"name": "查询用户", "method": "GET", "path": "/users", "request": {}},
            priority="P1",
            case_count=2,
            api_test_case_min_template='{"name":"","request":{},"assertions":[]}',
            include_format_instructions=True,
        )
        merged = "\n".join(getattr(m, "content", str(m)) for m in messages)
        self.assertIn("严格返回长度为2的JSON数组", merged)
        self.assertIn("若失败请直接重写为合法JSON", merged)


if __name__ == "__main__":
    unittest.main()
