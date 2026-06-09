<template>
  <div>
    <div class="card">
      <h2>接口用例生成</h2>
      <div class="form-grid">
        <div>
          <label>模型选择</label>
          <select v-model="form.llm_provider">
            <option v-for="p in providers" :key="p.key" :value="p.key">
              {{ p.name }}
            </option>
          </select>
        </div>
        <div>
          <label>优先级</label>
          <select v-model="form.priority">
            <option value="P0">P0</option>
            <option value="P1">P1</option>
            <option value="P2">P2</option>
            <option value="P3">P3</option>
          </select>
        </div>
        <div>
          <label>每接口用例数</label>
          <input type="number" v-model.number="form.count_per_api" min="1" max="10" />
        </div>
      </div>

      <div style="margin-top: 12px;">
        <label>规则覆盖（可选）</label>
        <textarea v-model="form.rules_override" placeholder="可填写 Markdown 规则"></textarea>
        <div class="flex" style="margin-top: 8px;">
          <button class="secondary" @click="loadRuleTemplate">加载默认规则</button>
        </div>
      </div>

      <div style="margin-top: 12px;">
        <label>接口定义 JSON</label>
        <input type="file" @change="onFile" accept=".json" />
      </div>
      <div class="flex" style="margin-top: 12px;">
        <button @click="upload" :disabled="!file || uploading">生成用例</button>
        <span v-if="message" class="notice">{{ message }}</span>
      </div>
      <div v-if="error" class="notice error">{{ error }}</div>
    </div>

    <div class="card" v-if="apiList.length">
      <h2>接口列表</h2>
      <div class="flex" style="margin-bottom: 8px;">
        <button class="secondary" @click="selectAll">全选</button>
        <button class="secondary" @click="clearAll">清空</button>
      </div>
      <table class="table">
        <thead>
          <tr>
            <th></th>
            <th>方法</th>
            <th>路径</th>
            <th>名称</th>
            <th>已有用例</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="apiItem in apiList" :key="apiItem.path">
            <td>
              <input type="checkbox" :value="apiItem.path" v-model="selectedPaths" />
            </td>
            <td>{{ apiItem.method }}</td>
            <td>{{ apiItem.path }}</td>
            <td>{{ apiItem.name }}</td>
            <td>{{ apiItem.test_case_count }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card" v-if="taskId">
      <h2>进度</h2>
      <div class="notice">任务：{{ taskId }}</div>
      <div class="notice">步骤：{{ progress.step || '-' }} | {{ progress.message || '' }}</div>
      <div class="notice">{{ progress.percentage || 0 }}%</div>
      <div>
        <progress :value="progress.percentage || 0" max="100" style="width: 100%;"></progress>
      </div>
    </div>

    <div class="card" v-if="logs.length">
      <h2>日志</h2>
      <pre style="max-height: 300px; overflow: auto;">{{ logs.join('\n') }}</pre>
    </div>

    <div class="card">
      <h2>生成历史</h2>
      <div v-if="loadingHistory" class="notice">加载中...</div>
      <div v-else-if="history.length === 0" class="muted">暂无记录</div>
      <div v-else class="history-list">
        <div class="history-item" v-for="item in history" :key="item.id">
          <div class="history-main">
            <div class="history-title">{{ item.file_name }}</div>
            <div class="muted">{{ formatTime(item.created_at) }}</div>
            <div class="muted">接口数 {{ item.selected_api_count }} | 用例数 {{ item.generated_cases }}</div>
          </div>
          <button @click="openHistoryDetail(item.id)">
            {{ detail && detail.id === item.id ? '收起' : '详情' }}
          </button>
        </div>
      </div>
      <div v-if="historyError" class="notice error">{{ historyError }}</div>
    </div>

    <div class="card" v-if="detail">
      <h2>生成详情</h2>
      <div class="detail-meta">
        <div class="detail-title">{{ detail.file_name }}</div>
        <div class="muted">{{ formatTime(detail.created_at) }}</div>
      </div>
      <div class="muted">接口数 {{ detail.selected_api_count }} | 用例数 {{ detail.generated_cases }}</div>

      <div class="automation-panel">
        <div class="form-grid">
          <div>
            <label>Base URL</label>
            <input v-model="automationBaseUrl" placeholder="http://127.0.0.1:8000" />
          </div>
          <div>
            <label>执行</label>
            <button @click="runApiAutomation" :disabled="automationRunning || !detailApis.length">执行首条 API 用例</button>
          </div>
        </div>
        <div v-if="automationMessage" class="notice">{{ automationMessage }}</div>
        <div v-if="latestAutomationRun" class="automation-result">
          <div class="result-head">
            <span class="badge" :class="latestAutomationRun.passed ? 'status-approved' : 'status-rejected'">
              {{ latestAutomationRun.passed ? '执行通过' : '执行失败' }}
            </span>
            <span class="muted">{{ latestAutomationRun.runner_type }} | {{ latestAutomationRun.duration_ms }} ms</span>
          </div>
          <div v-if="latestAutomationRun.analysis?.category && latestAutomationRun.analysis.category !== 'none'" class="notice">
            {{ latestAutomationRun.analysis.category }}：{{ latestAutomationRun.analysis.reason }}
          </div>
          <pre class="text-block">{{ JSON.stringify(latestAutomationRun.evidence || {}, null, 2) }}</pre>
        </div>
      </div>

      <div class="points" v-if="detailApis.length">
        <details v-for="apiItem in detailApis" :key="apiItem.path" class="tp-item">
          <summary>
            <span class="tp-title">{{ apiItem.name || '-' }}</span>
            <span class="badge">{{ apiItem.method }}</span>
            <span class="badge">{{ apiItem.path }}</span>
            <span class="muted">用例 {{ (apiItem.apiTestCaseList || []).length }}</span>
          </summary>
          <div class="tp-body">
            <div class="scenarios">
              <div v-for="(tc, idx) in (apiItem.apiTestCaseList || [])" :key="idx" class="scenario">
                <div class="scenario-header">
                  <span class="scenario-title">{{ tc.name || '未命名用例' }}</span>
                  <span class="tag">{{ tc.priority || '-' }}</span>
                </div>
                <pre class="text-block">{{ formatJson(tc) }}</pre>
              </div>
            </div>
          </div>
        </details>
      </div>
      <div v-else class="muted">暂无用例数据</div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, computed } from 'vue';
import { api } from '../api/endpoints';
import { API_BASE } from '../api/client';

const providers = ref([]);
const file = ref(null);
const apiList = ref([]);
const selectedPaths = ref([]);
const message = ref('');
const error = ref('');
const uploading = ref(false);
const generating = ref(false);
const taskId = ref('');
const logs = ref([]);
const progress = reactive({});
const history = ref([]);
const loadingHistory = ref(false);
const historyError = ref('');
const detail = ref(null);
const historyLoadedForTask = ref(false);
const automationBaseUrl = ref('http://127.0.0.1:8000');
const automationRunning = ref(false);
const automationMessage = ref('');
const latestAutomationRun = ref(null);

let logSource = null;
let pollTimer = null;

const form = reactive({
  llm_provider: 'deepseek',
  priority: 'P0',
  count_per_api: 1,
  rules_override: '',
  file_id: ''
});

onMounted(async () => {
  try {
    const data = await api.getProviders();
    providers.value = data.providers || [];
    if (data.default_provider) {
      form.llm_provider = data.default_provider;
    }
  } catch (e) {
    error.value = e.message || '加载模型失败。';
  }
});

function onFile(e) {
  file.value = e.target.files[0] || null;
}

async function loadRuleTemplate() {
  try {
    const data = await api.getRuleTemplate();
    if (data.success) {
      form.rules_override = data.rule_text || '';
    }
  } catch (e) {
    error.value = e.message || '加载规则失败。';
  }
}

async function upload() {
  if (!file.value) return;
  uploading.value = true;
  error.value = '';
  message.value = '';
  try {
    const formData = new FormData();
    formData.append('single_file', file.value);
    formData.append('auto_generate', '1');
    formData.append('sync_generate', '1');
    formData.append('count_per_api', String(form.count_per_api));
    formData.append('priority', form.priority);
    formData.append('llm_provider', form.llm_provider);
    formData.append('task_id', `task_${Date.now()}`);
    if (form.rules_override && form.rules_override.trim()) {
      formData.append('rules_override', form.rules_override);
    }
    const data = await api.uploadApiDefinition(formData);
    if (data.success) {
      apiList.value = data.api_list || [];
      selectedPaths.value = [];
      form.file_path = data.file_path;
      form.file_id = data.file_id;
      selectAll();
      if (data.result_json) {
        detail.value = {
          id: data.generation_id || null,
          file_name: file.value ? file.value.name : '',
          created_at: new Date().toISOString(),
          result_json: data.result_json,
          generated_cases: detailParsed.value?.apiDefinitions?.length || 0,
          selected_api_count: apiList.value.length
        };
        latestAutomationRun.value = null;
        await loadHistory();
        message.value = '生成成功。';
      } else if (data.task_id) {
        taskId.value = data.task_id;
        startLogStream();
        startProgressPoll();
      }
    } else {
      error.value = data.error || '上传失败。';
    }
  } catch (e) {
    error.value = e.message || '上传失败。';
  } finally {
    uploading.value = false;
  }
}

function selectAll() {
  selectedPaths.value = apiList.value.map((a) => a.path);
}

function clearAll() {
  selectedPaths.value = [];
}

async function generate() {
  if (!form.file_path || !selectedPaths.value.length) return;
  generating.value = true;
  error.value = '';
  message.value = '';
  logs.value = [];
  taskId.value = '';
  Object.keys(progress).forEach((k) => delete progress[k]);
  try {
    const selectedApis = apiList.value
      .filter((a) => selectedPaths.value.includes(a.path))
      .map((a) => ({
        path: a.path,
        name: a.name,
        method: a.method
      }));
    const formData = new FormData();
    formData.append('generate_test_cases', '1');
    formData.append('file_path', form.file_path);
    formData.append('selected_apis', JSON.stringify(selectedApis));
    formData.append('count_per_api', String(form.count_per_api));
    formData.append('priority', form.priority);
    formData.append('llm_provider', form.llm_provider);
    formData.append('task_id', `task_${Date.now()}`);
    if (form.file_id) {
      formData.append('file_id', String(form.file_id));
    }
    if (form.rules_override && form.rules_override.trim()) {
      formData.append('rules_override', form.rules_override);
    }

    const data = await api.generateApiCases(formData);
    if (data.success) {
      taskId.value = data.task_id;
      startLogStream();
      startProgressPoll();
    } else {
      error.value = data.error || '生成失败。';
    }
  } catch (e) {
    error.value = e.message || '生成失败。';
  } finally {
    generating.value = false;
  }
}

function startLogStream() {
  stopLogStream();
  if (!taskId.value) return;
  logSource = new EventSource(
    `${API_BASE}/api/stream-logs/?task_id=${encodeURIComponent(taskId.value)}`
  );
  logSource.addEventListener('log', (evt) => {
    try {
      const payload = JSON.parse(evt.data);
      if (payload.message) {
        logs.value.push(payload.message);
      }
    } catch (e) {
      logs.value.push(evt.data);
    }
  });
}

function stopLogStream() {
  if (logSource) {
    logSource.close();
    logSource = null;
  }
}

function startProgressPoll() {
  stopProgressPoll();
  if (!taskId.value) return;
  historyLoadedForTask.value = false;
  pollTimer = setInterval(async () => {
    try {
      const data = await apiFetchProgress();
      if (data && data.progress) {
        Object.assign(progress, data.progress);
        if (
          data.progress.percentage === 100 &&
          data.progress.generation_id &&
          !historyLoadedForTask.value
        ) {
          historyLoadedForTask.value = true;
          await loadHistory();
          await openHistoryDetail(data.progress.generation_id);
          message.value = '生成成功。';
        }
      }
    } catch (e) {
      // ignore
    }
  }, 2000);
}

function stopProgressPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function apiFetchProgress() {
  return apiGetProgress(
    `${API_BASE}/api/get-generation-progress/?task_id=${encodeURIComponent(taskId.value)}`
  );
}

async function apiGetProgress(path) {
  const resp = await fetch(path);
  if (!resp.ok) {
    throw new Error('进度获取失败');
  }
  return resp.json();
}

function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (e) {
    return String(value);
  }
}

function parseJson(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(value);
  } catch (e) {
    return null;
  }
}

const detailParsed = computed(() => parseJson(detail.value?.result_json));
const detailApis = computed(() => detailParsed.value?.apiDefinitions || []);

async function loadHistory() {
  loadingHistory.value = true;
  historyError.value = '';
  try {
    const data = await api.listApiCaseGenerations();
    history.value = data.items || [];
  } catch (e) {
    historyError.value = e.message || '获取历史失败。';
  } finally {
    loadingHistory.value = false;
  }
}

async function openHistoryDetail(id) {
  if (detail.value && detail.value.id === id) {
    detail.value = null;
    return;
  }
  try {
    const data = await api.getApiCaseGenerationDetail(id);
    if (data.success) {
      detail.value = data.item;
      latestAutomationRun.value = data.item.latest_automation_run || null;
    }
  } catch (e) {
    historyError.value = e.message || '获取详情失败。';
  }
}

async function runApiAutomation() {
  if (!detail.value?.id) return;
  automationRunning.value = true;
  automationMessage.value = '';
  try {
    const data = await api.runApiCaseGenerationAutomation(detail.value.id, {
      base_url: automationBaseUrl.value,
      case_index: 0
    });
    latestAutomationRun.value = data.run || null;
    automationMessage.value = latestAutomationRun.value?.passed ? '执行通过。' : '执行完成，存在失败。';
  } catch (e) {
    automationMessage.value = e.message || '执行失败。';
  } finally {
    automationRunning.value = false;
  }
}

onBeforeUnmount(() => {
  stopLogStream();
  stopProgressPoll();
});

onMounted(() => {
  loadHistory();
});
</script>

<style scoped>
.history-list {
  display: grid;
  gap: 10px;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 1px solid #f0e6dc;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff;
}

.history-main {
  display: grid;
  gap: 4px;
}

.history-title {
  font-weight: 600;
  color: #2e1f18;
}

.detail-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.detail-title {
  font-weight: 700;
  color: #2e1f18;
}

.points {
  display: grid;
  gap: 12px;
  margin-top: 12px;
}

.automation-panel {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.automation-result {
  display: grid;
  gap: 10px;
}

.result-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.tp-item {
  border: 1px solid #f2e3d7;
  border-radius: 12px;
  padding: 10px 12px;
  background: #fff;
}

.tp-item > summary {
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  list-style: none;
  font-weight: 600;
}

.tp-item > summary::-webkit-details-marker {
  display: none;
}

.tp-title {
  font-size: 16px;
  color: #2e1f18;
}

.tp-body {
  margin-top: 8px;
}

.scenarios {
  display: grid;
  gap: 10px;
}

.scenario {
  border: 1px solid #f3ebe5;
  border-radius: 10px;
  padding: 10px;
  background: #fffaf7;
}

.scenario-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.scenario-title {
  font-weight: 600;
  color: #2e1f18;
}

.badge {
  font-size: 12px;
  background: #f1f3f5;
  border-radius: 999px;
  padding: 2px 8px;
  color: #4d4d4d;
}

.tag {
  font-size: 12px;
  background: #ffe9d6;
  color: #9a4d00;
  border-radius: 999px;
  padding: 2px 8px;
}

.muted {
  color: #8a7a6d;
  font-size: 12px;
}

.text-block {
  background: #f6f7f9;
  border-radius: 8px;
  padding: 8px;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
}
</style>
