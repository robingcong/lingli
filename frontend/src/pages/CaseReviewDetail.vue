<template>
  <div>
    <div class="card">
      <h2>用例详情</h2>
      <div v-if="loading" class="notice">加载中...</div>
      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-if="testCase" class="form-grid">
        <div>
          <label>编号</label>
          <input :value="testCase.id" disabled />
        </div>
        <div>
          <label>状态</label>
          <select v-model="testCase.status">
            <option value="pending">待评审</option>
            <option value="approved">已通过</option>
            <option value="rejected">未通过</option>
          </select>
        </div>
      </div>
      <div v-if="testCase" style="margin-top: 12px;">
        <label>描述</label>
        <textarea v-model="testCase.description"></textarea>
      </div>
      <div v-if="testCase" class="form-grid" style="margin-top: 12px;">
        <div>
          <label>测试步骤</label>
          <textarea v-model="testCase.test_steps"></textarea>
        </div>
        <div>
          <label>预期结果</label>
          <textarea v-model="testCase.expected_results"></textarea>
        </div>
      </div>
      <div class="flex" style="margin-top: 12px;" v-if="testCase">
        <button @click="save" :disabled="saving">保存</button>
        <button class="secondary" @click="runReview" :disabled="reviewing">AI 评审</button>
        <span v-if="message" class="notice">{{ message }}</span>
      </div>
    </div>

    <div class="card" v-if="reviewResult">
      <h2>AI 评审结果</h2>
      <div v-if="parsedReview" class="form-grid" style="margin-bottom: 12px;">
        <div>
          <label>评分</label>
          <div class="badge">{{ parsedReview.score ?? '-' }}</div>
        </div>
        <div>
          <label>结论</label>
          <div class="badge" :class="parsedReview.recommendation === '通过' ? 'status-approved' : 'status-rejected'">
            {{ parsedReview.recommendation || '未知' }}
          </div>
        </div>
      </div>

      <div v-if="parsedReview" class="form-grid">
        <div>
          <label>优点</label>
          <ul>
            <li v-for="(item, idx) in parsedReview.strengths || []" :key="`s-${idx}`">{{ item }}</li>
          </ul>
        </div>
        <div>
          <label>不足</label>
          <ul>
            <li v-for="(item, idx) in parsedReview.weaknesses || []" :key="`w-${idx}`">{{ item }}</li>
          </ul>
        </div>
      </div>

      <div v-if="parsedReview" class="form-grid" style="margin-top: 12px;">
        <div>
          <label>改进建议</label>
          <ul>
            <li v-for="(item, idx) in parsedReview.suggestions || []" :key="`g-${idx}`">{{ item }}</li>
          </ul>
        </div>
        <div>
          <label>缺失场景</label>
          <ul>
            <li v-for="(item, idx) in parsedReview.missing_scenarios || []" :key="`m-${idx}`">{{ item }}</li>
          </ul>
        </div>
      </div>

      <div v-if="parsedReview" style="margin-top: 12px;">
        <label>评审意见</label>
        <div class="notice">{{ parsedReview.comments || '-' }}</div>
      </div>

      <div v-if="!parsedReview">
        <pre>{{ reviewResult }}</pre>
      </div>
    </div>

    <div class="card" v-if="testCase">
      <h2>UI 冒烟自动化</h2>
      <div class="form-grid">
        <div>
          <label>Base URL</label>
          <input v-model="automationBaseUrl" />
        </div>
        <div>
          <label>登录信息</label>
          <label class="check-line">
            <input type="checkbox" v-model="automationLoginEnabled" />
            <span>执行前登录</span>
          </label>
        </div>
        <div>
          <label>人工确认</label>
          <label class="check-line">
            <input type="checkbox" v-model="automationConfirmed" />
            <span>脚本已确认</span>
          </label>
        </div>
      </div>
      <div v-if="automationLoginEnabled" class="form-grid login-grid">
        <div>
          <label>登录地址</label>
          <input v-model="automationLoginUrl" placeholder="/login" />
        </div>
        <div>
          <label>账号</label>
          <input v-model="automationLoginUsername" autocomplete="username" />
        </div>
        <div>
          <label>密码</label>
          <input v-model="automationLoginPassword" type="password" autocomplete="current-password" />
        </div>
      </div>
      <div class="flex" style="margin-top: 12px;">
        <button class="secondary" @click="generateAutomationDraft" :disabled="automationRunning">生成 Playwright 草稿</button>
        <button @click="runAutomation" :disabled="automationRunning || !automationScript || !automationConfirmed">执行</button>
        <span v-if="automationMessage" class="notice">{{ automationMessage }}</span>
      </div>
      <div v-if="automationScript" style="margin-top: 12px;">
        <label>Playwright 脚本</label>
        <textarea class="script-area" v-model="automationScript"></textarea>
      </div>
      <div v-if="latestAutomationRun" class="automation-result">
        <div class="result-head">
          <span class="badge" :class="latestAutomationRun.passed ? 'status-approved' : 'status-rejected'">
            {{ latestAutomationRun.passed ? '执行通过' : '执行失败' }}
          </span>
          <span class="muted">{{ latestAutomationRun.runner_type }} | {{ latestAutomationRun.duration_ms }} ms</span>
        </div>
        <div v-if="latestAutomationRun.error_message" class="notice error">{{ latestAutomationRun.error_message }}</div>
        <div v-if="latestAutomationRun.analysis?.category && latestAutomationRun.analysis.category !== 'none'" class="notice">
          {{ latestAutomationRun.analysis.category }}：{{ latestAutomationRun.analysis.reason }}
        </div>
        <pre class="text-block">{{ JSON.stringify(latestAutomationRun.evidence || {}, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { api } from '../api/endpoints';

const props = defineProps({
  id: { type: String, required: true }
});

const loading = ref(false);
const saving = ref(false);
const reviewing = ref(false);
const error = ref('');
const message = ref('');
const testCase = ref(null);
const reviewResult = ref('');
const automationBaseUrl = ref('http://127.0.0.1:5173');
const automationLoginEnabled = ref(false);
const automationLoginUrl = ref('/login');
const automationLoginUsername = ref('');
const automationLoginPassword = ref('');
const automationScript = ref('');
const automationConfirmed = ref(false);
const automationRunning = ref(false);
const automationMessage = ref('');
const latestAutomationRun = ref(null);
const parsedReview = computed(() => {
  if (!reviewResult.value) return null;
  if (typeof reviewResult.value === 'object') return reviewResult.value;
  try {
    return JSON.parse(reviewResult.value);
  } catch (e) {
    return null;
  }
});

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const data = await api.getTestCase(props.id);
    testCase.value = { ...data };
    if (data.ai_review && data.ai_review.raw_result) {
      reviewResult.value = data.ai_review.raw_result;
    }
    latestAutomationRun.value = data.latest_automation_run || null;
    if (latestAutomationRun.value?.script_text) {
      automationScript.value = latestAutomationRun.value.script_text;
    }
    const latestLogin = latestAutomationRun.value?.spec?.test_data?.login;
    if (latestLogin?.enabled) {
      automationLoginEnabled.value = true;
      automationLoginUrl.value = latestLogin.login_url || automationLoginUrl.value;
      automationLoginUsername.value = latestLogin.username || '';
      automationLoginPassword.value = '';
    }
  } catch (e) {
    error.value = e.message || '加载失败。';
  } finally {
    loading.value = false;
  }
}

async function save() {
  if (!testCase.value) return;
  saving.value = true;
  message.value = '';
  try {
    const payload = {
      test_case_id: testCase.value.id,
      status: testCase.value.status,
      description: testCase.value.description,
      test_steps: testCase.value.test_steps,
      expected_results: testCase.value.expected_results
    };
    const data = await api.updateTestCase(payload);
    message.value = data.success ? '保存成功。' : (data.message || '保存失败。');
  } catch (e) {
    message.value = e.message || '保存失败。';
  } finally {
    saving.value = false;
  }
}

async function runReview() {
  if (!testCase.value) return;
  reviewing.value = true;
  try {
    const data = await api.reviewTestCase({ test_case_id: testCase.value.id });
    reviewResult.value = data.review_result || '';
  } catch (e) {
    reviewResult.value = e.message || '评审失败。';
  } finally {
    reviewing.value = false;
  }
}

function buildAutomationPayload(extra = {}) {
  const payload = {
    base_url: automationBaseUrl.value,
    ...extra
  };
  payload.login_info = automationLoginEnabled.value
    ? {
        enabled: true,
        login_url: automationLoginUrl.value,
        username: automationLoginUsername.value,
        password: automationLoginPassword.value
      }
    : { enabled: false };
  return payload;
}

async function generateAutomationDraft() {
  if (!testCase.value) return;
  automationRunning.value = true;
  automationMessage.value = '';
  try {
    const data = await api.generateAutomationScript(testCase.value.id, buildAutomationPayload());
    automationScript.value = data.script_text || '';
    latestAutomationRun.value = data.latest_run || latestAutomationRun.value;
    automationConfirmed.value = false;
    automationMessage.value = data.success ? '草稿已生成。' : (data.message || '生成失败。');
  } catch (e) {
    automationMessage.value = e.message || '生成失败。';
  } finally {
    automationRunning.value = false;
  }
}

async function runAutomation() {
  if (!testCase.value || !automationScript.value || !automationConfirmed.value) return;
  automationRunning.value = true;
  automationMessage.value = '';
  try {
    const data = await api.runTestCaseAutomation(testCase.value.id, buildAutomationPayload({
      script_text: automationScript.value,
      confirmed: true
    }));
    latestAutomationRun.value = data.run || null;
    automationMessage.value = latestAutomationRun.value?.passed ? '执行通过。' : '执行完成，存在失败。';
  } catch (e) {
    automationMessage.value = e.message || '执行失败。';
  } finally {
    automationRunning.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.check-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
}

.check-line input {
  width: auto;
}

.login-grid {
  margin-top: 12px;
}

.script-area {
  min-height: 280px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.automation-result {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.result-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.muted {
  color: var(--muted);
  font-size: 12px;
}

.text-block {
  background: var(--panel-soft);
  border-radius: 8px;
  padding: 10px;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
}
</style>
