# 接口文档

本文档整理当前系统对外 HTTP 接口（基于 `config/urls.py`、`apps/core/urls.py`、`apps/core/views.py`、`apps/core/views_sse.py`）。

## 基础信息
- Base: `/`
- 管理后台: `/admin/`

## 页面路由

### GET `/`
- 处理函数: `index`
- 说明: 首页

### GET/POST `/generate/`
- 处理函数: `generate`
- 说明: 测试用例生成页面；POST 接收需求并生成用例

### GET `/review/`
- 处理函数: `review_view`
- 说明: 用例评审页面

### GET `/knowledge/`
- 处理函数: `knowledge_view`
- 说明: 知识库管理页面

### GET `/case-review-detail/`
- 处理函数: `case_review_detail`
- 说明: 用例评审详情页面

### GET/POST `/upload/`
- 处理函数: `upload_single_file`
- 说明: 知识库文件上传页面与上传处理

### GET/POST `/analyser/`
- 处理函数: `prd_analyser`
- 说明: PRD 分析页面与上传处理

### GET/POST `/api_case_generate/`
- 处理函数: `api_case_generate`
- 说明: 接口用例生成页面；POST 支持 JSON 文件上传或触发生成

### GET `/download_file/`
- 处理函数: `download_file`
- 说明: 文件下载

## API 路由

### GET `/api/copy-test-cases/`
- 处理函数: `copy_test_cases`
- 说明: 复制选中的用例集合
- 查询参数: `ids` (逗号分隔)
- 请求示例:
```http
GET /api/copy-test-cases/?ids=1,2,3
```
- 响应示例:
```json
{
  "success": true,
  "test_cases": [
    {
      "id": 1,
      "title": "测试用例-1",
      "description": "用例描述",
      "test_steps": "步骤1\n步骤2",
      "expected_results": "结果1\n结果2",
      "status": "pending",
      "requirements": "需求文本",
      "llm_provider": "deepseek"
    }
  ]
}
```

### GET `/api/export-test-cases-excel/`
- 处理函数: `export_test_cases_excel`
- 说明: 导出用例集合为 Excel
- 查询参数: `ids` (逗号分隔)
- 请求示例:
```http
GET /api/export-test-cases-excel/?ids=1,2,3
```
- 响应示例:
```http
200 OK
Content-Type: application/vnd.ms-excel
Content-Disposition: attachment; filename="test_cases_20240319_153021_3_cases.xls"
```

### GET `/api/test-case/<int:test_case_id>/`
- 处理函数: `get_test_case`
- 说明: 获取单个测试用例
- 请求示例:
```http
GET /api/test-case/42/
```
- 响应示例:
```json
{
  "id": 42,
  "description": "用例描述",
  "test_steps": "步骤1\n步骤2",
  "expected_results": "结果1\n结果2",
  "status": "pending"
}
```

### GET `/api/test-cases/<str:test_case_ids>/`
- 处理函数: `get_test_cases`
- 说明: 获取多个测试用例
- 路径参数: `test_case_ids` (逗号分隔)
- 请求示例:
```http
GET /api/test-cases/1,2,3/
```
- 响应示例:
```json
{
  "success": true,
  "test_cases": [
    {
      "id": 1,
      "title": "测试用例-1",
      "description": "用例描述",
      "test_steps": "步骤1\n步骤2",
      "expected_results": "结果1\n结果2",
      "status": "pending",
      "requirements": "需求文本",
      "llm_provider": "deepseek"
    }
  ]
}
```

### POST `/api/update-test-case/`
- 处理函数: `update_test_case`
- 说明: 更新单个测试用例状态与内容
- 请求体(JSON): `test_case_id`, `status`, `description`, `test_steps`, `expected_results`
- 请求示例:
```http
POST /api/update-test-case/
Content-Type: application/json

{
  "test_case_id": 42,
  "status": "approved",
  "description": "更新后的描述",
  "test_steps": "步骤1\n步骤2",
  "expected_results": "结果1\n结果2"
}
```
- 响应示例:
```json
{
  "success": true
}
```

### POST `/core/save-test-case/`
- 处理函数: `save_test_case`
- 说明: 批量保存大模型生成的测试用例
- 请求体(JSON): `requirement`, `test_cases`, `llm_provider`
- 请求示例:
```http
POST /core/save-test-case/
Content-Type: application/json

{
  "requirement": "需求文本",
  "llm_provider": "deepseek",
  "test_cases": [
    {
      "description": "用例描述",
      "test_steps": ["步骤1", "步骤2"],
      "expected_results": ["结果1", "结果2"]
    }
  ]
}
```
- 响应示例:
```json
{
  "success": true,
  "message": "成功保存 1 条测试用例",
  "test_case_id": [101]
}
```

### POST `/api/review/`
- 处理函数: `case_review`
- 说明: AI 评审单个测试用例
- 请求体(JSON): `test_case_id`
- 请求示例:
```http
POST /api/review/
Content-Type: application/json

{
  "test_case_id": 42
}
```
- 响应示例:
```json
{
  "success": true,
  "review_result": "评审结论文本"
}
```

### POST `/api/add-knowledge/`
- 处理函数: `add_knowledge`
- 说明: 添加知识条目
- 请求体(JSON): `title`, `content`
- 请求示例:
```http
POST /api/add-knowledge/
Content-Type: application/json

{
  "title": "标题",
  "content": "知识内容"
}
```
- 响应示例:
```json
{
  "success": true,
  "message": "知识条目添加成功",
  "knowledge_id": 12
}
```

### GET `/api/knowledge-list/`
- 处理函数: `knowledge_list`
- 说明: 获取知识库列表
- 请求示例:
```http
GET /api/knowledge-list/
```
- 响应示例:
```json
{
  "success": true,
  "knowledge_items": [
    {
      "id": 12,
      "title": "标题",
      "content": "内容",
      "created_at": "2024-03-19T12:34:56"
    }
  ]
}
```

### POST `/api/search-knowledge/`
- 处理函数: `search_knowledge`
- 说明: 搜索知识库
- 请求体(JSON): `query`
- 请求示例:
```http
POST /api/search-knowledge/
Content-Type: application/json

{
  "query": "检索关键词"
}
```
- 响应示例:
```json
{
  "success": true,
  "results": "匹配的知识条目文本或摘要"
}
```

### DELETE `/api/delete-test-cases/`
- 处理函数: `delete_test_cases`
- 说明: 删除选中的测试用例
- 查询参数: `ids` (逗号分隔)
- 请求示例:
```http
DELETE /api/delete-test-cases/?ids=1,2,3
```
- 响应示例:
```json
{
  "success": true,
  "message": "成功删除 3 条测试用例"
}
```

### GET `/api/get-generation-progress/`
- 处理函数: `get_generation_progress_api`
- 说明: 获取生成进度
- 查询参数: `task_id`
- 请求示例:
```http
GET /api/get-generation-progress/?task_id=task_1710840000000_anon
```
- 响应示例:
```json
{
  "success": true,
  "progress": {
    "task_id": "task_1710840000000_anon",
    "status": "running",
    "percent": 35,
    "message": "正在生成用例",
    "updated_at": 1710840000
  }
}
```

### GET `/api/testcase-rule-template/`
- 处理函数: `get_testcase_rule_template`
- 说明: 获取规则模板文本
- 请求示例:
```http
GET /api/testcase-rule-template/
```
- 响应示例:
```json
{
  "success": true,
  "rule_text": "## 测试用例生成规则\n..."
}
```

### GET `/api/stream-logs/`
- 处理函数: `stream_logs`
- 说明: SSE 日志流
- 查询参数: `task_id`
- 请求示例:
```http
GET /api/stream-logs/?task_id=task_1710840000000_anon
Accept: text/event-stream
```
- 响应示例:
```text
event: log
data: {"seq":1,"ts":1710840000,"level":"info","msg":"开始生成","task_id":"task_1710840000000_anon"}

event: progress
data: {"ts":1710840005}
```

