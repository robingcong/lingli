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
      <div class="flex" style="justify-content: space-between; align-items: center;">
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
            <div>{{ selectedItem.entry_type === 'rag_file' ? 'RAG 文档' : selectedItem.entry_type }}</div>
          </div>
          <div>
            <label>Chunk 数</label>
            <div>{{ selectedItem.chunk_count || 0 }}</div>
          </div>
        </div>

        <div style="margin-top: 16px;">
          <label>全文内容</label>
          <pre class="text-block">{{ selectedItem.full_content || selectedItem.content || '暂无内容' }}</pre>
        </div>

        <div style="margin-top: 16px;">
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
const searchResults = ref([]);
const query = ref('');
const message = ref('');
const error = ref('');
const searching = ref(false);
const selectedItem = ref(null);
const detailLoading = ref(false);
const activeEntryId = ref('');

const formatTime = (value) => (value ? new Date(value).toLocaleString() : '');

async function load() {
  try {
    const data = await api.listKnowledgeLibrary();
    items.value = data.items || [];
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
    message.value = e.message || '搜索失败。';
  } finally {
    searching.value = false;
  }
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
</style>
