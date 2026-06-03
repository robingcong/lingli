<template>
  <div>
    <div class="card">
      <h2>用例生成</h2>
      <div class="form-grid">
        <div>
          <label>模型选择</label>
          <select v-model="form.llm_provider">
            <option v-for="p in providers" :key="p.key" :value="p.key">
              {{ p.name }}
            </option>
          </select>
        </div>
      </div>

      <div class="preference-panel">
        <div class="preference-header">
          <div>
            <h3>生成偏向</h3>
            <p>默认强化功能点拆分，让 case 覆盖更多入口、交互、状态和数据变化。</p>
          </div>
          <span class="badge">个性化</span>
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

      <div style="margin-top: 12px;">
        <label>需求描述</label>
        <textarea v-model="form.requirements" placeholder="请输入需求描述"></textarea>
      </div>

      <div class="flex" style="margin-top: 12px;">
        <button @click="generate" :disabled="loading">提交后台生成</button>
        <button class="secondary" @click="reset" :disabled="loading">重置</button>
      </div>

      <div v-if="loading" class="notice">正在提交后台任务...</div>
      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-if="submitMessage" class="notice">{{ submitMessage }}</div>
    </div>

    <GenerationJobs ref="jobsRef" />

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
        <button @click="save" :disabled="saving">保存到数据库</button>
        <span v-if="saveMessage" class="notice">{{ saveMessage }}</span>
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
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const saveMessage = ref('');
const submitMessage = ref('');
const testCases = ref([]);
const jobsRef = ref(null);

const form = reactive({
  llm_provider: 'deepseek',
  requirements: '',
  case_design_methods: [],
  case_categories: ['functional'],
  case_count: 0,
  ...buildDefaultGenerationPreferences()
});

const designMethods = [
  { value: 'equivalence_partitioning', label: '等价类划分' },
  { value: 'boundary_value', label: '边界值分析' },
  { value: 'decision_table', label: '判定表' },
  { value: 'cause_effect', label: '因果图' },
  { value: 'orthogonal_array', label: '正交分析' },
  { value: 'scenario', label: '场景法' }
];

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

onMounted(async () => {
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
});

async function generate() {
  error.value = '';
  saveMessage.value = '';
  submitMessage.value = '';
  if (!form.requirements.trim()) {
    error.value = '需求描述不能为空。';
    return;
  }
  if (!form.case_categories.length) {
    error.value = '请至少选择一种测试类型。';
    return;
  }
  loading.value = true;
  try {
    const data = await api.createGenerationJob({
      source_type: 'requirement',
      source_title: form.requirements.trim().split('\n')[0].slice(0, 80),
      requirements: form.requirements,
      llm_provider: form.llm_provider,
      case_design_methods: mapLabels(designMethods.map((m) => m.value), designMethods),
      case_categories: mapLabels(form.case_categories, caseCategories),
      case_count: form.case_count,
      generation_profile: form.generation_profile,
      focus_points: form.focus_points,
      focus_strength: form.focus_strength
    });
    testCases.value = [];
    submitMessage.value = data.message || `任务 #${data.job_id} 已提交后台生成。`;
    await jobsRef.value?.loadJobs?.();
  } catch (e) {
    error.value = e.message || '提交后台任务失败。';
  } finally {
    loading.value = false;
  }
}

async function save() {
  if (!testCases.value.length) return;
  saving.value = true;
  saveMessage.value = '';
  try {
    const data = await api.saveCases({
      requirement: form.requirements,
      test_cases: testCases.value,
      llm_provider: form.llm_provider
    });
    saveMessage.value = data.message || '保存成功。';
  } catch (e) {
    saveMessage.value = e.message || '保存失败。';
  } finally {
    saving.value = false;
  }
}

function reset() {
  form.requirements = '';
  form.case_design_methods = [];
  form.case_categories = ['functional'];
  form.case_count = 0;
  Object.assign(form, buildDefaultGenerationPreferences());
  testCases.value = [];
  error.value = '';
  saveMessage.value = '';
  submitMessage.value = '';
}
</script>
