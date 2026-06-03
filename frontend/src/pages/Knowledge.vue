<template>
  <div>
    <div class="card">
      <h2>检索</h2>
      <div class="flex">
        <input v-model="query" placeholder="请输入关键字" />
        <button @click="search" :disabled="searching">搜索</button>
      </div>
      <div v-if="searchResults.length" style="margin-top: 12px;">
        <table class="table">
          <thead>
            <tr>
              <th>命中内容</th>
              <th>相似度</th>
              <th>来源文件</th>
              <th>Chunk ID</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in searchResults" :key="idx">
              <td>{{ item.content }}</td>
              <td>{{ Number(item.score || 0).toFixed(4) }}</td>
              <td>{{ item.source }}</td>
              <td>{{ item.chunk_id || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="section-title-row">
        <h2>手动添加知识</h2>
        <span class="muted">提交后写入 MySQL，并同步写入 Milvus 向量库</span>
      </div>
      <div class="manual-form">
        <input v-model="manualTitle" placeholder="请输入知识标题，例如：集群任务规划规则" />
        <textarea
          v-model="manualContent"
          rows="6"
          placeholder="请输入知识内容。建议写清业务规则、限制条件、异常场景或验收标准。"
        ></textarea>
        <div class="form-actions">
          <button @click="addManualKnowledge" :disabled="addingManual">
            {{ addingManual ? '添加中...' : '添加知识' }}
          </button>
          <button class="secondary" @click="resetManualForm" :disabled="addingManual">清空</button>
        </div>
      </div>
      <div v-if="message" class="notice success">{{ message }}</div>
      <div v-if="manualError" class="notice error">{{ manualError }}</div>
    </div>

    <div class="card">
      <div class="section-title-row">
        <h2>手动知识条目</h2>
        <span class="muted">单独展示手动添加的知识，不和 /docs/rag 文档混在一起</span>
      </div>
      <table class="table" v-if="manualItems.length">
        <thead>
          <tr>
            <th>标题</th>
            <th>内容摘要</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in manualItems" :key="item.entry_id || item.id">
            <td>{{ item.title }}</td>
            <td>{{ item.summary || item.content }}</td>
            <td>{{ formatTime(item.updated_at || item.created_at) }}</td>
            <td>
              <button class="secondary" @click="openManualDetail(item)">查看内容</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="notice">暂无手动知识条目。</div>
    </div>

    <div class="card">
      <div class="section-title-row">
        <h2>知识库内容</h2>
        <span class="muted">仅展示 /docs/rag 下的知识库文档</span>
      </div>
      <table class="table" v-if="items.length">
        <thead>
          <tr>
            <th>文件名</th>
            <th>路径</th>
            <th>Chunk 数</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.entry_id">
            <td>{{ item.title }}</td>
            <td>{{ item.source }}</td>
            <td>{{ item.chunk_count || 0 }}</td>
            <td>{{ formatTime(item.updated_at || item.created_at) }}</td>
            <td>
              <button class="secondary" @click="openDetail(item)" :disabled="detailLoading && activeEntryId === item.entry_id">
                查看详情
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="notice">暂无知识条目。</div>
      <div v-if="error" class="notice error">{{ error }}</div>
    </div>

    <div v-if="selectedItem" class="card">
      <div class="flex" style="justify-content: space-between; align-items: center;">
        <div>
          <h2>{{ selectedItem.title }}</h2>
          <div class="muted">{{ selectedItem.source }}</div>
        </div>
        <button class="secondary" @click="selectedItem = null">关闭</button>
      </div>

      <div v-if="detailLoading" class="notice" style="margin-top: 12px;">正在加载详情...</div>
      <div v-else>
        <div class="form-grid" style="margin-top: 12px;">
          <div>
            <label>类型</label>
            <div>{{ entryTypeText(selectedItem) }}</div>
          </div>
          <div v-if="selectedItem.entry_type !== 'manual'">
            <label>Chunk 数</label>
            <div>{{ selectedItem.chunk_count || 0 }}</div>
          </div>
          <div v-else>
            <label>来源</label>
            <div>{{ selectedItem.source || '手动添加' }}</div>
          </div>
        </div>

        <div style="margin-top: 16px;">
          <label>全文内容</label>
          <pre class="text-block">{{ selectedItem.full_content || selectedItem.content || '暂无内容' }}</pre>
        </div>

        <div v-if="selectedItem.entry_type !== 'manual'" style="margin-top: 16px;">
          <label>Chunk 明细</label>
          <div v-if="selectedItem.chunks?.length">
            <details v-for="chunk in selectedItem.chunks" :key="chunk.chunk_id" class="chunk-item">
              <summary>
                <span>{{ chunk.chunk_id }}</span>
                <span class="muted">{{ chunk.upload_time ? formatTime(chunk.upload_time) : '' }}</span>
              </summary>
              <pre class="text-block">{{ chunk.content }}</pre>
            </details>
          </div>
          <div v-else class="notice">暂无 chunk 明细。</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { api } from '../api/endpoints';

const items = ref([]);
const manualItems = ref([]);
const searchResults = ref([]);
const query = ref('');
const message = ref('');
const error = ref('');
const manualError = ref('');
const searching = ref(false);
const addingManual = ref(false);
const selectedItem = ref(null);
const detailLoading = ref(false);
const activeEntryId = ref('');
const manualTitle = ref('');
const manualContent = ref('');

const formatTime = (value) => (value ? new Date(value).toLocaleString() : '');
const entryTypeText = (item) => {
  if (item?.entry_type === 'rag_file') return 'RAG 文档';
  if (item?.entry_type === 'manual') return '手动知识';
  return item?.entry_type || '-';
};

async function load() {
  try {
    error.value = '';
    const [libraryData, manualData] = await Promise.all([
      api.listKnowledgeLibrary(),
      api.listKnowledge()
    ]);
    items.value = libraryData.items || [];
    manualItems.value = manualData.knowledge_items || [];
  } catch (e) {
    error.value = e.message || '加载失败。';
  }
}

async function search() {
  if (!query.value.trim()) return;
  searching.value = true;
  try {
    const data = await api.searchKnowledge({ query: query.value });
    searchResults.value = data.results || [];
  } catch (e) {
    error.value = e.message || '搜索失败。';
  } finally {
    searching.value = false;
  }
}

function resetManualForm() {
  manualTitle.value = '';
  manualContent.value = '';
  manualError.value = '';
  message.value = '';
}

async function addManualKnowledge() {
  const title = manualTitle.value.trim();
  const content = manualContent.value.trim();
  manualError.value = '';
  message.value = '';
  if (!title || !content) {
    manualError.value = '标题和内容不能为空。';
    return;
  }
  addingManual.value = true;
  try {
    await api.addKnowledge({ title, content });
    manualTitle.value = '';
    manualContent.value = '';
    message.value = '知识条目添加成功，已写入知识库。';
    await load();
  } catch (e) {
    manualError.value = e.message || '添加失败。';
  } finally {
    addingManual.value = false;
  }
}

function openManualDetail(item) {
  selectedItem.value = {
    ...item,
    entry_type: 'manual',
    source: item.source || '手动添加',
    full_content: item.content,
    chunks: []
  };
}

async function openDetail(item) {
  detailLoading.value = true;
  activeEntryId.value = item.entry_id;
  try {
    const data = await api.getKnowledgeLibraryDetail(item.entry_id);
    selectedItem.value = data.item || item;
  } catch (e) {
    error.value = e.message || '加载详情失败。';
  } finally {
    detailLoading.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.section-title-row h2 {
  margin-bottom: 0;
}

.manual-form {
  display: grid;
  gap: 10px;
}

.form-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.notice.success {
  background: var(--panel-soft);
  color: var(--success);
}

.muted {
  color: var(--muted-color, #666);
  font-size: 12px;
}

.text-block {
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 8px;
  padding: 12px;
}

.chunk-item {
  margin-top: 8px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 8px;
  padding: 8px 12px;
}

.chunk-item summary {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
}

@media (max-width: 720px) {
  .section-title-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
