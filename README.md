# 🏢 一站式智能 AI Agent 系统 (企业版 v2.1)

基于 **FastAPI + RAG 检索增强生成 + LangGraph** 搭建的一站式智能 AI Agent 系统。集成知识库问答、工具调用、多轮对话、工作流编排、质量评估、JWT 认证、多租户隔离（用户-租户 RBAC）、多 Agent 协作、Prometheus 监控等企业级能力，支持本地运行与 Docker 全栈容器化部署。

---

##  目录
- [核心功能](#-核心功能)
- [技术架构](#-技术架构)
- [快速开始](#-快速开始)
- [项目结构](#-项目结构)
- [核心模块说明](#-核心模块说明)
- [API 文档](#-api-文档)
- [开发进度](#-开发进度)
- [常见问题](#-常见问题)

---

## 核心功能

系统覆盖 LLM 调用、工具智能编排、RAG 高质量问答、多轮对话、Agent 工作流全场景，核心能力如下：

- **基础服务能力**：FastAPI 高性能接口、日志管理、环境配置、Docker 容器化部署
- **企业安全**：JWT 认证鉴权、API 限流保护、多租户 RBAC（用户-租户关联 + 知识库隔离 + 默认共享租户）
- **通用工具调用**：内置天气查询、数学计算等工具，支持多工具协同调用
- **企业级 RAG 知识库**：PDF 上传解析、智能分块、向量化存储、多路检索、结果优化
- **高质量检索体系**：向量检索 + BM25 混合检索、Cross-Encoder 重排、MMR 多样性去重、HyDE 语义增强、Redis 缓存加速
- **高级 RAG 技术**：父文档检索、自查询检索（LLM 自动提取过滤条件）、多模态 OCR、RAGAS 质量评估
- **多轮对话系统**：会话管理、上下文记忆、对话压缩、历史记录持久化
- **智能 Agent 编排**：基于 LangGraph 状态机，实现多步骤推理、任务编排、可观测工作流
- **多 Agent 协作**：Supervisor 调度模式（Researcher + Analyst + Executor），Human-in-the-loop 审批
- **异步任务**：Celery 任务队列 + Flower 监控面板，PDF 处理异步化、自动重试
- **量化评估体系**：支持 HitRate、MRR、NDCG 等检索指标评估；RAGAS 上下文相关性/忠实度/回答相关性
- **可观测性**：Prometheus 指标暴露、Grafana 可视化仪表盘、结构化日志
- **可视化交互**：内置 Web 前端界面（支持租户登录/知识库管理）+ Streamlit 企业面板（4模式：Chat/KB搜索/多Agent/RAGAS评估）
- **压力测试**：Locust 多用户画像压测脚本

---

##  技术架构

采用分层解耦架构，从上至下分为前端交互层、API 服务层、核心业务层、数据存储层，模块独立可插拔，易于扩展迭代。

```text
┌─────────────────────────────────────────────────────────────┐
│  负载均衡 / API Gateway（限流 / 认证）                       │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│  前端界面层 (Web 可视化页面 + Streamlit 企业面板)            │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│  FastAPI 后端服务层（统一接口、路由、异常处理、中间件）        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ JWT 认证 │ │ API 限流 │ │ 多租户   │ │ Prometheus   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  核心业务模块层                                              │
│  ┌─────────────┐ ┌──────────┐ ┌────────────┐ ┌──────────┐  │
│  │统一Agent入口│ │RAG V2链路│ │多Agent编排 │ │会话管理  │  │
│  └──────┬──────┘ └────┬─────┘ └─────┬──────┘ └────┬─────┘  │
│         │              │             │              │        │
│  ┌──────▼──────────────▼─────────────▼──────────────▼─────┐  │
│  │ LLM 通用客户端（DeepSeek/OpenAI 兼容）                 │  │
│  └──────────────────────┬─────────────────────────────────┘  │
│         │                │                │                  │
│  ┌──────▼──────┐ ┌──────▼──────┐ ┌───────▼──────────┐      │
│  │ 工具调用集   │ │ 向量检索引擎│ │ 异步任务(Celery) │      │
│  └─────────────┘ └─────────────┘ └──────────────────┘      │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│  数据存储层                                                  │
│  ChromaDB(向量) / Redis(缓存+队列) / PostgreSQL(租户/用户/会话) │
│  Prometheus(监控) / Grafana(仪表盘) / Flower(任务面板)      │
└─────────────────────────────────────────────────────────────┘
```

---

##  快速开始

### 环境要求
- Python 3.11+
- 可选：Docker & Docker Compose（容器部署）

### 本地开发运行

```bash
# 1. 克隆项目
git clone https://github.com/yourname/ai-agent-system.git
cd ai-agent-system

# 2. 创建并激活虚拟环境
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 3. 安装项目依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的 LLM_API_KEY 等密钥

# 5. 启动项目服务
python run.py

# 6. 初始化数据库（租户/用户种子数据）
python scripts/init_db.py

# 7. 访问服务
# 前端可视化页面：http://localhost:8000
# 自动生成 API 文档：http://localhost:8000/docs
```

### Docker 全栈容器部署

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 配置 LLM_API_KEY、数据库连接等

# 2. 一键启动所有服务（9容器）
bash scripts/start_all.sh

# 或手动启动核心服务
# docker compose up -d redis postgres api celery-worker celery-beat

# 3. 初始化数据库（种子租户/用户）
docker compose exec api python scripts/init_db.py

# 4. 查看运行日志
docker compose logs -f api

# 5. 停止服务
docker compose down
```

### 服务端口一览

| 服务 | 端口 | 说明 |
|------|------|------|
| FastAPI | 8000 | 主 API 服务 + Web 前端 |
| Streamlit | 8501 | 企业级前端面板 |
| Flower | 5555 | Celery 任务监控 |
| Prometheus | 9090 | 指标收集 |
| Grafana | 3000 | 可视化仪表盘 |
| Redis | 6379 | 缓存 + 消息队列 |
| PostgreSQL | 5432 | 会话/租户持久化 |

### 模型本地离线下载

项目支持本地模型离线部署，规避境外网络访问失败、网页解析异常、在线模型加载超时等问题，通过专属脚本一键下载所需向量、重排模型至本地，实现完全离线推理。

```bash
# 执行模型批量下载脚本
python scripts/download_model.py
```

**脚本功能说明：**
- 自动下载项目依赖的 Embedding 向量化模型、Cross-Encoder 重排模型
- 默认保存至项目本地模型目录，全局复用，无需重复联网加载
- 规避 GitHub、境外模型源访问失败、解析失败等网络问题
- 下载完成后自动配置本地模型加载路径，服务启动优先读取本地模型

> **注意事项**：首次下载需保证网络通畅，模型文件较大请耐心等待；下载完成后可完全离线运行项目，不受外网限制。

---

##  项目结构

```text
ai-agent-system/
├── app/                        # 核心业务代码目录
│   ├── main.py                 # FastAPI 服务入口（企业版 v2.0）
│   ├── config.py               # 全局配置管理（12-Factor）
│   ├── logger.py               # 统一日志工具
│   ├── models.py               # 通用数据模型
│   │
│   ├── llm_client.py           # LLM 大模型客户端
│   ├── tools.py                # 智能工具调用集
│   ├── agent_unified.py        # Agent 统一入口（双引擎路由+回退）
│   │
│   ├── embeddings.py           # 文本向量化模型
│   ├── vector_store.py         # ChromaDB 向量库管理
│   ├── document_processor.py   # PDF 文档解析与分块
│   ├── knowledge_base.py       # 知识库核心管理
│   ├── rag_chain.py            # RAG 问答（简化版，向后兼容）
│   ├── rag_chain_v2.py         # RAG V2 增强链路（HyDE+混合检索+重排+MMR）
│   │
│   ├── hybrid_search.py        # BM25+向量混合检索
│   ├── reranker.py             # 结果重排、MMR 多样性筛选
│   ├── hyde.py                 # HyDE 语义查询增强
│   ├── cache_manager.py        # Redis 缓存管理
│   │
│   ├── session_manager.py      # 会话管理（Redis+内存双模式）
│   ├── context_compressor.py   # 上下文压缩优化
│   ├── task_manager.py         # 异步任务管理（内存模式）
│   │
│   ├── evaluator.py            # RAG 质量评估（HitRate/MRR/NDCG）
│   ├── langgraph_agent.py      # LangGraph 工作流 Agent
│   │
│   ├── advanced_rag.py         # [新] 高级RAG（父文档/自查询/多模态/RAGAS）
│   ├── multi_agent.py          # [新] 多Agent协作（Supervisor模式）
│   ├── workflow_tracker.py     # [新] 工作流追踪+重试+可视化
│   ├── monitoring.py           # [新] Prometheus 监控指标
│   ├── celery_app.py           # [新] Celery 异步任务实例
│   ├── tasks.py                # [新] Celery 任务定义（PDF处理/清理）
│   ├── database.py             # [新] PostgreSQL 数据库管理
│   │
│   └── middleware/             # [新] 企业中间件
│       ├── auth.py             #   JWT 认证鉴权
│       ├── rate_limit.py       #   API 限流
│       └── tenant.py           #   多租户隔离
│
├── web/                        # 前端静态资源
│   ├── index.html              #   可视化问答页面
│   └── streamlit_app.py        #   [新] Streamlit 企业面板
│
├── scripts/                    # [新] 运维脚本
│   ├── start_all.sh            #   一键启动全栈服务
│   ├── init_db.py              #   数据库初始化
│   ├── download_model.py       #   模型下载
│   └── txt2pdf.py              #   txt转PDF工具
│
├── tests/                      # [新] 测试脚本
│   ├── data/
│   │   ├── test.pdf            #   测试用PDF
│   │   └── test.txt            #   测试用文本
│   ├── test_smoke.py           #   端到端冒烟测试
│   ├── locustfile.py           #   Locust 压力测试
│   └── test_week*.py           #   各阶段验收测试
│
├── docker-compose.yml          # 容器编排配置（9容器）
├── Dockerfile                  # 项目镜像构建配置
├── prometheus.yml              # [新] Prometheus 采集配置
├── requirements.txt            # 依赖清单
├── run.py                      # 项目启动入口
├── .env.example                # 环境变量模板
└── README.md                   # 项目说明文档
```

---

## 核心模块说明

- **统一 Agent 入口**：`agent_unified.py` — 双引擎自动路由 + 回退：知识库中/高相关 → HyDE+RAG V2；低/弱相关 → LangGraph Agent（原生 function calling）；RAG 无结果 → 自动回退 Agent
- **RAG V2 增强链路**：`rag_chain_v2.py` — HyDE 假设文档嵌入 + 混合检索（向量+BM25+RRF融合）+ CrossEncoder 重排 + MMR 多样性去重 + Redis 缓存
- **高级 RAG**：`advanced_rag.py` — 父文档检索（小chunk检索→大chunk返回）、自查询检索（LLM提取过滤条件）、多模态 OCR、RAGAS 评估
- **LangGraph Agent**：`langgraph_agent.py` — 状态图驱动（think → execute_tool → reflect），原生 function calling，节点级可观测
- **多 Agent 编排**：`multi_agent.py` — Supervisor 调度模式（Researcher+Analyst+Executor），Human-in-the-loop 人工审批
- **混合检索模块**：BM25 关键词检索 + 向量语义检索双路召回，RRF 融合排序，索引自动缓存
- **重排序模块**：优先 CrossEncoder 交叉编码器精准打分，回退 BiEncoder 二次相似度
- **企业中间件**：`middleware/auth.py` JWT 认证 + 登出废止、`middleware/rate_limit.py` 滑动窗口限流（/api/task/ 白名单）、`middleware/tenant.py` 多租户隔离
- **数据库**：`database.py` PostgreSQL 5 表（tenants, users, user_tenants, sessions, tasks），含连接池 + 重试机制
- **异步任务**：`tasks.py` Celery 任务队列（PDF 处理+自动重试）、Flower 监控面板
- **监控**：`monitoring.py` Prometheus 指标（QPS/延迟/工具调用/LLM Token）、Grafana 仪表盘
- **会话管理**：Redis / 内存双模式，历史消息、上下文自动压缩

---

## API 文档

项目基于 FastAPI 自动生成交互式接口文档，服务启动后可直接访问：

- **Swagger 文档**：[http://localhost:8000/docs](http://localhost:8000/docs)
- 支持接口在线调试、参数查看、返回示例展示

### 企业级新增端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tenants` | 获取可用租户列表 |
| POST | `/api/token` | JWT 登录获取令牌（需 tenant_id） |
| POST | `/api/revoke` | 登出废止 Token |
| GET | `/api/me` | 获取当前用户信息（需认证） |
| GET | `/api/kb/documents` | 知识库文档列表（租户隔离） |
| DELETE | `/api/kb/documents/{name}` | 删除指定文档（租户隔离） |
| GET | `/api/metrics` | Prometheus 指标 |
| POST | `/api/multi-agent/run` | 多 Agent 协作 |
| POST | `/api/rag/evaluate` | RAGAS 质量评估 |

### 生产模式认证

设置 `ENV=production` 后，登录需通过数据库验证（users + user_tenants 表），支持 RBAC 租户权限控制。

| 用户 | 密码 | 租户 | 角色 |
|------|------|------|------|
| admin | admin123 | default（共享） | admin |
| demo1 | demo1123 | demo1 | user |
| demo2 | demo2123 | demo2 | user |

- `default` 租户为共享知识库，其他租户均可检索其文档
- 各租户私有文档互不可见
- 开发模式（`ENV=development`）任意用户名密码均可登录

---

## 开发进度

### ✅ v1.0 已完成
- FastAPI 基础服务、日志、配置、容器化部署
- LLM 多模型适配、通用客户端封装（DeepSeek）
- PDF 解析、智能分块、向量入库
- 混合检索（向量+BM25+RRF）、CrossEncoder 重排、MMR 去重
- HyDE 语义增强、Redis 缓存
- 多轮对话、会话管理（Redis+内存双模式）、上下文压缩
- LangGraph Agent（think→execute_tool→reflect）+ 原生 function calling
- 统一 Agent 双引擎路由 + RAG→Agent 回退
- 量化评估（HitRate/MRR/NDCG，基于真实检索）
- Web 可视化前端

### ✅ v2.1 生产就绪（当前）
- JWT 认证 + Token 黑名单 + 登出废止
- 多租户 RBAC（users + user_tenants 表，租户权限控制）
- 默认共享租户（default 文档对所有租户可见）
- Web 前端登录（用户名/密码/租户选择）
- 知识库上传 / 检索 / 文档列表全链路租户隔离
- 同名文件覆盖上传（?force=true）
- 容器时区统一 Asia/Shanghai
- API 限流白名单（/api/task/ 轮询不限流）
- 20 项冒烟测试（含生产认证 + 租户隔离）

### ✅ v2.0 企业级升级（第9-12周）
- JWT 认证鉴权 + Token 黑名单
- API 滑动窗口限流
- 多租户数据隔离（ContextVar）
- Celery 异步任务队列 + Flower 监控
- PostgreSQL 数据库（会话/租户/任务持久化）
- 高级 RAG：父文档检索、自查询检索、多模态 OCR、RAGAS 评估
- 多 Agent 协作：Supervisor 模式 + Human-in-the-loop
- 工作流追踪：步骤计时 + 指数退避重试 + DOT 可视化
- Prometheus 指标 + Grafana 仪表盘
- Streamlit 企业前端（4模式）
- Locust 压力测试（3种用户画像）
- 9容器 Docker Compose 全栈部署

### 🔜 待完善
- 流式输出体验优化
- 模型性能压测与效果对比
- Kubernetes Helm Chart 部署

---

## 常见问题

1. **检索指标偏低**：优化文本分块大小与重叠度、调整混合检索权重、确认知识库已上传文档
2. **接口响应慢**：首次检索包含 LLM 生成耗时；重复问题走 Redis 缓存秒级响应
3. **LLM 调用失败**：检查 `.env` 中 `LLM_API_KEY` 是否正确、网络是否可达
4. **模型加载失败**：确保已运行 `python scripts/download_model.py` 下载本地模型，或检查模型路径
5. **LangGraph 启动报错**：如遇 `MemorySaver` 导入失败，项目已兼容 0.3.x 多版本路径
6. **知识库检索为空**：确认已上传 PDF 文件，查看侧边栏文档数量是否 > 0
7. **认证失败 401**：生产模式需正确密码（admin/admin123 等），开发模式任意密码通过
8. **无权访问租户 403**：用户不属于该租户（通过 user_tenants 表控制）
9. **429 限流**：默认每分钟 60 次请求，可在 `.env` 调整 `API_RATE_LIMIT`；`/api/task/` 内部轮询不限流
10. **Celery Worker 未启动**：异步 PDF 处理需要 `celery -A app.celery_app worker`；开发环境自动回退到同步处理
11. **冒烟测试**：运行 `python tests/test_smoke.py` 验证全链路（需服务已启动）

