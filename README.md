# AI Agent 系统

基于 RAG（检索增强生成）和 LangGraph 的智能 AI Agent 系统。

## 📋 目录

- [功能特性](#功能特性)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [API 文档](#api-文档)
- [开发指南](#开发指南)
- [常见问题](#常见问题)

---

## ✨ 功能特性

### 第1周：AI 工程化基础
- ✅ FastAPI 服务搭建
- ✅ LLM API 集成（DeepSeek/OpenAI）
- ✅ Docker 容器化部署

### 第2周：Function Calling
- ✅ 工具调用（天气查询、数学计算）
- ✅ Agent 框架封装
- ✅ 多工具协同

### 第3周：向量数据库
- ✅ 文本向量化（BGE 模型）
- ✅ ChromaDB 向量存储
- ✅ 相似度检索

### 第4周：PDF 知识库
- ✅ PDF 上传与解析
- ✅ 文本智能切分
- ✅ RAG 问答系统
- ✅ Web 可视化界面
- ✅ 异步任务处理

### 第5周：RAG 质量提升
- ✅ 混合检索（向量 + BM25）
- ✅ Rerank 重排序
- ✅ HyDE 查询扩展
- ✅ Redis 缓存
- ✅ 评估体系

### 第6周：对话系统-待完善
- ✅ 会话管理
- ✅ 多轮对话上下文
- ✅ 对话历史存储
- ✅ 对话压缩

### 第7周：LangGraph Agent-待完善
- ✅ StateGraph 状态机
- ✅ Agent 工作流编排
- ✅ 多步骤推理
- ✅ 可观测性

### 第8周：系统整合-待完善
- ✅ 统一 Agent 入口
- ✅ 知识库 + 工具 + 对话整合
- ✅ 流式输出
- ✅ 完整项目交付

---

## 🏗 技术架构
┌─────────────────────────────────────────────────────────────┐
│ 前端界面 (Web) │
│ HTML/CSS/JavaScript │
└─────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI 后端服务 │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐ │
│ │ Agent │ │ RAG Chain │ │ Session Manager │ │
│ │ 统一入口 │ │ 问答链 │ │ 会话管理 │ │
│ └──────┬──────┘ └──────┬──────┘ └──────────┬──────────┘ │
│ │ │ │ │
│ ┌──────▼────────────────▼────────────────────▼──────────┐ │
│ │ LLM Client │ │
│ │ (DeepSeek / OpenAI API) │ │
│ └──────────────────────┬─────────────────────────────────┘ │
│ │ │ │ │
│ ┌──────▼──────┐ ┌──────▼──────┐ ┌──────────▼──────────┐ │
│ │ Tools │ │ Vector │ │ Task Manager │ │
│ │ 工具集 │ │ Store │ │ 任务管理 │ │
│ └────────────┘ └────────────┘ └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ 数据层 │
│ ┌────────────┐ ┌────────────┐ ┌────────────────────┐ │
│ │ ChromaDB │ │ Redis │ │ Local Files │ │
│ │ 向量库 │ │ 缓存 │ │ 本地文件 │ │
│ └────────────┘ └────────────┘ └────────────────────┘ │
└─────────────────────────────────────────────────────────────┘


---

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Docker & Docker Compose（可选）

### 本地运行

```bash
# 1. 克隆项目
git clone https://github.com/yourname/ai-agent-system.git
cd ai-agent-system

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 5. 启动服务
python run.py

# 6. 访问服务
# 前端界面: http://localhost:8000
# API 文档: http://localhost:8000/docs

### Docker 运行
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 2. 启动所有服务
docker-compose up -d

# 3. 查看日志
docker-compose logs -f api

# 4. 停止服务
docker-compose down

### 项目结构
ai-agent-system/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 主应用
│   ├── config.py            # 配置管理
│   ├── logger.py            # 日志模块
│   ├── models.py            # 数据模型
│   │
│   ├── llm_client.py        # LLM 客户端
│   ├── tools.py             # 工具集
│   ├── agent_unified.py     # 统一 Agent 入口
│   │
│   ├── embeddings.py        # 向量化模型
│   ├── vector_store.py      # 向量数据库
│   ├── document_processor.py # PDF 处理器
│   ├── knowledge_base.py    # 知识库管理
│   ├── rag_chain.py         # RAG 问答链
│   │
│   ├── hybrid_search.py     # 混合检索
│   ├── reranker.py          # 重排序
│   ├── hyde.py              # HyDE 查询扩展
│   ├── cache_manager.py     # 缓存管理
│   │
│   ├── session_manager.py   # 会话管理
│   ├── context_compressor.py # 上下文压缩
│   ├── task_manager.py      # 任务管理
│   │
│   └── langgraph_agent.py   # LangGraph Agent
│
├── web/
│   └── index.html           # 前端界面
│
├── chroma_data/             # 向量数据持久化
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── run.py
├── .env.example
└── README.md