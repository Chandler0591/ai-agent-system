# AI Agent System

基于FastAPI + DeepSeek的AI代理系统，支持LLM调用和工具扩展。

## 快速开始

### 前置要求
- Docker & Docker Compose
- Python 3.12+（本地开发）

### 环境配置
1. 复制环境变量模板
\`\`\`bash
cp .env.example .env
\`\`\`

2. 在`.env`中填入你的DeepSeek API Key

### 启动服务
\`\`\`bash
docker-compose up -d
\`\`\`

### 测试接口
\`\`\`bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'
\`\`\`

### API文档
启动后访问 http://localhost:8000/docs

## 项目结构
\`\`\`
.
├── app/
│   ├── main.py          # FastAPI主应用
│   ├── config.py        # 配置管理
│   ├── llm_client.py    # LLM客户端
│   └── logger.py        # 日志模块
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── run.py
\`\`\`

## 技术栈
- FastAPI - Web框架
- DeepSeek API - LLM服务
- Redis - 缓存（后续使用）
- Docker - 容器化
