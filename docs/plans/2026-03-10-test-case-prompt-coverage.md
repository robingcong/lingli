# Test Case Prompt Coverage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 强化普通需求测试用例生成提示词，使其生成更多 case，并显式覆盖功能与非功能测试场景。

**Architecture:** 仅调整普通需求生成提示词配置与组装逻辑，不改变请求协议或生成后处理。通过回归测试锁定覆盖维度、数量导向与 JSON 合约，确保后续修改不会削弱提示词效果。

**Tech Stack:** Python 3.12, Django, LangChain PromptTemplate, unittest, YAML prompt config

---

### Task 1: 为普通需求生成提示词补充覆盖与数量约束

**Files:**
- Modify: `apps/agents/prompts_config.yaml`
- Modify: `apps/agents/prompts.py`
- Test: `tests/test_prompt_quality.py`

**Step 1: Write the failing test**

在 `tests/test_prompt_quality.py` 中新增/扩展普通需求提示词断言，要求 prompt 文本包含：
- 主流程
- 关键分支
- 边界条件
- 异常处理
- 性能
- 兼容性
- 安全
- 稳定性
- 至少参考目标
- 覆盖不足应继续补充

**Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m unittest tests.test_prompt_quality -v`
Expected: FAIL because the current normal test case prompt does not contain the stronger coverage and quantity language.

**Step 3: Write minimal implementation**

- 在 `apps/agents/prompts_config.yaml` 的 `test_case_generator.system_template` 中加入覆盖维度硬约束。
- 在 `apps/agents/prompts_config.yaml` 的 `test_case_generator.human_template` 中加入“拆分不同维度为独立 case”“覆盖不足继续补充”的表述。
- 在 `apps/agents/prompts.py` 中调整 `quantity_instruction`：
  - `case_count <= 0`: 数量不设上限，尽可能多生成。
  - `case_count > 0`: 至少参考目标 N 条，若覆盖维度不足则继续补充。

**Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m unittest tests.test_prompt_quality -v`
Expected: PASS

### Task 2: 运行相关回归测试

**Files:**
- Test: `tests/test_prompt_quality.py`
- Test: `tests/test_llm_factory.py`
- Test: `tests/test_llm_error_mapping.py`
- Test: `tests/test_plane_api_errors.py`

**Step 1: Run focused regression suite**

Run: `./.venv/bin/python -m unittest tests.test_prompt_quality tests.test_llm_factory tests.test_llm_error_mapping tests.test_plane_api_errors -v`

**Step 2: Verify results**

Expected:
- All tests pass
- No prompt-quality regressions
- Existing LLM fallback and Plane error mapping tests remain green
