# 🏭 AI 调度仿真系统

> **[ai-agent-system](https://github.com/Chandler0591/ai-agent-system)** 仿真模块 | `feature/simulation` 分支

基于 **PyBullet + FastAPI + LangGraph Agent** 的仓库调度仿真系统。10m×10m 物理仿真环境，支持 AGV 小车创建/移动/障碍检测，Agent 自然语言控制，2D Canvas 实时可视化。

---

## 🎯 核心功能

```
用户: "把小车 agv_1 移到 B 区"
  ↓
Agent 🧠: 理解意图 → 调用 move_robot("agv_1", zone="B")
  ↓
仿真引擎 ⚙️: 物理计算 → AGV 移动到 (-2.5, 2.5)
  ↓
前端 🗺️: Canvas 2D 实时刷新，小车三角指向 B 区
```

| 能力 | 实现 |
|------|------|
| 物理引擎 | PyBullet DIRECT/GUI 双模式，重力 + 碰撞检测 |
| AGV 管理 | 创建/删除/移动/速度控制，支持 yaw 初始朝向 |
| 场景感知 | 激光雷达模拟 (rayTest)、距离计算、区域判定 |
| REST API | 12 个端点，FastAPI 自动生成 `/docs` |
| Agent 工具 | move_robot / get_robot_status / check_obstacle |
| 可视化 | Canvas 2D 俯瞰（货架/区域/AGV朝向），3秒轮询 |

---

## 🗺️ 仿真场景

```
        北 ↑
    ┌──────────────────────────┐
    │  🟦 B区 (-3.7~-1.3, 1.3~3.7)   🟢 A区 (1.3~3.7, 1.3~3.7) │
    │                              │
    │    🟫 shelf_1     🟫 shelf_0  │
    │    (-3.8~-2.2)    (2.2~3.8)   │  ← 货架 (1.6m×0.6m×2m)
    │                              │
    │         ╋ 走道 (十字)          │
    │                              │
    │    🟫 shelf_3     🟫 shelf_2  │
    │                              │
    │  🟣 C区              🟠 D区   │
    └──────────────────────────┘
        南 ↓
```

- **仓库**: 10m × 10m
- **货架**: 4 个静态障碍体（有碰撞）
- **区域**: A/B/C/D 四个 2.4m×2.4m 目标区（无碰撞）
- **AGV**: 盒体 + 4 轮子，1kg，颜色可配

---

## 🚀 快速开始

```bash
# Docker 启动（推荐）
docker compose up -d api

# 创建 AGV
curl -s -X POST "http://localhost:8000/api/sim/robot/create?robot_id=agv_1&x=0&y=0&color=blue"

# 移动到 B 区
curl -s -X POST "http://localhost:8000/api/sim/robot/agv_1/move-by-zone?zone=B"

# Agent 自然语言控制
curl -s -X POST "http://localhost:8000/api/agent/run" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"把小车 agv_1 移到 C 区","mode":"auto"}'
```

**本地 GUI 可视化**（WSL/Win11 直接跑）：

```bash
SIM_MODE=gui python3 scripts/sim_demo.py
# 左键拖拽旋转 | 滚轮缩放 | Ctrl+左键平移
```

---

## 📡 API 端点

### 场景

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sim/status` | 仓库场景 + 所有机器人 |
| POST | `/api/sim/reset` | 重置（清空AGV，保留场景） |
| GET | `/api/sim/zones` | 区域定义 |

### 机器人

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sim/robot/create` | 创建 AGV（robot_id/x/y/yaw/color） |
| DELETE | `/api/sim/robot/{id}` | 删除 AGV |
| GET | `/api/sim/robot/{id}` | 查询单机器人（位置/朝向/区域） |
| GET | `/api/sim/robots` | 列出所有机器人 |

### 控制

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sim/robot/{id}/move` | 移动到坐标（自动对齐朝向） |
| POST | `/api/sim/robot/{id}/move-by-zone` | 移动到区域 A/B/C/D |
| POST | `/api/sim/robot/{id}/velocity` | 速度控制（vx/vy/duration） |

### 传感器

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sim/robot/{id}/distance` | 到目标点距离 |
| GET | `/api/sim/robot/{id}/obstacle` | 激光雷达（forward/left/right/back） |

> 完整 API 文档：`http://localhost:8000/docs`

---

## 🖥️ 前端控制台

浏览器打开 `http://localhost:8000/sim.html`：

- **🗺️ 2D 俯瞰**：Canvas 实时渲染（货架/区域/AGV 朝向三角）
- **🤖 车队管理**：一键创建（顺序命名 agv_1/2/3...）、删除、选中
- **🎮 手动控制**：坐标移动 / 区域跳转（A/B/C/D）
- **🧠 AI 调度**：自然语言输入 → Agent 工具调用 → 仿真执行

---

## 📁 文件结构

```
app/
├── sim_engine.py    # PyBullet 仿真引擎（SimEngine 单例）
├── sim_api.py       # FastAPI 路由（12 个端点）
├── tools.py         # Agent 工具注册（3 个仿真工具）
└── langgraph_agent.py  # Agent 工作流 + 提示词

web/
└── sim.html         # 仿真控制台（Canvas 2D + AI 调度）

scripts/
├── test_sim.py      # 4 项自动化验证
└── sim_demo.py      # GUI 交互式演示
```

---

## 🔗 关联

本分支是 [ai-agent-system](https://github.com/Chandler0591/ai-agent-system)（企业级 AI Agent 平台）的仿真模块。主分支包含：

- 📄 知识库 RAG 问答（PDF 解析 + 混合检索 + 重排）
- 🔐 企业安全（JWT 认证 + 多租户 RBAC + 限流）
- 🤖 多 Agent 协作（Supervisor 模式 + LangGraph 工作流）
- 📊 可观测性（Prometheus + Grafana + 审计日志）

> 切换到 `main` 分支查看完整项目：`git checkout main`
