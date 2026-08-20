# Gazebo/ROS2 后端程序执行流程

> 从启动到小车跑起来、再到完成移动的完整链路拆解，对照真实代码（行号以 `feature/simulation` 分支为准）。

---

## 一、整体架构：三个层次

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

补充两个架构事实：

- **单 Node 多车**：所有 `Ros2Robot` 共享同一个 rclpy.Node，话题靠 `/{robot_id}/` 命名空间区分（`sim_gazebo_robot.py` 设计决策）
- **GazeboBackend 只当"客户端"**：它不启动、不管理 gzserver，只通过 `/spawn_entity`、`/delete_entity` 等服务与运行中的 Gazebo 交互

---

## 二、关键前提：两个独立进程，两套 executor

理解执行流程必须先分清两个进程（最容易混淆的点）：

| 进程 | 入口 | executor | 职责 |
|------|------|----------|------|
| **业务进程**（demo/API） | `SIM_BACKEND=gazebo python3 scripts/sim_demo.py` | `SingleThreadedExecutor` + 专用 spin 线程（`sim_gazebo.py` L76-90） | `GazeboBackend` 单例、`Ros2Robot`×N、`MoveToClient`×N |
| **MoveToServer 进程**×每车一个 | `python3 scripts/ros2_examples/start_move_to_server.py agv_X` | `MultiThreadedExecutor(num_threads=3)`（`sim_gazebo_srv.py` L143-154） | `MoveToServer`：20Hz 闭环控制、阻塞式移动回调 |

> `MoveToServer` 不是 `GazeboBackend` 创建的，而是**独立进程**（start_move_to_server.py 启动，自带同名残留自愈清理）。业务进程只持有 `MoveToClient`（`sim_gazebo.py` L175）。

---

## 三、完整启动流程（从零到能动）

### 第 1 步：Gazebo 仿真环境由容器拉起

```bash
# 容器启动时 entrypoint 拉起 gzserver（world 文件声明 state 插件）
gzserver /workspace/worlds/*.world
```

**后端不会启动 Gazebo**。`GazeboBackend.__init__` 只做 ROS 2 侧初始化（`sim_gazebo.py` L52-85）：

```python
# 由 get_sim() 懒加载创建单例（SIM_BACKEND=gazebo 时）
→ rclpy.init()
→ Node("gazebo_backend")
→ SingleThreadedExecutor + spin 线程启动   # spin_once(0.1s)，处理 odom/scan 回调与 Service 响应
```

**此时系统状态**：Gazebo 世界已运行（无车）；后端 Node 已就绪、spin 线程后台跑。

### 第 2 步：生成车辆（Spawn）

`create_robot(robot_id, x, y, yaw)`（`sim_gazebo.py` L123-208）：

```python
cmd = ["ros2", "run", "gazebo_ros", "spawn_entity.py",
       "-entity", robot_id, "-file", agv.urdf,
       "-x", x, "-y", y, "-z", 0.117,     # 默认 z=0.117：离地 2mm 落地，防空转
       "-Y", yaw, "-robot_namespace", robot_id]   # 话题前缀 → /agv_X/cmd_vel、/agv_X/odom
subprocess.run(cmd, timeout=30)
```

spawn_entity 内部：读取 URDF → Gazebo 创建物理实体 → 看到 `<gazebo><plugin>` 加载 `libgazebo_ros_diff_drive.so` → 按 `-robot_namespace` 设置话题名。

**失败自愈**：spawn 失败（多半是同名残留车）→ 自动 `delete_entity` 清理 → 重试一次（L154-171）。

### 第 3 步：建 ROS 2 封装并等 odom

spawn 成功后（L173-200）依次做：

1. 建 `Ros2Robot`（订阅 `/odom`、`/scan`，发布 `/cmd_vel`，缓存位姿）与 `MoveToClient`（等服务端上线，最多 10s）
2. **自动等待首条 odom**（15s deadline，每 0.2s 探测）——不需要上层手动等
3. **自检 cmd_vel 订阅者**（`ros2 topic info -v`，0 订阅者 = diff_drive 插件未监听，发警告）

---

## 四、移动执行流程（从命令到到达）

### 发起：move_robot()（`sim_gazebo.py` L254-322）

```
T=0ms  move_robot("agv_1", 2.5, 2.5)
        │
        ├─ 防穿模校验：目标点距货架 ≥ 安全距离；直线路径 check_path_clear
        │   （不通过 → 直接返回 error，不发指令）
        ├─ distance < 0.001 → 直接 status="arrived"（已在目标位置）
        │
        ├─ robot.status = "moving"（Ros2Robot 状态机 idle/moving/arrived）
        ├─ 启动后台线程 _drive → 立即返回（不阻塞主线程）
        │
        └─ _drive 线程：move_clients[agv_1].call_sync(2.5, 2.5, 0.5)
```

### 同步调用：call_sync()（`sim_gazebo_srv.py` L179-210）

```python
future = cli.call_async(req)          # 异步发出 Service 请求
future.add_done_callback(_on_done)    # future 回调 + Event 等待
if not done.wait(timeout=120.0):      # 默认 120s（必须大于 server 端 100s deadline）
    return None                       # 超时 → 上层标记 status=idle
```

> 不用 `spin_until_future_complete`：Node 已挂在 GazeboBackend 的 executor 上，spin 函数线程不安全；`Event` 等待可在任意线程调用（多车并发安全）。

### 控制闭环：handle_move_request()（`sim_gazebo_srv.py` L93-140，server 进程内）

```
T=+几ms  Server 收到请求（MoveToServer 进程，MultiThreadedExecutor 3 线程）
         │
         └─ 20Hz 控制环，最多 100s（deadline）：
            ① 读 odom 缓存（独立回调组持续更新，不被移动回调阻塞）
            ② dist = hypot(dx, dy)
            ③ dist < 0.05 → 发 Twist() 停车 → success=True "arrived" → 返回
            ④ |yaw_err| > 0.15(≈9°) → 原地转向（angular=clamp(2·yaw_err, ±1)）
               否则 → 前进 + 纠偏（linear=min(speed, dist·2) 接近减速）
            ⑤ 每 5s 打印一次进度日志（pos/yaw/距目标）
            ⑥ rate.sleep() 等下一帧（20Hz）
         │
         └─ 超时 → 停车 → success=False "move timeout"
```

**闭环数据流（每 50ms 一圈）**：

```
Server 读 odom 缓存 → 算距离/朝向 → 发 /cmd_vel
   ↑                                        ↓
odom 缓存更新 ←── Gazebo 插件发布 /odom ←── 轮子转 → 车身动（物理模拟）
```

### 收尾：唤醒与等待

```
T=到达    call_sync() 的 done.wait() 被唤醒 → 拿到 response → _drive 线程收尾：
         success=True  → robot.status = "arrived"
         None / 失败    → robot.status = "idle" + 警告日志（超时无响应 / move timeout）
         │
T=到达+  上层 wait_arrival("agv_1") 主线程轮询 status（0.1s 间隔）
         → 看到非 "moving" → 返回最终状态 ✓
```

---

## 五、最容易踩的 3 个坑（对照本项目修正版）

### 坑 1：忘了启动 spin 线程 → 回调永远不触发

```python
# ❌ 只创建 node 不 spin：永远收不到消息
node.create_subscription(Odometry, '/odom', callback, 10)

# ✅ 本项目写法：executor + 专用 spin 线程
executor = SingleThreadedExecutor(); executor.add_node(node)
threading.Thread(target=lambda: executor.spin_once(timeout_sec=0.1)).start()
```

> 本项目两处都已内置：`GazeboBackend`（L80-84）与 `MoveToServer.spin()`（L148-151）。

### 坑 2：阻塞式移动回调会卡死 odom 更新？

```python
# ⚠️ 在单线程 executor 下：回调里长时间循环 → 其他回调全部饿死（odom 冻结）
# ✅ 本项目解法（sim_gazebo_srv.py L68-80）：
#    • odom 订阅用独立的 MutuallyExclusiveCallbackGroup
#    • executor = MultiThreadedExecutor(3)
#    → 移动回调阻塞 100s 期间，odom 缓存仍持续更新（否则 pos 冻结死等）
```

### 坑 3：车刚 spawn 就 move 会"尚无 odom 数据"？

```python
# ✅ 已内置，无需手动等（sim_gazebo.py L180-188）：
#    create_robot spawn 后自动等待首条 odom（15s deadline）+ 自检 cmd_vel 订阅者
#    只有 15s 内仍未收到才打警告；此时再调 move_robot 才会返回 error
```

---

## 六、一句话总结

> **`move_robot()`（业务进程）→ 防穿模校验 → 后台线程发 Service 请求 → MoveToServer 进程的 20Hz 控制环（读 odom 缓存 → 发 cmd_vel → Gazebo 轮子动 → 插件回 odom）→ 到站停车返回 response → 唤醒调用线程置 status=arrived → `wait_arrival()` 轮询到结果。**

核心是**两个进程各司其职**：业务进程的 spin 线程让"耳朵嘴巴活起来"，MoveToServer 的**多线程 executor + 独立回调组**保证"边开车边听 odom"；Service 的阻塞等待实现"一问一答"的同步效果。
