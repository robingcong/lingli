# Generation Quality Gate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为普通需求测试用例生成链路增加统一质量门禁，降低温度、去重重复测试点、检查覆盖缺口，并使用 AI 评审打分后自动补齐不足 case。

**Architecture:** 在普通需求生成链路中引入“候选生成 -> 规则去重 -> 覆盖检查 -> AI 评审过滤 -> 自动补齐”的多轮闭环。温度控制通过普通生成入口单独覆盖，避免影响其它生成链路；质量门禁逻辑集中在 `TestCaseGeneratorAgent`，以便后续复用。

**Tech Stack:** Python 3.12, Django, LangChain, unittest

---

### Task 1: 固定温度与质量配置

**Files:**
- Modify: `config/settings.py`
- Modify: `apps/core/views.py`
- Test: `tests/test_generation_quality_gate.py`

**Step 1: Write the failing test**

新增测试，验证普通生成入口会用较低温度创建生成模型和评审模型。

**Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m unittest tests.test_generation_quality_gate -v`
Expected: FAIL because `generate` view does not override temperature or create a dedicated reviewer service.

**Step 3: Write minimal implementation**

- 在 `config/settings.py` 增加普通生成质量配置。
- 在 `apps/core/views.py` 的 `generate` 入口中为生成模型与评审模型传入较低温度。

**Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m unittest tests.test_generation_quality_gate -v`
Expected: PASS

### Task 2: 为普通生成增加去重、覆盖检查和 AI 评审质量门禁

**Files:**
- Modify: `apps/agents/generator.py`
- Modify: `apps/agents/reviewer.py`
- Modify: `apps/agents/prompts.py`
- Test: `tests/test_generation_quality_gate.py`

**Step 1: Write the failing tests**

新增测试覆盖：
- 相似 description 和关键词重复的 case 会被归并。
- 低于最低质量分的 case 会被过滤。
- 数量不足或覆盖缺失时会自动补齐生成。

**Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_generation_quality_gate -v`
Expected: FAIL because generator currently only validates JSON structure.

**Step 3: Write minimal implementation**

- 在 `TestCaseReviewerAgent` 中增加结构化评审方法，返回解析后的评分结果。
- 在 `TestCaseGeneratorAgent` 中增加：
  - 目标数量计算
  - description/关键词去重
  - 覆盖标签识别与缺口检查
  - 质量评分过滤
  - 基于缺口的自动补齐轮次
- 在 prompt 组装层支持“补齐模式”附加说明。

**Step 4: Run tests to verify they pass**

Run: `./.venv/bin/python -m unittest tests.test_generation_quality_gate -v`
Expected: PASS

### Task 3: 运行相关回归测试

**Files:**
- Test: `tests/test_generation_quality_gate.py`
- Test: `tests/test_prompt_quality.py`
- Test: `tests/test_llm_factory.py`
- Test: `tests/test_llm_error_mapping.py`
- Test: `tests/test_plane_api_errors.py`

**Step 1: Run focused regression suite**

Run: `./.venv/bin/python -m unittest tests.test_generation_quality_gate tests.test_prompt_quality tests.test_llm_factory tests.test_llm_error_mapping tests.test_plane_api_errors -v`

**Step 2: Verify results**

Expected:
- All tests pass
- 普通生成质量门禁生效
- 既有 prompt / fallback / Plane 相关行为不回归
