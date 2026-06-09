<template>
  <div>
    <div class="card">
      <div class="page-head">
        <div>
          <h2>UI 自动化管理</h2>
          <div class="muted">Playwright 用例草稿、人工确认、执行结果</div>
        </div>
        <button class="secondary" @click="load" :disabled="loading">刷新</button>
      </div>

      <div class="summary-grid">
        <div class="summary-item">
          <span>用例</span>
          <strong>{{ summary.total }}</strong>
        </div>
        <div class="summary-item">
          <span>已执行</span>
          <strong>{{ summary.with_runs }}</strong>
        </div>
        <div class="summary-item pass">
          <span>通过</span>
          <strong>{{ summary.passed }}</strong>
        </div>
        <div class="summary-item fail">
          <span>失败</span>
          <strong>{{ summary.failed }}</strong>
        </div>
        <div class="summary-item">
          <span>未执行</span>
          <strong>{{ summary.unrun }}</strong>
        </div>
      </div>

      <div class="form-grid filter-grid">
        <div>
          <label>评审状态</label>
          <select v-model="status">
            <option value="approved">已通过</option>
            <option value="pending">待评审</option>
            <option value="rejected">未通过</option>
            <option value="all">全部</option>
          </select>
        </div>
        <div>
          <label>自动化状态</label>
          <select v-model="automationStatus">
            <option value="all">全部</option>
            <option value="unrun">未执行</option>
            <option value="passed">执行通过</option>
            <option value="failed">执行失败</option>
          </select>
        </div>
        <div>
          <label>每页数量</label>
          <select v-model.number="pageSize">
            <option :value="10">10</option>
            <option :value="15">15</option>
            <option :value="20">20</option>
            <option :value="30">30</option>
          </select>
        </div>
        <div>
          <label>关键词</label>
          <div class="search-line">
            <input v-model="keyword" placeholder="标题/描述/需求/步骤" @keyup.enter="resetAndLoad" />
            <button class="secondary" @click="resetAndLoad">查询</button>
          </div>
        </div>
      </div>

      <div v-if="loading" class="notice">加载中...</div>
      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-if="fallbackNotice" class="notice">{{ fallbackNotice }}</div>

      <table class="table management-table" v-if="items.length">
        <thead>
          <tr>
            <th>用例</th>
            <th>评审状态</th>
            <th>自动化</th>
            <th>最近执行</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id" :class="{ selected: selectedCase?.id === item.id }">
            <td>
              <div class="case-title">#{{ item.id }} {{ item.title || '未命名用例' }}</div>
              <div class="case-desc">{{ shortText(item.description || item.requirements) }}</div>
              <div class="case-meta">
                <span>{{ item.llm_provider || '未知模型' }}</span>
                <span>{{ formatTime(item.updated_at || item.created_at) }}</span>
              </div>
            </td>
            <td>
              <span class="badge" :class="statusClass(item.status)">{{ statusText(item.status) }}</span>
            </td>
            <td>
              <span class="badge" :class="automationClass(item.latest_automation_run)">
                {{ automationText(item.latest_automation_run) }}
              </span>
            </td>
            <td>
              <div v-if="item.latest_automation_run" class="run-cell">
                <span>{{ item.latest_automation_run.runner_type }}</span>
                <span>{{ item.latest_automation_run.duration_ms }} ms</span>
                <span>{{ formatTime(item.latest_automation_run.created_at) }}</span>
              </div>
              <span v-else class="muted">暂无</span>
            </td>
            <td>
              <div class="action-line">
                <button class="secondary" @click="selectCase(item)">管理</button>
                <RouterLink :to="`/review/${item.id}`">详情</RouterLink>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!loading" class="notice">暂无用例。</div>

      <div class="pagination">
        <button class="secondary" @click="prevPage" :disabled="page <= 1 || loading">上一页</button>
        <div>第 {{ page }} / {{ totalPages }} 页</div>
        <button class="secondary" @click="nextPage" :disabled="page >= totalPages || loading">下一页</button>
      </div>
    </div>

    <div class="card" v-if="selectedCase">
      <div class="page-head">
        <div>
          <h2>#{{ selectedCase.id }} {{ selectedCase.title || '未命名用例' }}</h2>
          <div class="muted">{{ shortText(selectedCase.description || selectedCase.requirements, 160) }}</div>
        </div>
        <span class="badge" :class="automationClass(selectedCase.latest_automation_run)">
          {{ automationText(selectedCase.latest_automation_run) }}
        </span>
      </div>

      <div class="form-grid">
        <div>
          <label>Base URL</label>
          <input v-model="automationBaseUrl" />
        </div>
        <div>
          <label>登录信息</label>
          <label class="check-line">
            <input type="checkbox" v-model="automationLoginEnabled" />
            <span>执行前登录</span>
          </label>
        </div>
        <div>
          <label>人工确认</label>
          <label class="check-line">
            <input type="checkbox" v-model="automationConfirmed" />
            <span>脚本已确认</span>
          </label>
        </div>
      </div>

      <div v-if="automationLoginEnabled" class="form-grid login-grid">
        <div>
          <label>登录地址</label>
          <input v-model="automationLoginUrl" placeholder="/login" />
        </div>
        <div>
          <label>账号</label>
          <input v-model="automationLoginUsername" autocomplete="username" />
        </div>
        <div>
          <label>密码</label>
          <input v-model="automationLoginPassword" type="password" autocomplete="current-password" />
        </div>
      </div>

      <div class="flex" style="margin-top: 12px;">
        <button class="secondary" @click="generateAutomationDraft" :disabled="automationRunning">
          生成 Playwright 草稿
        </button>
        <button @click="runAutomation" :disabled="automationRunning || !automationScript || !automationConfirmed">
          执行
        </button>
        <span v-if="automationMessage" class="notice">{{ automationMessage }}</span>
      </div>

      <div class="script-grid">
        <div>
          <label>Playwright 脚本</label>
          <textarea class="script-area" v-model="automationScript"></textarea>
        </div>
        <div>
          <label>最近证据</label>
          <div v-if="selectedCase.latest_automation_run" class="result-panel">
            <div class="result-head">
              <span class="badge" :class="automationClass(selectedCase.latest_automation_run)">
                {{ automationText(selectedCase.latest_automation_run) }}
              </span>
              <span class="muted">{{ selectedCase.latest_automation_run.duration_ms }} ms</span>
            </div>
            <div v-if="selectedCase.latest_automation_run.error_message" class="notice error">
              {{ selectedCase.latest_automation_run.error_message }}
            </div>
            <div
              v-if="selectedCase.latest_automation_run.analysis?.category && selectedCase.latest_automation_run.analysis.category !== 'none'"
              class="notice"
            >
              {{ selectedCase.latest_automation_run.analysis.category }}：{{ selectedCase.latest_automation_run.analysis.reason }}
            </div>
            <pre class="text-block">{{ formatJson(selectedCase.latest_automation_run.evidence || {}) }}</pre>
          </div>
          <div v-else class="notice">暂无执行证据。</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import { api } from '../api/endpoints';

const status = ref('approved');
const automationStatus = ref('all');
const keyword = ref('');
const page = ref(1);
const pageSize = ref(15);
const totalPages = ref(1);
const items = ref([]);
const loading = ref(false);
const error = ref('');
const fallbackNotice = ref('');
const selectedCase = ref(null);
const summary = ref({
  total: 0,
  with_runs: 0,
  passed: 0,
  failed: 0,
  unrun: 0
});

const automationBaseUrl = ref('http://127.0.0.1:5173');
const automationLoginEnabled = ref(false);
const automationLoginUrl = ref('/login');
const automationLoginUsername = ref('');
const automationLoginPassword = ref('');
const automationConfirmed = ref(false);
const automationScript = ref('');
const automationRunning = ref(false);
const automationMessage = ref('');

function statusText(value) {
  if (value === 'pending') return '待评审';
  if (value === 'approved') return '已通过';
  if (value === 'rejected') return '未通过';
  return value || '-';
}

function statusClass(value) {
  if (value === 'pending') return 'status-pending';
  if (value === 'approved') return 'status-approved';
  if (value === 'rejected') return 'status-rejected';
  return '';
}

function automationText(run) {
  if (!run) return '未执行';
  return run.passed ? '执行通过' : '执行失败';
}

function automationClass(run) {
  if (!run) return 'status-pending';
  return run.passed ? 'status-approved' : 'status-rejected';
}

function isMissingManagementEndpoint(errorValue) {
  const message = String(errorValue?.message || errorValue || '');
  return (
    message.includes('/api/automation/ui-test-cases/')
    || message.includes('api/automation/ui-test-cases/')
  ) && (
    message.includes('Page not found')
    || message.includes('didn') && message.includes('match')
    || message.includes('404')
  );
}

function matchesAutomationStatus(item) {
  const run = item.latest_automation_run;
  if (automationStatus.value === 'passed') return Boolean(run?.passed);
  if (automationStatus.value === 'failed') return Boolean(run && !run.passed);
  if (automationStatus.value === 'unrun') return !run;
  return true;
}

function matchesKeyword(item) {
  const kw = keyword.value.trim().toLowerCase();
  if (!kw) return true;
  return [
    item.title,
    item.description,
    item.requirements,
    item.test_steps,
    item.expected_results
  ].some((value) => String(value || '').toLowerCase().includes(kw));
}

function buildSummary(rows, totalOverride = null) {
  const nextSummary = {
    total: totalOverride ?? rows.length,
    with_runs: 0,
    passed: 0,
    failed: 0,
    unrun: 0
  };
  for (const item of rows) {
    const run = item.latest_automation_run;
    if (!run) {
      nextSummary.unrun += 1;
    } else if (run.passed) {
      nextSummary.with_runs += 1;
      nextSummary.passed += 1;
    } else {
      nextSummary.with_runs += 1;
      nextSummary.failed += 1;
    }
  }
  return nextSummary;
}

function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function shortText(value, maxLength = 96) {
  const text = (value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= maxLength) return text || '-';
  return `${text.slice(0, maxLength)}...`;
}

function formatJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (e) {
    return String(value);
  }
}

function applyLatestRunToSelected(run) {
  if (!selectedCase.value) return;
  selectedCase.value = {
    ...selectedCase.value,
    latest_automation_run: run || null
  };
  items.value = items.value.map((item) => (
    item.id === selectedCase.value.id
      ? { ...item, latest_automation_run: run || null }
      : item
  ));
}

async function loadFromLegacyTestCaseList() {
  const data = await api.listTestCases(status.value, page.value, pageSize.value);
  const legacyRows = (data.items || []).map((item) => ({
    ...item,
    latest_automation_run: item.latest_automation_run || null
  }));
  const filteredRows = legacyRows
    .filter(matchesKeyword)
    .filter(matchesAutomationStatus);
  return {
    items: filteredRows,
    summary: buildSummary(legacyRows, data.total || legacyRows.length),
    total_pages: data.total_pages || 1
  };
}

async function load() {
  loading.value = true;
  error.value = '';
  fallbackNotice.value = '';
  const selectedId = selectedCase.value?.id;
  try {
    let data;
    try {
      data = await api.listUiAutomationTestCases({
        page: page.value,
        pageSize: pageSize.value,
        status: status.value,
        automationStatus: automationStatus.value,
        keyword: keyword.value
      });
    } catch (primaryError) {
      if (!isMissingManagementEndpoint(primaryError)) {
        throw primaryError;
      }
      data = await loadFromLegacyTestCaseList();
      fallbackNotice.value = '后端服务尚未加载新的管理列表接口，已用旧接口兼容展示；重启 Django 后端后可恢复完整统计和后端筛选。';
    }
    items.value = data.items || [];
    summary.value = data.summary || summary.value;
    totalPages.value = data.total_pages || 1;
    if (selectedId) {
      const nextSelected = items.value.find((item) => item.id === selectedId);
      if (nextSelected) {
        selectedCase.value = nextSelected;
      }
    }
  } catch (e) {
    error.value = e.message || '加载失败。';
  } finally {
    loading.value = false;
  }
}

function resetAndLoad() {
  page.value = 1;
  load();
}

function prevPage() {
  if (page.value <= 1) return;
  page.value -= 1;
  load();
}

function nextPage() {
  if (page.value >= totalPages.value) return;
  page.value += 1;
  load();
}

function hydrateLoginFromRun(run) {
  const latestLogin = run?.spec?.test_data?.login;
  automationLoginEnabled.value = Boolean(latestLogin?.enabled);
  automationLoginUrl.value = latestLogin?.login_url || '/login';
  automationLoginUsername.value = latestLogin?.username || '';
  automationLoginPassword.value = '';
}

function selectCase(item) {
  selectedCase.value = item;
  automationScript.value = item.latest_automation_run?.script_text || '';
  automationConfirmed.value = false;
  automationMessage.value = '';
  hydrateLoginFromRun(item.latest_automation_run);
}

function buildAutomationPayload(extra = {}) {
  const payload = {
    base_url: automationBaseUrl.value,
    ...extra
  };
  payload.login_info = automationLoginEnabled.value
    ? {
        enabled: true,
        login_url: automationLoginUrl.value,
        username: automationLoginUsername.value,
        password: automationLoginPassword.value
      }
    : { enabled: false };
  return payload;
}

async function generateAutomationDraft() {
  if (!selectedCase.value) return;
  automationRunning.value = true;
  automationMessage.value = '';
  try {
    const data = await api.generateAutomationScript(selectedCase.value.id, buildAutomationPayload());
    automationScript.value = data.script_text || '';
    applyLatestRunToSelected(data.latest_run || selectedCase.value.latest_automation_run || null);
    automationConfirmed.value = false;
    automationMessage.value = data.success ? '草稿已生成。' : (data.message || '生成失败。');
  } catch (e) {
    automationMessage.value = e.message || '生成失败。';
  } finally {
    automationRunning.value = false;
  }
}

async function runAutomation() {
  if (!selectedCase.value || !automationScript.value || !automationConfirmed.value) return;
  automationRunning.value = true;
  automationMessage.value = '';
  try {
    const data = await api.runTestCaseAutomation(selectedCase.value.id, buildAutomationPayload({
      script_text: automationScript.value,
      confirmed: true
    }));
    applyLatestRunToSelected(data.run || null);
    automationMessage.value = data.run?.passed ? '执行通过。' : '执行完成，存在失败。';
    await load();
  } catch (e) {
    automationMessage.value = e.message || '执行失败。';
  } finally {
    automationRunning.value = false;
  }
}

watch([status, automationStatus, pageSize], resetAndLoad);

onMounted(load);
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.muted {
  color: var(--muted);
  font-size: 12px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.summary-item {
  display: grid;
  gap: 6px;
  min-height: 72px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--panel-soft);
}

.summary-item span {
  color: var(--muted);
  font-size: 12px;
}

.summary-item strong {
  font-size: 24px;
  line-height: 1;
}

.summary-item.pass strong {
  color: var(--success);
}

.summary-item.fail strong {
  color: var(--danger);
}

.filter-grid {
  align-items: end;
  margin-bottom: 14px;
}

.search-line {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.management-table tr.selected td {
  background: var(--panel-soft);
}

.case-title {
  font-weight: 700;
  word-break: break-word;
}

.case-desc {
  margin-top: 5px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.case-meta,
.run-cell,
.action-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.case-meta,
.run-cell {
  margin-top: 6px;
  color: var(--muted);
  font-size: 12px;
}

.check-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
}

.check-line input {
  width: auto;
}

.login-grid {
  margin-top: 12px;
}

.script-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
  gap: 12px;
  margin-top: 12px;
}

.script-area {
  min-height: 360px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.result-panel {
  display: grid;
  gap: 10px;
}

.result-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.text-block {
  max-height: 360px;
  overflow: auto;
  background: var(--panel-soft);
  border-radius: 8px;
  padding: 10px;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 1100px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .script-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .summary-grid,
  .search-line {
    grid-template-columns: 1fr;
  }

  .page-head {
    display: grid;
  }
}
</style>
