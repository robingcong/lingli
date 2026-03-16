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
                生成测试用例
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

    <div v-if="oneClickLoading" class="notice">一键生成并保存中...</div>
    <div v-if="generateError" class="notice error">{{ generateError }}</div>

    <div class="card" v-if="testCases.length">
      <h2>生成结果</h2>
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

const form = reactive({
  llm_provider: 'deepseek',
  case_count: 0
});

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
  testCases.value = [];
  const targetId = itemId || selectedId.value;
  if (!targetId) {
    generateError.value = '请先选择一个 Plane 工作项。';
    return;
  }
  oneClickLoading.value = true;
  try {
    const data = await api.planeOneClickGenerate({
      id: targetId,
      llm_provider: form.llm_provider,
      case_count: form.case_count
    });
    testCases.value = data.test_cases || [];
    effectiveProvider.value = data.effective_provider || form.llm_provider;
    saveMessage.value = data.message || '一键生成并保存成功。';
    if (effectiveProvider.value && effectiveProvider.value !== form.llm_provider) {
      saveMessage.value += ` 已自动切换到 ${effectiveProvider.value}。`;
    }
  } catch (e) {
    generateError.value = e.message || '一键生成失败。';
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
}
</script>
