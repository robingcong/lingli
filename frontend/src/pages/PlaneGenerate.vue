<template>
  <div>
    <div class="card">
      <h2>Plane 一键生成</h2>
      <div class="form-grid">
        <div>
          <label>模型选择</label>
          <select v-model="form.llm_provider">
            <option v-for="p in providers" :key="p.key" :value="p.key">{{ p.name }}</option>
          </select>
        </div>
        <div>
          <label>刷新数量（0=全部）</label>
          <input v-model.number="refreshMaxItems" type="number" min="0" />
        </div>
      </div>

      <div class="flex" style="margin-top: 12px;">
        <button @click="refreshFromPlane" :disabled="refreshing">手动刷新 Plane</button>
        <select v-model="projectId" style="max-width: 260px;" @change="onProjectChange">
          <option value="">全部项目</option>
          <option v-for="p in projects" :key="p.project_id" :value="p.project_id">
            {{ p.project_name || p.project_id }}
          </option>
        </select>
        <input v-model="keyword" placeholder="搜索项目/标题/内容" style="max-width: 280px;" />
        <button class="secondary" @click="loadPlaneItems" :disabled="loadingItems">查询</button>
      </div>

      <div class="preference-panel">
        <div class="preference-header">
          <div>
            <h3>生成偏向</h3>
            <p>用于控制 Plane 工作项生成时的覆盖方向，默认优先展开更多功能点。</p>
          </div>
          <span class="badge">影响生成 prompt</span>
        </div>
        <div class="form-grid">
          <div>
            <label>生成模式</label>
            <select v-model="form.generation_profile">
              <option v-for="profile in generationProfiles" :key="profile.value" :value="profile.value">
                {{ profile.label }} - {{ profile.description }}
              </option>
            </select>
          </div>
          <div>
            <label>偏向强度</label>
            <select v-model="form.focus_strength">
              <option v-for="strength in focusStrengthOptions" :key="strength.value" :value="strength.value">
                {{ strength.label }}
              </option>
            </select>
          </div>
        </div>
        <div style="margin-top: 12px;">
          <label>测试类型</label>
          <div class="checkbox-grid">
            <label v-for="category in caseCategories" :key="category.value" class="check-pill">
              <input v-model="form.case_categories" type="checkbox" :value="category.value" />
              <span>{{ category.label }}</span>
            </label>
          </div>
          <p class="form-hint">默认只生成“功能测试”；性能、安全、兼容只在勾选后参与生成。</p>
        </div>
        <div style="margin-top: 12px;">
          <label>偏向点</label>
          <div class="checkbox-grid">
            <label v-for="point in focusPointOptions" :key="point" class="check-pill">
              <input v-model="form.focus_points" type="checkbox" :value="point" />
              <span>{{ point }}</span>
            </label>
          </div>
        </div>
      </div>

      <div v-if="refreshMessage" class="notice">{{ refreshMessage }}</div>
      <div v-if="error" class="notice error">{{ error }}</div>
    </div>

    <div class="card">
      <h2>Plane 工作项</h2>
      <table class="table">
        <thead>
          <tr>
            <th>选择</th>
            <th>项目</th>
            <th>标题</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in planeItems" :key="item.id">
            <td>
              <input type="radio" name="plane-item" :value="item.id" v-model="selectedId" />
            </td>
            <td>{{ item.project_name }}</td>
            <td>{{ item.work_item_name }}</td>
            <td>{{ item.updated_at }}</td>
            <td>
              <button class="secondary" @click="oneClickGenerate(item.id)" :disabled="oneClickLoading">
                后台生成测试用例
              </button>
            </td>
          </tr>
          <tr v-if="!planeItems.length">
            <td colspan="5">暂无数据，请先手动刷新。</td>
          </tr>
        </tbody>
      </table>
      <div class="flex" style="margin-top: 12px;">
        <button class="secondary" @click="prevPage" :disabled="page <= 1">上一页</button>
        <span>第 {{ page }} / {{ totalPages || 1 }} 页，共 {{ total }} 条</span>
        <button class="secondary" @click="nextPage" :disabled="page >= totalPages">下一页</button>
      </div>
    </div>

    <div v-if="oneClickLoading" class="notice">正在提交后台任务...</div>
    <div v-if="generateError" class="notice error">{{ generateError }}</div>

    <GenerationJobs ref="jobsRef" />

    <div class="card" v-if="testCases.length">
      <h2>生成结果</h2>
      <div v-if="generationMeta" class="agent-trace">
        <div class="trace-summary">
          <div class="trace-metric">
            <span>总耗时</span>
            <strong>{{ formatMs(generationMeta.total_elapsed_ms) }}</strong>
          </div>
          <div class="trace-metric">
            <span>Agent 模式</span>
            <strong>{{ formatMode(generationMeta.mode) }}</strong>
          </div>
          <div class="trace-metric">
            <span>生成数量</span>
            <strong>{{ generationMeta.returned_count || testCases.length }}</strong>
          </div>
          <div class="trace-metric">
            <span>候选/保留</span>
            <strong>{{ generationMeta.metadata?.candidate_count ?? '-' }} / {{ generationMeta.metadata?.retained_count ?? '-' }}</strong>
          </div>
        </div>
        <div v-if="generationMeta.metadata?.missing_coverages?.length" class="trace-warning">
          未完全覆盖：{{ generationMeta.metadata.missing_coverages.join('、') }}
        </div>
        <details class="trace-details">
          <summary>查看 Agent 执行明细</summary>
          <table class="table trace-table">
            <thead>
              <tr>
                <th>阶段</th>
                <th>耗时</th>
                <th>关键信息</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="step in generationMeta.steps || []" :key="step.name">
                <td>{{ formatStageName(step.name) }}</td>
                <td>{{ formatMs(step.elapsed_ms) }}</td>
                <td>{{ formatStepMeta(step.metadata) }}</td>
              </tr>
            </tbody>
          </table>
        </details>
      </div>
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
          <tr v-for="(tc, idx) in testCases" :key="idx">
            <td>{{ idx + 1 }}</td>
            <td>{{ tc.description }}</td>
            <td>
              <div v-for="(s, sidx) in tc.test_steps" :key="sidx">{{ s }}</div>
            </td>
            <td>
              <div v-for="(r, ridx) in tc.expected_results" :key="ridx">{{ r }}</div>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="flex" style="margin-top: 12px;">
        <span v-if="saveMessage" class="notice">{{ saveMessage }}</span>
        <span v-if="effectiveProvider" class="notice">实际使用模型：{{ effectiveProvider }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { api } from '../api/endpoints';
import GenerationJobs from '../components/GenerationJobs.vue';
import {
  buildDefaultGenerationPreferences,
  focusPointOptions,
  focusStrengthOptions,
  generationProfiles
} from '../constants/generationPreferences';

const providers = ref([]);
const refreshing = ref(false);
const loadingItems = ref(false);
const oneClickLoading = ref(false);
const error = ref('');
const generateError = ref('');
const saveMessage = ref('');
const refreshMessage = ref('');
const testCases = ref([]);
const effectiveProvider = ref('');
const generationMeta = ref(null);
const jobsRef = ref(null);

const form = reactive({
  llm_provider: 'deepseek',
  case_count: 0,
  case_categories: ['functional'],
  ...buildDefaultGenerationPreferences()
});

const caseCategories = [
  { value: 'functional', label: '功能测试' },
  { value: 'performance', label: '性能测试' },
  { value: 'compatibility', label: '兼容性测试' },
  { value: 'security', label: '安全测试' }
];

const mapLabels = (values, options) => {
  const map = new Map(options.map((o) => [o.value, o.label]));
  return values.map((v) => map.get(v) || v);
};

const refreshMaxItems = ref(0);
const keyword = ref('');
const page = ref(1);
const pageSize = ref(20);
const totalPages = ref(1);
const total = ref(0);
const planeItems = ref([]);
const projects = ref([]);
const projectId = ref('');
const selectedId = ref(null);

onMounted(async () => {
  await Promise.all([loadProviders(), loadPlaneItems()]);
});

async function loadProviders() {
  try {
    const data = await api.getProviders();
    providers.value = data.providers || [];
    const hasQwen = providers.value.some((p) => p.key === 'qwen');
    if (hasQwen) {
      form.llm_provider = 'qwen';
    } else if (data.default_provider) {
      form.llm_provider = data.default_provider;
    }
  } catch (e) {
    error.value = e.message || '加载模型失败。';
  }
}

async function loadPlaneItems() {
  loadingItems.value = true;
  error.value = '';
  try {
    const data = await api.listPlaneWorkItems({
      page: page.value,
      pageSize: pageSize.value,
      keyword: keyword.value,
      projectId: projectId.value
    });
    planeItems.value = data.items || [];
    projects.value = data.projects || [];
    total.value = data.total || 0;
    totalPages.value = data.total_pages || 1;
    if (selectedId.value && !planeItems.value.some((item) => String(item.id) === String(selectedId.value))) {
      selectedId.value = null;
    }
  } catch (e) {
    error.value = e.message || '加载 Plane 工作项失败。';
  } finally {
    loadingItems.value = false;
  }
}

async function refreshFromPlane() {
  refreshing.value = true;
  refreshMessage.value = '';
  error.value = '';
  try {
    const data = await api.refreshPlaneWorkItems({ max_items: refreshMaxItems.value });
    refreshMessage.value = `刷新完成：同步 ${data.synced_count} 条（新增 ${data.created_count}，更新 ${data.updated_count}）`;
    page.value = 1;
    await loadPlaneItems();
  } catch (e) {
    error.value = e.message || '刷新失败。';
  } finally {
    refreshing.value = false;
  }
}

async function oneClickGenerate(itemId = null) {
  generateError.value = '';
  saveMessage.value = '';
  effectiveProvider.value = '';
  generationMeta.value = null;
  testCases.value = [];
  const targetId = itemId || selectedId.value;
  if (!targetId) {
    generateError.value = '请先选择一个 Plane 工作项。';
    return;
  }
  if (!form.case_categories.length) {
    generateError.value = '请至少选择一种测试类型。';
    return;
  }
  oneClickLoading.value = true;
  try {
    const data = await api.createGenerationJob({
      source_type: 'plane',
      plane_item_id: targetId,
      llm_provider: form.llm_provider,
      case_count: form.case_count,
      case_categories: mapLabels(form.case_categories, caseCategories),
      generation_profile: form.generation_profile,
      focus_points: form.focus_points,
      focus_strength: form.focus_strength
    });
    saveMessage.value = data.message || `任务 #${data.job_id} 已提交后台生成。`;
    await jobsRef.value?.loadJobs?.();
  } catch (e) {
    generateError.value = e.message || '提交后台任务失败。';
  } finally {
    oneClickLoading.value = false;
  }
}

function prevPage() {
  if (page.value <= 1) return;
  page.value -= 1;
  loadPlaneItems();
}

function nextPage() {
  if (page.value >= totalPages.value) return;
  page.value += 1;
  loadPlaneItems();
}

function onProjectChange() {
  page.value = 1;
  loadPlaneItems();
}

function reset() {
  testCases.value = [];
  generateError.value = '';
  saveMessage.value = '';
  effectiveProvider.value = '';
  generationMeta.value = null;
}

function formatMs(value) {
  const numberValue = Number(value || 0);
  if (!Number.isFinite(numberValue)) return '-';
  if (numberValue >= 1000) return `${(numberValue / 1000).toFixed(2)}s`;
  return `${numberValue.toFixed(0)}ms`;
}

function formatMode(mode) {
  const labels = {
    fast_single_call: '极速单次',
    fast_parallel: '极速并行',
    deep_with_review: '深度评审',
    deep_local_filter: '深度本地过滤'
  };
  return labels[mode] || mode || '-';
}

function formatStageName(name) {
  const labels = {
    knowledge_retrieval: 'RAG 检索',
    requirement_normalization: '需求归一化',
    llm_generation: 'LLM 生成',
    quality_filtering: '质量过滤',
    finalization: '结果整理'
  };
  if (labels[name]) return labels[name];
  return String(name || '-').replaceAll('_', ' ');
}

function formatStepMeta(metadata = {}) {
  const parts = [];
  if (metadata.context_chars !== undefined) parts.push(`上下文 ${metadata.context_chars} 字`);
  if (metadata.candidate_count !== undefined) parts.push(`候选 ${metadata.candidate_count}`);
  if (metadata.deduped_count !== undefined) parts.push(`去重后 ${metadata.deduped_count}`);
  if (metadata.qualified_count !== undefined) parts.push(`达标 ${metadata.qualified_count}`);
  if (metadata.retained_count !== undefined) parts.push(`保留 ${metadata.retained_count}`);
  if (metadata.returned_count !== undefined) parts.push(`返回 ${metadata.returned_count}`);
  if (metadata.missing_coverages?.length) parts.push(`缺失 ${metadata.missing_coverages.join('、')}`);
  if (metadata.request_count !== undefined) parts.push(`请求 ${metadata.request_count}`);
  if (metadata.subtasks?.length) parts.push(`子任务 ${metadata.subtasks.length}`);
  return parts.join('，') || '-';
}
</script>

<style scoped>
.agent-trace {
  margin-bottom: 16px;
  padding: 14px;
  border: 1px solid #dbe3ef;
  border-radius: 12px;
  background: linear-gradient(135deg, #f8fbff 0%, #eef6ff 100%);
}

.trace-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
}

.trace-metric {
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.24);
}

.trace-metric span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.trace-metric strong {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 16px;
}

.trace-warning {
  margin-top: 10px;
  color: #9a3412;
  font-size: 13px;
}

.trace-details {
  margin-top: 12px;
}

.trace-details summary {
  cursor: pointer;
  color: #2563eb;
  font-weight: 600;
}

.trace-table {
  margin-top: 10px;
}
</style>
