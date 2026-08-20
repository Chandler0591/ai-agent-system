# 🏭 AI 调度仿真系统

> **[ai-agent-system](https://github.com/Chandler0591/ai-agent-system)** 仿真模块 | `feature/simulation` 分支

基于 **PyBullet / Gazebo-ROS 2 双仿真后端 + FastAPI + LangGraph Agent** 的仓库调度仿真系统，后端通过 `SIM_BACKEND` 环境变量热切换（PyBullet 轻量默认，Gazebo + ROS 2 Humble 物理驱动）。10m×10m 物理仿真环境，支持 AGV 小车创建/移动/障碍检测，Agent 自然语言控制，2D Canvas 实时可视化。

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
| 物理引擎 | PyBullet DIRECT/GUI 与 Gazebo+ROS 2 双后端，重力 + 碰撞检测 |
| AGV 管理 | 创建/删除/移动/速度控制，支持 yaw 初始朝向 |
| 场景感知 | 激光雷达模拟 (rayTest)、距离计算、区域判定 |
| REST API | 12 个端点，FastAPI 自动生成 `/docs` |
| Agent 工具 | move_robot / get_robot_status / check_obstacle / check_distance |
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

## 🤖 Gazebo 物理后端（ROS 2 Humble）

通过 `SIM_BACKEND` 环境变量切换后端（`pybullet` 默认 / `gazebo`），两后端实现同一 `SimBackend` 接口，上层代码无感知。

| 组件 | 职责 |
|------|------|
| `app/sim_gazebo.py` | `GazeboBackend`：spawn/删除 AGV、move_to 调度、场景管理 |
| `app/sim_gazebo_robot.py` | `Ros2Robot`：odom 订阅 / cmd_vel 发布 / 真值查询 |
| `app/sim_gazebo_srv.py` | `MoveToServer`（每车一进程）+ `MoveToClient`：20Hz 闭环控制器 |
| `app/sim_geometry.py` | 仓库几何常量（两后端共用，防穿模校验） |
| `models/agv.urdf` | AGV 物理模型（两后端共用） |

### 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    你的控制代码（上层）                      │
│              sim_gazebo.py / 状态机 / 业务逻辑              │
└──────────────────────┬──────────────────────────────────────┘
                       │ 调用 move_robot() / wait_arrival()
┌──────────────────────▼──────────────────────────────────────┐
│                  ROS 2 通信层（中间层）                     │
│     sim_gazebo_robot.py (Ros2Robot) + sim_gazebo_srv.py   │
│     • 发布 /cmd_vel  • 订阅 /odom  • Service 一问一答      │
└──────────────────────┬──────────────────────────────────────┘
                       │ 话题 / 服务
┌──────────────────────▼──────────────────────────────────────┐
│                   仿真引擎层（底层）                        │
│     Gazebo + libgazebo_ros_diff_drive.so (插件)           │
│     物理模拟：车轮转 → 车身动 → 发布 odom                  │
└─────────────────────────────────────────────────────────────┘
```

- **上层**：`GazeboBackend` 与 PyBullet 后端实现同一 `SimBackend` 接口，业务代码无感知
- **中间层**：`Ros2Robot` 封装 odom/cmd_vel 与真值查询，`MoveToServer` 20Hz 闭环控制
- **底层**：Gazebo classic + `libgazebo_ros_diff_drive.so` 插件，物理结算与 odom 发布

### 运行（容器内）

**推荐：一键编排**（自动清场 → 起服务端 → 演示 → 统一清理，^C 也会兜底清理）：

```bash
bash scripts/run_demo.sh
```

**手动方式**：

```bash
# 1) 启动 3 台车的 move_to 服务端（自带残留进程自愈清理）
python3 scripts/ros2_examples/start_move_to_server.py agv_1 &
python3 scripts/ros2_examples/start_move_to_server.py agv_2 &
python3 scripts/ros2_examples/start_move_to_server.py agv_3 &

# 2) 跑三车调度演示（两轮交叉调度，全部到达后自动清理）
SIM_BACKEND=gazebo python3 scripts/sim_demo.py
```

**残留治理**：`run_demo.sh` 统一清场（零速停车 / 删残留车 / 杀残留 server / 杀僵尸 spawn）；`remove_robot` 删除失败自动重试 3 次；`sim_demo.py` 捕获 ^C 自动删车退出——杜绝"幽灵车漂移"与同名节点冲突。

### URDF 物理参数（关键修复）

| 参数 | 值 | 作用 |
|------|-----|------|
| 后轮（驱动） | cylinder 碰撞 + `mu=1` | 抓地力，直线/转向力矩传递 |
| 前轮（万向） | sphere 碰撞 + `mu=0` | 横向自由滑动，不干扰转向 |
| 驱动轮关节 rpy | `(-1.5707963 0 0)` | 轮轴对齐（单轴旋转 child z → parent +y） |
| 接触 | `kp=1e6 kd=1000` | 软接触，避免地面弹跳/抖动 |

> ⚠️ URDF 修改后务必同步进容器并确认生效：`stat -c '%y' /workspace/app/models/agv.urdf`。
> 旧版 URDF（球面点接触驱动轮）会导致 AGV 打滑：0.5 m/s 指令实际仅 ~0.1 m/s、转向无力、yaw 冻结——这是"轮子空转 / 移动超时"类问题最常见的根因。

### 诊断脚本

`scripts/ros2_examples/probe_wheels.py`：轮子驱动/转向/空转探针（对比 odom 与 Gazebo 真值，一键定位物理层问题）。
程序执行完整流程（双进程架构 / spawn / 移动闭环 / 常见坑）：[docs/gazebo-execution-flow.md](docs/gazebo-execution-flow.md)。
完整路线图见 `docs/gazebo-ros2-roadmap.md`。

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
├── sim_engine.py        # 仿真引擎入口（get_sim 双后端开关）
├── sim_backend.py       # SimBackend 抽象接口
├── sim_gazebo.py        # Gazebo 后端（GazeboBackend）
├── sim_gazebo_robot.py  # ROS2 机器人封装（odom/cmd_vel/真值）
├── sim_gazebo_srv.py    # move_to 服务端/客户端（20Hz 闭环）
├── sim_geometry.py      # 仓库几何常量（防穿模校验）
├── sim_api.py           # FastAPI 路由（12 个端点）
├── tools.py             # Agent 工具注册（4 个仿真工具）
└── langgraph_agent.py   # Agent 工作流 + 提示词

web/
└── sim.html         # 仿真控制台（Canvas 2D + AI 调度）

scripts/
├── run_demo.sh          # 一键演示编排（清场→起服务端→演示→统一清理）
├── ros2_examples/       # ROS2 示例：move_to server、轮子探针、odom 读取等
├── test_sim.py          # 4 项自动化验证
└── sim_demo.py          # 演示（PyBullet GUI / Gazebo 双模式）
```

---

## 🔗 关联

本分支是 [ai-agent-system](https://github.com/Chandler0591/ai-agent-system)（企业级 AI Agent 平台）的仿真模块。主分支包含：

- 📄 知识库 RAG 问答（PDF 解析 + 混合检索 + 重排）
- 🔐 企业安全（JWT 认证 + 多租户 RBAC + 限流）
- 🤖 多 Agent 协作（Supervisor 模式 + LangGraph 工作流）
- 📊 可观测性（Prometheus + Grafana + 审计日志）

- 🏗️ Gazebo/ROS2 后端路线图：[docs/gazebo-ros2-roadmap.md](docs/gazebo-ros2-roadmap.md)
- 🔄 程序执行完整流程：[docs/gazebo-execution-flow.md](docs/gazebo-execution-flow.md)

> 切换到 `main` 分支查看完整项目：`git checkout main`
