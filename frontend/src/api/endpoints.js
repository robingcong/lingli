import { apiGet, apiPostJson, apiPostForm, apiDelete } from './client';

export const api = {
  getDashboard: () => apiGet('/api/dashboard/'),
  getProviders: () => apiGet('/api/llm-providers/'),
  generateCases: (payload) => apiPostJson('/generate/', payload),
  saveCases: (payload) => apiPostJson('/core/save-test-case/', payload),

  listTestCases: (status, page = 1, pageSize = 15) =>
    apiGet(`/api/test-cases-list/?status=${encodeURIComponent(status)}&page=${page}&page_size=${pageSize}`),
  getTestCase: (id) => apiGet(`/api/test-case/${id}/`),
  updateTestCase: (payload) => apiPostJson('/api/update-test-case/', payload),
  updateStatus: (payload) => apiPostJson('/api/update-status/', payload),
  reviewTestCase: (payload) => apiPostJson('/api/review/', payload),
  copyTestCases: (ids) => apiGet(`/api/copy-test-cases/?ids=${encodeURIComponent(ids.join(','))}`),
  deleteTestCases: (ids) => apiDelete(`/api/delete-test-cases/?ids=${encodeURIComponent(ids.join(','))}`),

  listKnowledge: () => apiGet('/api/knowledge-list/'),
  listKnowledgeLibrary: () => apiGet('/api/knowledge-library/'),
  getKnowledgeLibraryDetail: (entryId) =>
    apiGet(`/api/knowledge-library/detail/?entry_id=${encodeURIComponent(entryId)}`),
  addKnowledge: (payload) => apiPostJson('/api/add-knowledge/', payload),
  searchKnowledge: (payload) => apiPostJson('/api/search-knowledge/', payload),

  uploadKnowledgeFile: (formData) => apiPostForm('/upload/', formData),
  analysePrd: (formData) => apiPostForm('/analyser/', formData),
  listPrdAnalyses: () => apiGet('/api/prd-analyses/'),
  getPrdAnalysisDetail: (id) => apiGet(`/api/prd-analyses/${id}/`),
  deletePrdAnalysis: (id) => apiDelete(`/api/prd-analyses/${id}/`),

  uploadApiDefinition: (formData) => apiPostForm('/api_case_generate/', formData),
  generateApiCases: (formData) => apiPostForm('/api_case_generate/', formData),
  listApiSchemaFiles: () => apiGet('/api/api-schema-files/'),
  getApiSchemaFileDetail: (id) => apiGet(`/api/api-schema-files/${id}/`),
  listApiCaseGenerations: () => apiGet('/api/api-case-generations/'),
  getApiCaseGenerationDetail: (id) => apiGet(`/api/api-case-generations/${id}/`),
  getRuleTemplate: () => apiGet('/api/testcase-rule-template/'),

  refreshPlaneWorkItems: (payload) => apiPostJson('/api/plane-work-items/', payload),
  listPlaneWorkItems: ({ page = 1, pageSize = 20, keyword = '', projectId = '' } = {}) =>
    apiGet(
      `/api/plane-work-items/?page=${page}&page_size=${pageSize}&keyword=${encodeURIComponent(keyword)}&project_id=${encodeURIComponent(projectId)}`
    ),
  planeOneClickGenerate: (payload) => apiPostJson('/api/plane-one-click-generate/', payload)
};
