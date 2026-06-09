<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <h1>AiCase</h1>
        <button class="theme-toggle" @click="toggleTheme" :aria-label="`切换主题，当前为${themeLabel}`">
          <span class="theme-icon" aria-hidden="true">{{ themeIcon }}</span>
          <span>{{ themeLabel }}</span>
        </button>
      </div>
      <nav class="nav">
        <RouterLink to="/">看板</RouterLink>
        <RouterLink to="/generate">用例生成</RouterLink>
        <RouterLink to="/plane-generate">Plane 一键生成</RouterLink>
        <RouterLink to="/review">用例评审</RouterLink>
        <RouterLink to="/upload">知识库上传</RouterLink>
        <RouterLink to="/analyser">PRD 分析</RouterLink>
        <RouterLink to="/api-case-generate">接口用例生成</RouterLink>
        <RouterLink to="/ui-automation">UI 自动化管理</RouterLink>
        <RouterLink to="/knowledge">知识库管理</RouterLink>
      </nav>
    </aside>
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { RouterLink, RouterView } from 'vue-router';

const themes = ['light', 'dark'];
const themeNameMap = {
  light: '白色',
  dark: '黑色'
};
const themeIconMap = {
  light: '☀️',
  dark: '🌙'
};
const currentTheme = ref('light');
const themeLabel = computed(() => themeNameMap[currentTheme.value]);
const themeIcon = computed(() => themeIconMap[currentTheme.value]);

function normalizeTheme(value) {
  return themes.includes(value) ? value : 'light';
}

function applyTheme(value) {
  const nextTheme = normalizeTheme(value);
  if (nextTheme === 'light') {
    document.documentElement.removeAttribute('data-theme');
  } else {
    document.documentElement.setAttribute('data-theme', nextTheme);
  }
  currentTheme.value = nextTheme;
  localStorage.setItem('theme', nextTheme);
}

function toggleTheme() {
  const next = currentTheme.value === 'light' ? 'dark' : 'light';
  applyTheme(next);
}

onMounted(() => {
  const saved = localStorage.getItem('theme') || 'light';
  applyTheme(saved);
});
</script>
