# Gazebo/ROS2 后端程序执行流程

> 从启动到小车跑起来、再到完成移动的完整链路拆解。所有代码片段与行号对照 `feature/simulation` 分支真实源码（app/sim_gazebo.py、app/sim_gazebo_robot.py、app/sim_gazebo_srv.py、scripts/sim_demo.py）。

---

## 序：通俗版——先建立直觉

把 Gazebo 想象成真实仓库的模拟器，AGV 是"考驾照的新手司机"。链路每一步：

### ① spawn（生成车辆）

把 `agv.urdf` 文件交给 Gazebo → 世界里出现一辆车（相当于游戏里"刷"出一个角色）。

### ② diff_drive 通电（驱动插件激活）

URDF 里写了 `<gazebo>` 插件块（`agv.urdf` L204-223），Gazebo 加载模型时顺带激活它。插件做两件事：

- 订阅 `/agv_1/cmd_vel` → 听"开多快"的指令（踩油门）
- 发布 `/agv_1/odom` → 广播"我现在在哪"（仪表盘）
- 关键配置：`update_rate=30`（30Hz 控制/发布）、`odometry_frame=odom`、`robot_base_frame=base_link`

### ③ odom 数据流（位置广播）

插件以 **30Hz** 持续把 (x, y, 朝向) 发到 `/agv_1/odom`；我们的 `Ros2Robot` 订阅它（`sim_gazebo_robot.py` L53-54）→ `get_pose()` 随时能查到车的位置。（odom = odometry 里程计，就是"车自己报告自己的位置"）

### ④ Service 同步移动（一问一答式开车）

客户端发请求："去 (2.5, 2.5)，速度 0.5" → 服务端收到后自己开车：读 odom 判断在哪 → 发 cmd_vel 前进 → 到站回复 success=true；客户端期间一直阻塞等待（像函数调用）。

### 核心概念对照

| 概念 | 通俗理解 | 本项目用法 |
|------|---------|-----------|
| Topic 话题 | 广播电台：发布者播音不管谁听，订阅者调频收听 | `/cmd_vel`（速度指令）、`/odom`（位置） |
| Service 服务 | 打电话：一方发起、另一方必须回话 | `/agv_1/move_to`（命令开到某处） |
| 四元数 | 3D 旋转的数学表示（4 个数），ROS 标准 | odom 朝向用四元数给出，回调内联公式换算成绕 Z 轴角度（车在地面只绕竖直轴转；`sim_gazebo_robot.py` L64-70 与 `sim_gazebo_srv.py` L83-91 两处） |

### "仿真→现实"的桥

真实 AGV（宇树、仙知等厂商的车）出厂就跑 ROS 2，接口和 Gazebo 里**完全同名同类型**——真车也有 `/cmd_vel`、也发布 `/odom`、导航栈也用 Service/Action 下任务。所以我们写的 `Ros2Robot`、`MoveToClient` 代码，将来把话题名从 `/agv_1/...` 改成真车的命名空间，就能控制真车。训练场和赛场规则一样，这就是桥。

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

两个架构事实（容易忽略）：

- **单 Node 多车**：所有 `Ros2Robot` 共享同一个 rclpy.Node（`sim_gazebo_robot.py` 设计决策），话题靠 `/{robot_id}/` 命名空间区分（`/agv_1/cmd_vel`、`/agv_2/odom` …）
- **GazeboBackend 只当"客户端"**：它不启动、不管理 gzserver，只通过 `/spawn_entity`、`/delete_entity` 等服务与运行中的 Gazebo 交互

---

## 二、关键前提：两个独立进程，两套 executor

整个系统由**业务进程**和**每车一个 MoveToServer 进程**组成，各自维护自己的 executor（最容易混淆的点）：

| 进程 | 入口 | executor | 职责 |
|------|------|----------|------|
| **业务进程**（demo/API） | `SIM_BACKEND=gazebo python3 scripts/sim_demo.py` | `SingleThreadedExecutor` + 专用 spin 线程（`sim_gazebo.py` L78-90） | `GazeboBackend` 单例、`Ros2Robot`×N、`MoveToClient`×N |
| **MoveToServer 进程**×每车一个 | `python3 scripts/ros2_examples/start_move_to_server.py agv_X` | `MultiThreadedExecutor(num_threads=3)`（`sim_gazebo_srv.py` L142-154） | `MoveToServer`：20Hz 闭环控制、阻塞式移动回调 |

> `MoveToServer` 不是 `GazeboBackend` 创建的，而是**独立进程**：`start_move_to_server.py` 启动，自带同名残留自愈（`kill_stale_servers`，L21-49：pgrep 同名进程 → SIGKILL → 等 DDS 发现租约过期 20s）。业务进程只持有 `MoveToClient`（`sim_gazebo.py` L175）。

---

## 三、完整启动流程（从零到能动）

### 第 1 步：Gazebo 仿真环境（由容器侧拉起，与后端无关）

```bash
# 容器内真实启动命令（ps 可查，进程长期驻留）：
gzserver /workspace/app/models/state_world.world \
  -s libgazebo_ros_init.so \
  -s libgazebo_ros_factory.so \
  -s libgazebo_ros_force_system.so
```

- world 文件 `state_world.world` 声明仓库场景（地面、货架、区域）与 `gazebo_ros_state` 插件（真值服务）
- `-s` 显式加载 ROS 桥接插件：`init`（/clock）、`factory`（/spawn_entity、/delete_entity 服务）、`force_system`（/apply_body_wrench）
- **GazeboBackend 假定 Gazebo 已在运行**——它不 spawn gzserver，只做 ROS 2 侧初始化

### 第 2 步：业务进程初始化 GazeboBackend（`sim_gazebo.py` L41-90）

入口：`SIM_BACKEND=gazebo python3 scripts/sim_demo.py` → `get_sim()`（`sim_engine.py` L571）懒加载创建**单例**：

```python
# L46-50 单例：__new__ 保证全局只有一个实例（与 PyBullet 后端一致）
def __new__(cls):
    if cls._instance is None:
        cls._instance = super().__new__(cls)
        cls._instance._initialized = False
    return cls._instance

# L57-65 rclpy 延迟导入：非 ROS2 环境 import 本模块不报错（保 PyBullet 路径），实例化才报错
try:
    import rclpy
    from rclpy.node import Node
except ImportError as e:
    raise RuntimeError("Gazebo 后端需要 ROS 2 环境（rclpy）...或改用 SIM_BACKEND=pybullet") from e

# L67-84 核心初始化
rclpy.init()
self.node = Node("gazebo_backend")
self.robots: Dict[str, Ros2Robot] = {}        # robot_id → Ros2Robot
self.move_clients: Dict[str, MoveToClient] = {}  # robot_id → MoveToClient
self._move_lock = threading.Lock()            # 状态写锁（多车并发安全）
self.mode = "gazebo"

# 专用 executor + spin 线程（rclpy spin 非线程安全，必须集中在单一线程）
self.executor = SingleThreadedExecutor()
self.executor.add_node(self.node)
self._spin_thread = threading.Thread(target=self._spin_loop, daemon=True,
                                     name="gz-executor-spin")
self._spin_thread.start()

# L87-90 spin 循环：每 0.1s 处理一次待决事件（odom/scan 回调、Service 响应）
def _spin_loop(self):
    while self._running:
        self.executor.spin_once(timeout_sec=0.1)
```

**此时系统状态**：Gazebo 世界已运行（无车）；后端 Node 就绪、spin 线程后台跑；`robots`/`move_clients` 还是空 dict。

### 第 3 步：demo 创建 3 台车（`scripts/sim_demo.py` L16-18）

```python
sim.create_robot("agv_1", 0, 0, color="blue")      # z 用默认值 0.117
sim.create_robot("agv_2", -3, -3, color="orange")
sim.create_robot("agv_3", 3, 2, color="green")
```

### 第 4 步：create_robot() 内部（`sim_gazebo.py` L123-208）

**a) 幂等保护**（L134-136）：同名车已存在 → 直接返回现有位姿，不重复 spawn。

**b) spawn 命令**（L140-149）：

```python
cmd = ["ros2", "run", "gazebo_ros", "spawn_entity.py",
       "-entity", robot_id,                  # Gazebo 实体名（必须唯一）
       "-file", _AGV_URDF_PATH,              # URDF 路径（L36-38，与 PyBullet 共用）
       "-x", str(x), "-y", str(y), "-z", str(z),   # z 默认 0.117（函数默认值，L124）
       "-Y", str(yaw),                       # 初始朝向（绕 Z 轴）
       "-robot_namespace", robot_id]         # ← 话题前缀：/agv_X/cmd_vel、/agv_X/odom
subprocess.run(cmd, capture_output=True, text=True, timeout=30)
```

> `z=0.117` 的意义（L128-132 注释）：轮底在车身中心下 0.115m，此值高出触地高度 2mm，刚好超过 ODE 接触生成阈值（min_depth 1mm）——既保证落地即产生接触（零穿透时接触判定不稳定、轮子无摩擦空转），又让落地冲击足够小。旧值 0.13 实测约 1/3 概率车轮接触异常。

**c) spawn_entity 内部行为**：读取 URDF → Gazebo 创建物理实体 → 看到 `<gazebo><plugin>` 加载 `libgazebo_ros_diff_drive.so` → 按 `-robot_namespace` 自动设置话题：订阅 `/agv_X/cmd_vel`、发布 `/agv_X/odom`。

**d) 失败自愈**（L154-171）：spawn 失败（多半是上一轮残留同名车）→ 自动 `delete_entity` 清理 → 重试一次；仍失败才返回 error。

**e) 建 ROS 2 封装**（L173-178）：

```python
robot = Ros2Robot(robot_id, self.node)        # 订阅 /odom、/scan；发布 /cmd_vel；缓存位姿
client = MoveToClient(robot_id, self.node)    # 等 /agv_X/move_to 服务上线（最多 10s，L172-177）
self.robots[robot_id] = robot
self.move_clients[robot_id] = client
self.robot_speeds[robot_id] = 0.5             # 默认速度
```

**f) 自动等待首条 odom**（L180-188，15s deadline 每 0.2s 探测）+ **自检 cmd_vel 订阅者**（L190-200，`ros2 topic info -v`，0 订阅者 = diff_drive 插件未监听 → 警告）。

---

## 四、移动执行流程（从命令到到达）

### 发起：move_robot()（`sim_gazebo.py` L253-322）

```
T=0ms  move_robot("agv_1", 2.5, 2.5, speed=0.5)
        │
        ├─ 防穿模校验①（L259-266）：目标点与每台货架距离 ≥ SHELF_SAFE_DISTANCE
        │   不通过 → 返回 error（不发指令）
        ├─ 读位姿（L268-272）：get_pose() 有 error（尚无 odom）→ 返回 error
        ├─ 防穿模校验②（L274-277）：直线路径 check_path_clear（目标合法 ≠ 路径合法）
        ├─ distance < 0.001（L281-290）→ 直接 status="arrived"，返回"已在目标位置"
        │
        ├─ 加锁写状态（L292-294）：robot.status = "moving"（Ros2Robot 状态机 idle/moving/arrived）
        ├─ 启动后台线程 _drive（L312，daemon）→ move_robot 立即返回（不阻塞）
        │
        └─ _drive 线程（L297-312）：
            resp = move_clients[agv_1].call_sync(2.5, 2.5, 0.5)   # 阻塞，最多 120s
            success=True  → status="arrived"
            None/失败     → status="idle" + 警告（超时无响应 / move timeout）
            异常          → status="idle" + error 日志（try/except 兜底，L307-310）
```

### 同步调用：call_sync()（`sim_gazebo_srv.py` L179-210）

```python
req = MoveTo.Request(); req.target_x, req.target_y, req.speed = x, y, speed
done = threading.Event(); result_box = {}

future = self.cli.call_async(req)             # 异步发出 Service 请求
def _on_done(fut):                            # future 回调（executor 线程里触发）
    result_box['resp'] = fut.result()         # 结果装箱，避免闭包竞态
    done.set()
future.add_done_callback(_on_done)
if not done.wait(timeout=timeout):            # 默认 120s（L179）
    logger.warning(f"{robot_id} move_to 超时 ({timeout}s)")
    return None                               # → 上层 status="idle"
return result_box.get('resp')
```

> 为什么不用 `spin_until_future_complete`（L183-186 注释）：spin 函数线程不安全，且本 Node 已挂在 GazeboBackend 的 executor 上；`future 回调 + Event 等待` 可在任意线程调用（多车并发安全）。120s 必须大于 server 端 100s deadline（L104-105 注释：否则上一轮移动未结束、新一轮请求排队，客户端先超时放弃）。

### 控制闭环：handle_move_request()（`sim_gazebo_srv.py` L93-140，server 进程内）

```python
def handle_move_request(self, request, response):
    if self.pos is None:                      # L97-101：尚无 odom → 直接拒绝
        response.success = False; response.message = "尚无 odom 数据"; return response

    rate = self.create_rate(20)               # L103：20Hz 控制环
    deadline = time.time() + 100.0            # L106：单次移动最长 100s
    last_log = 0.0
    while rclpy.ok():
        if time.time() > deadline:            # 超时 → 停车、返回失败
            self.cmd_pub.publish(Twist()); response.success=False; return response
        dx = request.target_x - self.pos[0]; dy = request.target_y - self.pos[1]
        dist = math.hypot(dx, dy)
        if dist < 0.05:                       # L118-123：到达阈值 5cm → 发 Twist() 停车
            self.cmd_pub.publish(Twist()); response.success=True; return response
        # 转向 + 前进闭环（L124-133）
        target_yaw = math.atan2(dy, dx)
        yaw_err = atan2(sin(target_yaw - self.yaw), cos(target_yaw - self.yaw))  # 归一化 [-π,π]
        msg = Twist()
        if abs(yaw_err) > 0.15:               # 朝向差 > ~9°：原地转向
            msg.angular.z = max(-1.0, min(1.0, 2.0 * yaw_err))
        else:                                 # 前进 + 纠偏：接近时减速
            msg.linear.x = min(request.speed, dist * 2)
            msg.angular.z = max(-0.8, min(0.8, 2.0 * yaw_err))
        if time.time() - last_log >= 5.0:     # 每 5s 进度日志（诊断用）
            logger.info(f"{robot_id} 移动中: pos=..., yaw=..., 距目标 {dist:.2f}m")
        self.cmd_pub.publish(msg)
        rate.sleep()                          # 等下一帧（20Hz → 每 50ms 一圈）
```

**为什么 odom 不被移动循环饿死**（关键设计，L68-80）：`srv` 用独立 `MutuallyExclusiveCallbackGroup`，`odom` 订阅用另一个独立回调组；executor 是 `MultiThreadedExecutor(num_threads=3)`（1 个阻塞式移动回调 + 1 个 odom 订阅 + 1 缓冲）——移动回调阻塞 100s 期间 odom 缓存仍持续更新。

**闭环数据流（每 50ms 一圈）**：

```
Server 读 odom 缓存(pos/yaw) → 算距离/朝向差 → 发 /cmd_vel
   ↑                                        ↓
odom 缓存更新 ←── Gazebo 插件发布 /odom ←── diff_drive 收到指令 → 轮子转 → 车身动
```

### 收尾：唤醒与等待

```
T=到达   call_sync() 的 done.wait() 被唤醒 → _drive 线程收尾（L300-306）：
        success=True → robot.status="arrived"
        None/失败    → robot.status="idle" + 警告（超时无响应 / move timeout）
        │
T=到达+ 上层 wait_arrival("agv_1", timeout=90)（L334-346）主线程轮询 status（0.1s 间隔）：
        status != "moving" → 立即返回最终状态（arrived / idle）
        一直 moving 到 timeout → 返回 "moving"（超时）
```

---

## 五、最容易踩的 3 个坑（对照本项目修正版）

### 坑 1：忘了启动 spin 线程 → 回调永远不触发

```python
# ❌ 只创建 node 不 spin：永远收不到消息
node.create_subscription(Odometry, '/odom', callback, 10)

# ✅ 本项目写法：executor + 专用 spin 线程
executor = SingleThreadedExecutor(); executor.add_node(node)
threading.Thread(target=lambda: executor.spin_once(timeout_sec=0.1), daemon=True).start()
```

> 本项目两处都已内置：`GazeboBackend.__init__`（L78-84）与 `MoveToServer.spin()`（L148-151）。daemon 线程 + `_running` 标志保证 close() 能正常收尾（L105-119：先停 spin 再 join 2s，再 rclpy.shutdown()）。

### 坑 2：阻塞式移动回调会卡死 odom 更新？

```python
# ⚠️ 单线程 executor 下：回调里长时间循环 → 其他回调全部饿死（odom 冻结 → pos 不动 → 死等）
# ✅ 本项目解法（sim_gazebo_srv.py L68-80）：
#    • srv/odom 各自独立 MutuallyExclusiveCallbackGroup
#    • executor = MultiThreadedExecutor(3)
#    → 移动回调阻塞 100s 期间，odom 缓存仍持续更新
```

### 坑 3：车刚 spawn 就 move 会"尚无 odom 数据"？

```python
# ✅ 已内置，无需手动等（sim_gazebo.py L180-188）：
#    create_robot spawn 后自动等待首条 odom（15s deadline，每 0.2s 探测）
#    + 自检 cmd_vel 订阅者（L190-200）
#    只有 15s 内仍未收到才打警告；此时再调 move_robot 才会返回 error
```

---

## 六、一句话总结

> **`move_robot()`（业务进程）→ 防穿模校验 → 后台线程发 Service 请求 → MoveToServer 进程的 20Hz 控制环（读 odom 缓存 → 发 cmd_vel → Gazebo 轮子动 → 插件回 odom）→ 到站停车返回 response → 唤醒调用线程置 status=arrived → `wait_arrival()` 轮询到结果。**

核心是**两个进程各司其职**：业务进程的 spin 线程让"耳朵嘴巴活起来"，MoveToServer 的**多线程 executor + 独立回调组**保证"边开车边听 odom"；Service 的阻塞等待实现"一问一答"的同步效果。

---

## 附：删除流程（remove_robot，`sim_gazebo.py` L210-250）

```python
# 最多重试 3 次（delete_entity 偶发 DDS 发现延迟，L215-230）
for attempt in range(1, 4):
    result = subprocess.run(["ros2", "service", "call", "/delete_entity",
                             "gazebo_msgs/srv/DeleteEntity", f"{{name: '{robot_id}'}}"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode == 0: break                          # 删除成功
    if "no such model" in out or "not exist" in out: break    # 已删过（首轮超时但服务端处理了）→ 视为成功
    time.sleep(2.0)                                           # 否则重试
# 3 次仍失败 → 警告"下轮 spawn 会自动清理"，但不阻塞（本地 dict 照常 pop）
```

demo 结束或 ^C 中断时：`sim.reset()`（L94-99）遍历删车 → `sim.close()`（L105-119）停 spin → `rclpy.shutdown()`。
