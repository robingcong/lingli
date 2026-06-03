# Prompt Quality Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 提升测试用例生成/评审/PRD分析/API用例生成提示词质量与输出稳定性，减少跑偏和格式错误。

**Architecture:** 采用“结构化提示词协议”统一四类提示词，按角色、任务、输入边界、硬约束、输出Schema、自检清单六段组织。基于现有重试机制保留二次格式纠偏，并在模板中加入显式失败处理与字段一致性规则。

**Tech Stack:** Django, LangChain PromptTemplate, YAML 配置模板。

---

### Task 1: 为提示词配置增加统一结构化约束

**Files:**
- Modify: `apps/agents/prompts_config.yaml`

**Step 1: 写失败验证标准（手工）**
- 定义“失败”标准：输出非 JSON、字段缺失、步骤与预期数量不一致、出现解释性废话。

**Step 2: 最小改动实现结构化模板**
- 按模块重写 system/human template：
  - 角色与目标
  - 输入边界
  - 严格输出契约
  - 生成规则
  - 输出前自检清单

**Step 3: 保留并强化重试友好性**
- 模板增加“若格式不合法，立即修正并仅输出合法 JSON”的指令。

**Step 4: 人工检查**
- 检查 YAML 语法、占位符名称一致性。

### Task 2: 在 Prompt 组装层补充一致性保障

**Files:**
- Modify: `apps/agents/prompts.py`

**Step 1: 写 failing tests（见 Task 3）**
- 先写模板关键约束存在性测试。

**Step 2: 最小实现**
- 在 `APITestCaseGeneratorPrompt.format_messages` 的重试附加说明中加入更强协议（仅 JSON、数组长度、字段完整）。
- 保证规则覆盖逻辑不会破坏关键章节标题。

**Step 3: 通过测试**
- 运行测试并确认通过。

### Task 3: 增加提示词回归测试

**Files:**
- Create: `tests/test_prompt_quality.py`

**Step 1: 写 failing tests**
- 测试四类提示词包含关键结构标签：`输出格式`、`自检`、`仅输出JSON` 等。
- 测试 API 生成提示词在 `include_format_instructions=True` 时注入严格格式要求。

**Step 2: 运行验证失败**
- Run: `./.venv/bin/python -m unittest tests/test_prompt_quality.py -v`
- 预期：至少一项失败（改动前）。

**Step 3: 实现并复测**
- 修改模板与组装逻辑后重复运行，预期全通过。

### Task 4: 端到端快速验证

**Files:**
- Modify: none

**Step 1: 生成侧验证**
- 使用现有入口触发一次用例生成，确认响应可被 JSON 解析。

**Step 2: 评审侧验证**
- 触发一次评审，确认输出结构完整。

**Step 3: 记录风险**
- 标注潜在风险：模型仍可能受上下文污染，需继续观察重试率。
