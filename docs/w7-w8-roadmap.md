# 第 7-8 周实施计划：3D 可视化 + 仓储场景

> 目标：把仿真从"代码/命令行"升级为"可看、可点、可演示"的产品级形态。
> 原则：最大化复用现有基础（`sim_geometry` 几何常量、`SimBackend` 双后端、SSE 已有雏形、`task_manager`、docker-compose）。

---

## 现有基础盘点（开工前核对）

| 计划项 | 现状 | 结论 |
|--------|------|------|
| W7-1 Three.js 渲染 | `web/sim.html` 已有 Canvas 2D 鸟瞰渲染（仓库+小车+yaw 旋转） | 2D → 3D 升级 |
| W7-2 SSE 位置推送 | `app/main.py` L202 已有 SSE（agent 流式输出）；sim 位置目前靠轮询 `/api/sim/status` | 新增 sim 位置流 |
| W7-3 点击地图交互 | `web/sim.html` L359 已有 canvas click → 坐标 | 迁移到 3D raycast |
| W7-4 货架/装卸区模型 | `app/sim_geometry.py` 已有货架/区域几何常量 | 几何已有，缺 3D 模型 |
| W7-5 任务队列 + 优先级 | `app/task_manager.py` 已有 TaskManager（无优先级）；Celery 已在 | 加优先级字段 |
| W8-1 多车避障 | 防穿模校验（静态货架）+ `check_path_clear` 已有 | 缺车-车动态避障 |
| W8-2 Compose 一键启动 | `docker-compose.yml` 已有 | 补前端服务与健康检查 |
| W8-3 README + 架构图 | README 已较全 | 补架构图与快速上手路径 |
| W8-4 录制 Demo | 未开始 | 全新 |
| W8-5 接单介绍页 | 未开始 | 全新 |

---

## W7：3D 可视化 + 交互闭环

### W7-1 Three.js 渲染鸟瞰视图（2D 坐标映射 3D）✅

- **现状**：`web/sim.html` 用 Canvas 2D 画平面仓库（L229-321），坐标映射已有
- **方案**：
  - 新建 `web/index3d.html`，Three.js 走 CDN 引入（无构建工具，与现有 web 目录风格一致）
  - 正交/透视相机俯视场景；坐标映射：仿真 (x, y) → Three.js 场景 (x, -z)（y 轴朝上，符合右手系）
  - 地面 Plane + 货架 Box + 小车（车身 box + 4 轮 cylinder，轮子颜色沿用 agv.urdf 配色）
  - 数据源复用 `GET /api/sim/status`（`sim_api.py` 已提供 scene + robots）
- **产出**：浏览器看到 3D 仓库（浏览器打开即见，无需构建）

### W7-2 SSE 推送小车实时位置 → Three.js 更新 ✅

- **现状**：SSE 机制已有（`main.py` L202 `StreamingResponse(media_type="text/event-stream")`），sim 位置无推送
- **方案**：
  - 新增 `GET /api/sim/stream`（SSE）：后端每 0.1s 采样 `sim.get_all_robots()`，以 `data: {robot_id, x, y, yaw, status}` 推送
  - 前端 `EventSource` 接收，小车位置做**线性插值平滑**（0.1s 采样间隔足够平滑，无需物理插值）
  - 断开重连：`EventSource` 自带；后端心跳注释事件防代理超时
- **产出**：小车平滑移动（无卡顿跳变）

### W7-3 点击地图 → 生成目标坐标 → Agent 执行 ✅

- **现状**：2D canvas 已有 click → 仿真坐标（`sim.html` L359-360）
- **方案**：
  - Three.js `Raycaster` 点击地面 → 换算仿真坐标 → 弹窗选车/目标语义（"去这取货"/"送到这"）
  - 两种执行路径：直接调 `/api/sim/robot/move`（`sim_api.py` 已有）；或生成自然语言交给 Agent（证明"点击→Agent 调度"闭环）
- **产出**：交互闭环（点哪车去哪）

### W7-4 添加货架/装卸区模型 ✅

- **现状**：`sim_geometry` 已有货架位置、A-D 区、中转点等几何常量（防穿模校验共用）
- **方案**：前端渲染层从 `GET /api/sim/status` 的 scene 信息读取货架/区域坐标 → 3D 建模：货架 = 多层 box（框架 + 隔板），装卸区 = 地面色块/标记
- **产出**：场景像真实仓库（与仿真几何严格一致，所见即所仿）

### W7-5 任务队列系统 + 优先级调度 ✅

- **现状**：`task_manager.TaskManager`（create_task/update_task/get_task）无优先级；Celery 已部署
- **方案**：
  - `TaskManager` 任务 dict 增加 `priority` 字段，`get_tasks` 按 priority 排序返回；出队取最高优先级
  - 任务类型扩展：sim 移动任务 / 复合任务（多段移动 + 等待）
  - 前端（3D 页）展示任务队列与当前执行状态
- **产出**：多任务排队执行、高优先级插队

---

## W8：避障 + 打包交付

### W8-1 多车路径规划（避免碰撞）✅

- **现状**：静态防穿模（目标点/直线路径与货架校验）+ `check_path_clear` 已有；**车-车动态避障缺失**
- **方案**（由简到繁，推荐先 ①②）：
  - ① 车-车距离检测：move 前与移动中检查与其他车距离，过近则降速/等待
  - ② 中转点调度：demo 已有多车交叉调度经中转点模式，把中转点机制做成通用（多车协调靠错峰 + 中转）
  - ③ 可选进阶：网格 A* 全局路径（仓库小，几何简单，收益有限）
- **产出**：多车同时运行无碰撞

### W8-2 Docker Compose 一键启动 ✅

- **现状**：`docker-compose.yml` 已有（API/Celery 等容器）
- **方案**：补前端静态服务（nginx 或 FastAPI 静态挂载 web/）、`SIM_BACKEND` 环境变量、健康检查（API `/health`）；README 增"一键启动"段
- **产出**：`docker compose up` 后浏览器打开即见 3D 仓库 + API 可调

### W8-3 README + 架构图 ✅

- **现状**：README 已有模块清单与 Gazebo 章节
- **方案**：
  - 架构图（ASCII/图片）：Agent → tools → SimBackend（PyBullet/Gazebo）→ 3D 可视化 + REST/SSE；任务队列/多智能体旁路
  - "新成员 10 分钟上手"路径：一键启动 → 打开 3D → 点地图 → 看小车动
- **产出**：新成员 10 分钟跑通全链路

### W8-4 录制完整 Demo ⏳（待录制）

- **方案**：自然语言调度（"agv_1 去 A 区取货送到 D 区"）+ 3D 可视化同屏录制，剪辑关键镜头（创建→移动→到达→交叉调度）
- **录制步骤**：
  1. 起服务：`docker compose up -d api`，浏览器开 `http://localhost:8000/index3d.html`
  2. 打开 OBS（或系统录屏）：一个窗口录 3D 视图，另一个窗口录终端跑 `python3 scripts/sim_demo.py`（或对话调度命令）
  3. 镜头：介绍页 → 3D 场景全景 → 快速创建 3 台车 → 点击地面移动（或 Agent 对话）→ 多车同场 → 到达目标
  4. 结尾剪入 `web/intro.html` 工作流程段（5 步闭环）
- **产出**：可对接客户的演示视频（🎬）

### W8-5 接单介绍页 + GitHub README ✅

- **方案**：README 头部加项目简介 + Demo 动图/链接；必要时独立介绍页（静态，放 web/）
- **产出**：可直接转发给客户的入口

---

## 依赖与建议顺序

```
W7-1（3D 渲染）→ W7-2（SSE 数据流）→ W7-3（点击交互）→ W7-4（场景完善）
W7-5（任务队列）可与 W7-1/2 并行
W8-1（避障）依赖 W7-3 的交互路径，但核心逻辑可先于前端开发
W8-2（Compose 打包）在 W7 功能稳定后
W8-3/4/5（文档/Demo/介绍页）最后收尾
```

**风险点**：W7-2 SSE 与多后端（PyBullet/Gazebo）的采样一致性——`get_all_robots()` 是 `SimBackend` 接口方法，两后端同构，风险低；W8-1 车-车避障是唯一有算法复杂度的项，先用距离检测 + 中转错峰，不引入全局规划。
