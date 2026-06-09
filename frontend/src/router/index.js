import { createRouter, createWebHistory } from 'vue-router';
import Dashboard from '../pages/Dashboard.vue';
import Generate from '../pages/Generate.vue';
import Review from '../pages/Review.vue';
import CaseReviewDetail from '../pages/CaseReviewDetail.vue';
import Knowledge from '../pages/Knowledge.vue';
import Upload from '../pages/Upload.vue';
import Analyser from '../pages/Analyser.vue';
import ApiCaseGenerate from '../pages/ApiCaseGenerate.vue';
import PlaneGenerate from '../pages/PlaneGenerate.vue';
import UiAutomationManage from '../pages/UiAutomationManage.vue';

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard },
  { path: '/generate', name: 'generate', component: Generate },
  { path: '/plane-generate', name: 'plane-generate', component: PlaneGenerate },
  { path: '/review', name: 'review', component: Review },
  { path: '/review/:id', name: 'review-detail', component: CaseReviewDetail, props: true },
  { path: '/knowledge', name: 'knowledge', component: Knowledge },
  { path: '/upload', name: 'upload', component: Upload },
  { path: '/analyser', name: 'analyser', component: Analyser },
  { path: '/api-case-generate', name: 'api-case-generate', component: ApiCaseGenerate },
  { path: '/ui-automation', name: 'ui-automation', component: UiAutomationManage }
];

export default createRouter({
  history: createWebHistory(),
  routes
});
