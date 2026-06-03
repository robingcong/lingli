<template>
  <div>
    <div class="card">
      <h2>概览</h2>
      <div class="form-grid">
        <div>
          <div class="badge">总量</div>
          <div>{{ stats.total }}</div>
        </div>
        <div>
          <div class="badge status-pending">待评审</div>
          <div>{{ stats.pending }}</div>
        </div>
        <div>
          <div class="badge status-approved">已通过</div>
          <div>{{ stats.approved }}</div>
        </div>
        <div>
          <div class="badge status-rejected">未通过</div>
          <div>{{ stats.rejected }}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>最近用例</h2>
      <table class="table" v-if="recent.length">
        <thead>
          <tr>
            <th>编号</th>
            <th>描述</th>
            <th>状态</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in recent" :key="item.id">
            <td>{{ item.id }}</td>
            <td>{{ item.description }}</td>
            <td>
              <span class="badge" :class="statusClass(item.status)">{{ statusText(item.status) }}</span>
            </td>
            <td>{{ formatTime(item.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="notice">暂无用例。</div>
    </div>

    <div v-if="error" class="notice error">{{ error }}</div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { api } from '../api/endpoints';

const stats = reactive({ total: 0, pending: 0, approved: 0, rejected: 0 });
const recent = ref([]);
const error = ref('');

const statusClass = (status) => {
  if (status === 'pending') return 'status-pending';
  if (status === 'approved') return 'status-approved';
  if (status === 'rejected') return 'status-rejected';
  return '';
};

const statusText = (status) => {
  if (status === 'pending') return '待评审';
  if (status === 'approved') return '已通过';
  if (status === 'rejected') return '未通过';
  return status || '';
};

const formatTime = (value) => {
  if (!value) return '';
  return new Date(value).toLocaleString();
};

onMounted(async () => {
  try {
    const data = await api.getDashboard();
    stats.total = data.total || 0;
    stats.pending = data.pending || 0;
    stats.approved = data.approved || 0;
    stats.rejected = data.rejected || 0;
    recent.value = data.recent || [];
  } catch (e) {
    error.value = e.message || '加载失败。';
  }
});
</script>
