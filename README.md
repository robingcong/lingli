# 灵例 (LingLi)

一个基于大模型的智能测试用例生成与评审平台，支持知识库管理、向量检索与结构化 RAG 上下文注入。
- 前端：Vue 3 + Vite (SPA)
- 后端：Django (RESTful API)
- RAG / Prompt 编排：Milvus + BGE-M3 + LangChain Prompt / Message 组件

## 主要功能

- 多模型支持：DeepSeek / 通义千问等
- 用例生成：基于需求描述生成测试用例，并结合知识库证据增强生成质量
- 用例评审：AI 辅助评审与状态管理，支持批量评审加速生成链路
- 知识库管理：文档导入、向量化存储、混合检索与结构化 RAG 上下文构建
- 接口用例生成：上传 API 定义 JSON 自动生成用例
- 主题切换：前端支持主题配色切换

## 前后端结构

```
project/
├─ apps/                 # Django 应用
├─ config/               # Django 配置
├─ utils/                # 工具
├─ frontend/             # Vue 3 + Vite 前端
│  ├─ src/
│  ├─ index.html
│  └─ package.json
├─ manage.py
└─ requirements.txt
```

## 快速开始

### 1. 后端（Django）

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip setuptools wheel
pip install -r requirements.txt
python manage.py migrate
```

在环境变量或 `settings.py` 对应配置中设置模型密钥（示例）：

```plaintext
DEEPSEEK_API_KEY=""
QWEN_API_KEY=""
```

Milvus 连接配置（示例）：

```plaintext
ENABLE_MILVUS=true
MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
MILVUS_COLLECTION=vv_rag_markdown_chunks
```

启动后端：

```bash
python manage.py runserver
```

默认地址：`http://127.0.0.1:8000/`

### 2. 前端（Vue 3 + Vite）

```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://127.0.0.1:5173/`

> Vite 已配置代理，开发环境请求会自动转发到 `http://127.0.0.1:8000`。

## 用例生成说明（已更新）

- 用例生成页面**不显示**：生成数量 / 用例设计方法 / 用例类型
- 后端默认：
  - 生成数量：100（最多）
  - 设计方法：等价类划分 / 边界值分析 / 判定表 / 因果图 / 正交分析 / 场景法
  - 用例类型：功能 / 性能 / 兼容性 / 安全
- 前端默认模型：**通义千问**（若可用）

## RAG 与评审机制

- 知识库文档上传后会切分为多个 chunk，生成 embedding，并写入 Milvus 集合 `vv_rag_markdown_chunks`
- 检索阶段采用“向量召回 + BM25 混合重排”
- 检索命中的 chunk 不再直接裸拼 prompt，而是会经过去重、限长、引用编号等处理，组装成结构化 RAG 上下文
- 测试用例生成时会把这些证据块注入 prompt，优先吸收业务术语、状态流转、约束规则、边界条件与异常处理
- 用例质量评审已改为“批量评审优先，单条评审回退”，能显著减少生成过程中的大模型调用次数

当前生成链路可以简化理解为：

```text
需求输入
  -> 知识库检索
  -> 混合重排
  -> 上下文压缩 / 引用构建
  -> 用例生成
  -> 批量 AI 评审
  -> 结果去重与筛选
```

## 主题切换

左侧导航处提供主题切换按钮，可在默认/海洋/暖阳三种主题中切换。

## 系统要求

- Python 3.12.x
- Django 5.1.x
- Milvus 2.3.x（独立部署）
- MySQL

## Milvus 版本说明

项目默认使用 `pymilvus` 连接独立 Milvus：
- Milvus 2.3.x 使用 `pymilvus 2.3.x`
- 若切换为 milvus-lite，需要调整依赖版本及连接配置

## 常见安装问题（Windows）

如果出现：

`Microsoft Visual C++ 14.0 or greater is required`

