<template>
  <div class="card generation-jobs">
    <div class="jobs-header">
      <div>
        <h2>后台生成任务</h2>
        <p>切换页面不影响生成，任务完成后可在这里查看结果。</p>
      </div>
      <button class="secondary" @click="loadJobs" :disabled="loading">刷新</button>
    </div>

    <div v-if="error" class="notice error">{{ error }}</div>
    <div v-if="loading && !jobs.length" class="notice">正在加载任务...</div>
    <div v-if="!loading && !jobs.length" class="notice">暂无后台生成任务。</div>

    <table v-if="jobs.length" class="table">
      <thead>
        <tr>
          <th>来源</th>
          <th>任务</th>
          <th>状态</th>
          <th>进度</th>
          <th>结果</th>
          <th>更新时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="job in jobs" :key="job.id">
          <td>{{ sourceLabel(job.source_type) }}</td>
          <td>
            <div class="job-title">{{ job.source_title || '-' }}</div>
            <div class="job-subtitle">{{ job.llm_provider || '-' }}</div>
          </td>
          <td>
            <span class="badge" :class="`job-status-${job.status}`">
              {{ statusLabel(job.status) }}
            </span>
            <div v-if="job.message" class="job-subtitle">{{ job.message }}</div>
            <div v-if="job.error_message" class="job-error">{{ job.error_message }}</div>
          </td>
          <td>
            <progress :value="job.progress || 0" max="100"></progress>
            <div class="job-subtitle">{{ job.progress || 0 }}%</div>
          </td>
          <td>{{ job.result_count || 0 }} 条</td>
          <td>{{ formatTime(job.updated_at || job.created_at) }}</td>
          <td>
            <button class="secondary" @click="viewJob(job.id)" :disabled="detailLoading">
              查看结果
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="selectedJob" class="job-detail">
      <div class="jobs-header">
        <div>
          <h3>{{ selectedJob.source_title || `任务 #${selectedJob.id}` }}</h3>
          <p>
            {{ sourceLabel(selectedJob.source_type) }} · {{ statusLabel(selectedJob.status) }} ·
            {{ selectedCases.length }} 条结果
          </p>
        </div>
        <button class="secondary" @click="selectedJob = null">收起</button>
      </div>

      <div v-if="selectedJob.error_message" class="notice error">{{ selectedJob.error_message }}</div>

      <div v-if="selectedCases.length" class="job-cases">
        <table class="table">
          <thead>
            <tr>
              <th>#</th>
              <th>描述</th>
              <th>步骤</th>
              <th>预期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(tc, idx) in selectedCases" :key="idx">
              <td>{{ idx + 1 }}</td>
              <td>{{ tc.description }}</td>
              <td>
                <div v-for="(step, stepIdx) in tc.test_steps" :key="stepIdx">{{ step }}</div>
              </td>
              <td>
                <div v-for="(result, resultIdx) in tc.expected_results" :key="resultIdx">{{ result }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="notice">任务还没有可展示的结果。</div>

      <details v-if="generationMeta && Object.keys(generationMeta).length" class="trace-details">
        <summary>查看 Agent 执行信息</summary>
        <pre>{{ JSON.stringify(generationMeta, null, 2) }}</pre>
      </details>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { api } from '../api/endpoints';

const jobs = ref([]);
const loading = ref(false);
const detailLoading = ref(false);
const error = ref('');
const selectedJob = ref(null);
const selectedCases = ref([]);
const generationMeta = ref(null);
let pollTimer = null;

const runningStatuses = new Set(['queued', 'running', 'saving']);

function sourceLabel(sourceType) {
  const labels = {
    requirement: '需求生成',
    plane: 'Plane 生成'
  };
  return labels[sourceType] || sourceType || '-';
}

function statusLabel(status) {
  const labels = {
    queued: '排队中',
    running: '生成中',
    saving: '保存中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消'
  };
  return labels[status] || status || '-';
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString() : '-';
}

async function loadJobs() {
  loading.value = true;
  error.value = '';
  try {
    const data = await api.listGenerationJobs({ page: 1, pageSize: 20 });
    jobs.value = data.items || [];
  } catch (e) {
    error.value = e.message || '加载任务失败。';
  } finally {
    loading.value = false;
  }
}

async function viewJob(jobId) {
  detailLoading.value = true;
  error.value = '';
  try {
    const data = await api.getGenerationJob(jobId);
    selectedJob.value = data.job || null;
    selectedCases.value = data.test_cases || [];
    generationMeta.value = data.generation_meta || null;
  } catch (e) {
    error.value = e.message || '加载任务详情失败。';
  } finally {
    detailLoading.value = false;
  }
}

function startPolling() {
  pollTimer = window.setInterval(() => {
    if (!jobs.value.length || jobs.value.some((job) => runningStatuses.has(job.status))) {
      loadJobs();
    }
  }, 3000);
}

onMounted(() => {
  loadJobs();
  startPolling();
});

onUnmounted(() => {
  if (pollTimer) {
    window.clearInterval(pollTimer);
  }
});

defineExpose({
  loadJobs,
  viewJob
});
</script>

<style scoped>
.jobs-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.jobs-header h2,
.jobs-header h3 {
  margin: 0 0 4px;
}

.jobs-header p,
.job-subtitle {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.job-title {
  font-weight: 600;
}

.job-error {
  margin-top: 4px;
  color: var(--danger);
  font-size: 13px;
  max-width: 360px;
}

progress {
  width: 110px;
  height: 8px;
}

.job-detail {
  margin-top: 16px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--panel-soft);
}

.job-cases {
  overflow-x: auto;
}

.trace-details {
  margin-top: 12px;
}

.trace-details summary {
  cursor: pointer;
  font-weight: 600;
}

.trace-details pre {
  white-space: pre-wrap;
  word-break: break-word;
  padding: 12px;
  border-radius: 10px;
  background: var(--panel);
  border: 1px solid var(--border);
}

.job-status-completed {
  color: var(--success);
}

.job-status-failed {
  color: var(--danger);
}
</style>
