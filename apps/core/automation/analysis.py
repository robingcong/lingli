from typing import Any, Dict


def build_failure_analysis(result: Dict[str, Any]) -> Dict[str, Any]:
    """Create a concise attribution and fix suggestion from deterministic evidence."""
    if result.get("passed"):
        return {
            "category": "none",
            "reason": "执行通过，无需失败归因。",
            "修复建议": [],
        }

    error = str(result.get("error_message") or "").lower()
    evidence = result.get("evidence") or {}
    assertion_failures = evidence.get("assertion_failures") or []

    if assertion_failures:
        category = "assertion_issue"
        reason = "响应已返回，但至少一条断言未满足。"
        suggestions = [
            "核对断言是否仍符合当前业务规则和接口契约。",
            "保存失败响应作为证据，必要时补充更精确的状态码或字段断言。",
        ]
    elif any(marker in error for marker in ("timeout", "connection", "refused", "dns", "name resolution")):
        category = "environment"
        reason = "执行器无法稳定访问被测环境。"
        suggestions = [
            "检查 base_url、网络连通性、服务启动状态和本地 runner 环境。",
            "确认测试数据依赖的账号、租户或环境变量已经配置。",
        ]
    elif any(marker in error for marker in ("selector", "locator", "strict mode", "not found")):
        category = "selector_drift"
        reason = "UI 元素定位失败，可能是页面结构或选择器发生变化。"
        suggestions = [
            "人工更新 Playwright 脚本中的 locator，不要直接覆盖已确认脚本。",
            "优先使用 role、label、test id 等稳定选择器。",
        ]
    elif any(marker in error for marker in ("401", "403", "unauthorized", "forbidden", "登录", "login")):
        category = "test_data"
        reason = "执行失败与身份、账号或测试数据状态相关。"
        suggestions = [
            "检查账号、权限、前置数据和登录态是否满足用例前置条件。",
            "将必要的测试数据准备动作显式写入 AutomationSpec。",
        ]
    else:
        category = "product_defect"
        reason = "执行过程触发了未预期失败，需要结合证据判断是否为产品缺陷。"
        suggestions = [
            "保留错误信息、响应片段、截图或 trace 后提交给负责人确认。",
            "若证据显示断言过窄，先修改脚本草稿并重新人工确认。",
        ]

    return {
        "category": category,
        "reason": reason,
        "修复建议": suggestions,
    }
