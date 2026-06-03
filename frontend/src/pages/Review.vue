<template>
  <div>
    <div class="card">
      <h2>用例评审</h2>
      <div class="form-grid" style="margin-bottom: 12px;">
        <div>
          <label>状态</label>
          <select v-model="status" @change="resetAndLoad">
            <option value="pending">待评审</option>
            <option value="approved">已通过</option>
            <option value="rejected">未通过</option>
          </select>
        </div>
        <div>
          <label>每页数量</label>
          <select v-model.number="pageSize" @change="resetAndLoad">
            <option :value="10">10</option>
            <option :value="15">15</option>
            <option :value="20">20</option>
            <option :value="30">30</option>
          </select>
        </div>
        <div>
          <label>关键词</label>
          <input v-model="keyword" placeholder="过滤需求名/标题/描述" />
        </div>
      </div>

      <div class="flex" style="margin-bottom: 12px;">
        <button class="secondary" @click="copySelected" :disabled="!selectedIds.length">复制所选</button>
        <button class="secondary" @click="exportSelected" :disabled="!selectedIds.length">导出表格</button>
        <button class="danger" @click="deleteSelected" :disabled="!selectedIds.length">删除</button>
        <button class="secondary" @click="expandAllGroups">全部展开</button>
        <button class="secondary" @click="collapseAllGroups">全部收起</button>
      </div>

      <table class="table" v-if="groupedItems.length">
        <thead>
          <tr>
            <th><input type="checkbox" :checked="allVisibleSelected" @change="toggleAllVisible($event.target.checked)" /></th>
            <th>需求（父）/ 用例（子）</th>
            <th>状态</th>
            <th>快速更新</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in groupedItems" :key="group.groupKey">
            <tr class="group-row">
              <td>
                <input
                  type="checkbox"
                  :checked="isGroupChecked(group)"
                  @change="toggleGroupSelection(group, $event.target.checked)"
                />
              </td>
              <td colspan="4">
                <div class="group-head">
                  <button class="secondary" @click="toggleGroup(group)">
                    {{ isGroupExpanded(group) ? '收起' : '展开' }}
                  </button>
                  <span class="group-count">{{ group.children.length }} 条用例</span>
                </div>
                <div class="group-title">{{ group.parentName }}</div>
                <div class="group-sub" v-if="group.childName">{{ group.childName }}</div>
              </td>
            </tr>

            <tr v-for="item in group.children" :key="item.id" v-show="isGroupExpanded(group)">
              <td><input type="checkbox" :value="item.id" v-model="selectedIds" /></td>
              <td>
                <div class="case-title"><strong>#{{ item.id }}</strong> {{ item.title || '未命名用例' }}</div>
                <div class="case-desc">{{ item.description }}</div>
                <div class="case-meta">
                  <span>{{ item.llm_provider || '未知模型' }}</span>
                  <span v-if="item.ai_review?.score">AI 评分 {{ item.ai_review.score }}</span>
                </div>
              </td>
              <td><span class="badge" :class="statusClass(item.status)">{{ statusText(item.status) }}</span></td>
              <td>
                <div class="flex">
                  <select v-model="item._next_status">
                    <option value="pending">待评审</option>
                    <option value="approved">已通过</option>
                    <option value="rejected">未通过</option>
                  </select>
                  <button class="secondary" @click="updateStatus(item)">更新</button>
                </div>
              </td>
              <td>
                <RouterLink :to="`/review/${item.id}`">详情</RouterLink>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-else class="notice">暂无用例。</div>

      <div class="pagination">
        <button class="secondary" @click="prevPage" :disabled="page <= 1">上一页</button>
        <div>第 {{ page }} / {{ totalPages }} 页</div>
        <button class="secondary" @click="nextPage" :disabled="page >= totalPages">下一页</button>
      </div>

      <div v-if="message" class="notice">{{ message }}</div>
      <div v-if="error" class="notice error">{{ error }}</div>
    </div>

    <div class="card" v-if="copied.length">
      <h2>复制结果</h2>
      <pre>{{ JSON.stringify(copied, null, 2) }}</pre>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import { api } from '../api/endpoints';
import { API_BASE } from '../api/client';

const status = ref('pending');
const page = ref(1);
const pageSize = ref(15);
const totalPages = ref(1);
const items = ref([]);
const selectedIds = ref([]);
const copied = ref([]);
const message = ref('');
const error = ref('');
const keyword = ref('');
const groupExpanded = ref({});

const statusClass = (value) => {
  if (value === 'pending') return 'status-pending';
  if (value === 'approved') return 'status-approved';
  if (value === 'rejected') return 'status-rejected';
  return '';
};

const statusText = (value) => {
  if (value === 'pending') return '待评审';
  if (value === 'approved') return '已通过';
  if (value === 'rejected') return '未通过';
  return value || '';
};

const filteredItems = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  if (!kw) return items.value;
  return items.value.filter((item) => {
    const req = (item.requirements || '').toLowerCase();
    const title = (item.title || '').toLowerCase();
    const desc = (item.description || '').toLowerCase();
    return req.includes(kw) || title.includes(kw) || desc.includes(kw);
  });
});

function extractRequirementMeta(requirements, fallback = '') {
  const req = (requirements || '').trim();
  if (!req) {
    return {
      groupKey: fallback || '未命名需求',
      parentName: fallback || '未命名需求',
      childName: ''
    };
  }

  const matchTitle = req.match(/【工作项标题】([^\n\r]+)/);
  const matchId = req.match(/【工作项ID】([^\n\r]+)/);
  const matchContent = req.match(/【工作项内容】([\s\S]*)$/);

  const parentName = (matchTitle?.[1] || '').trim() || req.split(/\r?\n/)[0] || req;
  const parentId = (matchId?.[1] || '').trim();

  const contentRaw = (matchContent?.[1] || req).trim();
  const childName = contentRaw
    ? contentRaw
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 120)
    : '';

  return {
    groupKey: parentId || parentName || '未命名需求',
    parentName: parentName || '未命名需求',
    childName
  };
}

const groupedItems = computed(() => {
  const groups = new Map();
  for (const item of filteredItems.value) {
    const meta = extractRequirementMeta(item.requirements, item.title || item.description || '');
    if (!groups.has(meta.groupKey)) {
      groups.set(meta.groupKey, {
        groupKey: meta.groupKey,
        parentName: meta.parentName,
        childName: meta.childName,
        children: []
      });
    }
    groups.get(meta.groupKey).children.push(item);
  }
  return Array.from(groups.values());
});

const allVisibleIds = computed(() => filteredItems.value.map((item) => item.id));
const allVisibleSelected = computed(() => (
  allVisibleIds.value.length > 0
  && allVisibleIds.value.every((id) => selectedIds.value.includes(id))
));

function isGroupExpanded(group) {
  return groupExpanded.value[group.groupKey] !== false;
}

function toggleGroup(group) {
  const key = group.groupKey;
  groupExpanded.value[key] = !isGroupExpanded(group);
}

function expandAllGroups() {
  const next = {};
  for (const group of groupedItems.value) {
    next[group.groupKey] = true;
  }
  groupExpanded.value = next;
}

function collapseAllGroups() {
  const next = {};
  for (const group of groupedItems.value) {
    next[group.groupKey] = false;
  }
  groupExpanded.value = next;
}

function isGroupChecked(group) {
  if (!group.children.length) return false;
  return group.children.every((child) => selectedIds.value.includes(child.id));
}

function toggleGroupSelection(group, checked) {
  const ids = group.children.map((child) => child.id);
  if (checked) {
    selectedIds.value = Array.from(new Set([...selectedIds.value, ...ids]));
  } else {
    const idSet = new Set(ids);
    selectedIds.value = selectedIds.value.filter((id) => !idSet.has(id));
  }
}

function toggleAllVisible(checked) {
  selectedIds.value = checked ? [...allVisibleIds.value] : [];
}

async function load() {
  error.value = '';
  message.value = '';
  try {
    const data = await api.listTestCases(status.value, page.value, pageSize.value);
    items.value = (data.items || []).map((item) => ({ ...item, _next_status: item.status }));
    totalPages.value = data.total_pages || 1;
    selectedIds.value = [];
  } catch (e) {
    error.value = e.message || '加载失败。';
  }
}

function resetAndLoad() {
  page.value = 1;
  load();
}

function prevPage() {
  if (page.value > 1) {
    page.value -= 1;
    load();
  }
}

function nextPage() {
  if (page.value < totalPages.value) {
    page.value += 1;
    load();
  }
}

async function copySelected() {
  if (!selectedIds.value.length) return;
  try {
    const data = await api.copyTestCases(selectedIds.value);
    copied.value = data.test_cases || [];
  } catch (e) {
    error.value = e.message || '复制失败。';
  }
}

function exportSelected() {
  if (!selectedIds.value.length) return;
  const ids = selectedIds.value.join(',');
  window.location.href = `${API_BASE}/api/export-test-cases-excel/?ids=${encodeURIComponent(ids)}`;
}

async function deleteSelected() {
  if (!selectedIds.value.length) return;
  try {
    const data = await api.deleteTestCases(selectedIds.value);
    message.value = data.message || '删除成功。';
    await load();
  } catch (e) {
    error.value = e.message || '删除失败。';
  }
}

async function updateStatus(item) {
  if (!item || !item._next_status) return;
  try {
    const data = await api.updateStatus({ test_case_id: item.id, status: item._next_status });
    if (data.success) {
      item.status = item._next_status;
      message.value = '状态已更新。';
    } else {
      message.value = data.message || '更新失败。';
    }
  } catch (e) {
    message.value = e.message || '更新失败。';
  }
}

watch(groupedItems, (groups) => {
  const next = {};
  for (const group of groups) {
    next[group.groupKey] = groupExpanded.value[group.groupKey] !== false;
  }
  groupExpanded.value = next;
}, { immediate: true });

onMounted(load);
</script>

<style scoped>
.group-row td {
  background: var(--panel-soft);
}

.group-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.group-count {
  color: var(--muted);
  font-weight: 600;
}

.group-title {
  margin-top: 8px;
  word-break: break-word;
  color: var(--text);
  font-size: 16px;
  font-weight: 700;
}

.group-sub {
  margin-top: 6px;
  margin-left: 20px;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.5;
  word-break: break-word;
}

.case-title {
  margin-left: 16px;
  font-size: 14px;
}

.case-desc {
  margin-top: 4px;
  margin-left: 16px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.case-meta {
  display: flex;
  gap: 10px;
  margin-top: 6px;
  margin-left: 16px;
  color: var(--muted);
  font-size: 12px;
}
</style>
