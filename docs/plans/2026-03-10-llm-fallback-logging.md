# LLM Fallback Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Record explicit backend logs when `plane_one_click_generate` falls back from the requested model to `qwen`, and when generation later succeeds.

**Architecture:** Keep logging at the API layer so business troubleshooting can see requested provider, effective provider, work item id, and saved count in one place. Reuse existing factory-level fallback logs and add API-level `warning` and `info` records only around the fallback/success boundary.

**Tech Stack:** Django views, Python `unittest`, existing project logger

---

### Task 1: Add failing test for API-layer fallback logs

**Files:**
- Modify: `tests/test_plane_api_errors.py`
- Reference: `apps/core/api_views.py`

**Step 1: Write the failing test**

Add a test that calls `plane_one_click_generate` with `kimi`, forces a 502 on the first provider and a success on `qwen`, and asserts:
- one `warning` log is emitted for the provider switch
- one `info` log is emitted for the final success

**Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m unittest tests/test_plane_api_errors.py`
Expected: FAIL because API-layer logs are not emitted yet.

**Step 3: Write minimal implementation**

Update `apps/core/api_views.py` to create/use a module logger and emit:
- `warning` when switching from requested provider to `qwen`
- `info` after successful save with requested/effective provider and saved count

**Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m unittest tests/test_plane_api_errors.py`
Expected: PASS

### Task 2: Run targeted regression

**Files:**
- Verify: `tests/test_llm_factory.py`
- Verify: `tests/test_llm_error_mapping.py`

**Step 1: Run regression tests**

Run: `./.venv/bin/python -m unittest tests/test_plane_api_errors.py tests/test_llm_factory.py tests/test_llm_error_mapping.py`
Expected: PASS

**Step 2: Verify frontend build still passes**

Run: `cd frontend && npm run build`
Expected: Vite build succeeds
