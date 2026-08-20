# 第 5-6 周：Gazebo + ROS 2 入门 —— 详细拆解与实现说明

> 配套代码：`scripts/ros2_examples/`（W5 示例）、`app/sim_gazebo*.py`（W6 实现）
> 前置改造已完成：`SimBackend` 接口（`app/sim_backend.py`）、公共几何（`app/sim_geometry.py`）、
> AGV URDF 模型（`app/models/agv.urdf`）、`SIM_BACKEND` 后端开关（`app/sim_engine.py`）。

## 总体架构

```
Agent (tools.py / sim_api.py 零改动)
  └── get_sim() 按 SIM_BACKEND 环境变量选择
        ├── PyBulletBackend（默认，app/sim_engine.py）
        └── GazeboBackend（W6-3，app/sim_gazebo.py）
              ├── Ros2Robot ×N（W6-1，app/sim_gazebo_robot.py）
              └── MoveToClient（W6-2，app/sim_gazebo_srv.py）
共享：app/sim_geometry.py（几何常量）+ app/models/agv.urdf（同一模型双引擎加载）
```

---

## W5-1：ROS 2 环境搭建

**目标**：在 Docker 里跑起 ROS 2 Humble，验证话题机制。

```bash
# 1. 拉取官方镜像（桌面版，含 rviz2/gazebo 依赖）
docker pull osrf/ros:humble-desktop

# 2. 起交互容器
docker run -it --rm --name ros2_test osrf/ros:humble-desktop bash

# 3. 容器内每次新开终端都要 source 环境
source /opt/ros/humble/setup.bash

# 4. 验证：查看系统话题（应看到 /rosout 和 /parameter_events）
ros2 topic list
```

- `/rosout`：所有节点日志汇聚话题（logging）
- `/parameter_events`：节点参数变更通知话题
- `ros2 node list` / `ros2 node info /xxx` 配合查看节点关系

**验收**：`ros2 topic list -t` 能列出话题及其消息类型（如 `[rcl_interfaces/msg/Log]`）。

---

## W5-2：Topic / Node 发布订阅模式

**目标**：手写最小发布者与订阅者，理解三步结构（创建节点 → 创建 pub/sub → 发布/回调）。

**代码**：`scripts/ros2_examples/talker.py`、`scripts/ros2_examples/listener.py`

```python
# talker.py（核心结构）
class Talker(Node):
    def __init__(self):
        super().__init__('talker')                            # 1. 创建节点
        self.pub = self.create_publisher(String, 'chatter', 10)  # 2. 创建发布者
        self.create_timer(0.5, self.cb)                       # 定时触发
    def cb(self):
        msg = String(); msg.data = 'hello ros2'
        self.pub.publish(msg)                                 # 3. 发布
```

```python
# listener.py（核心结构）
class Listener(Node):
    def __init__(self):
        super().__init__('listener')
        self.sub = self.create_subscription(String, 'chatter', self.cb, 10)  # 订阅+回调
    def cb(self, msg):
        self.get_logger().info(f'收到: {msg.data}')
```

**调试命令**：
```bash
ros2 run my_pkg talker &       # 起发布者
ros2 run my_pkg listener       # 起订阅者
ros2 topic echo /chatter       # 第三方旁观
ros2 topic hz /chatter         # 看发布频率
```

**关键概念**：
- `create_publisher(消息类型, 话题名, QoS深度)`，QoS 深度=10 表示缓冲 10 条
- `/cmd_vel` 消息类型是 `geometry_msgs/msg/Twist`，用法与 `String` 完全一样

**验收**：两个终端一个发一个收，第三个终端 `echo` 旁观。

---

## W5-3：Gazebo 启动 + URDF 结构解剖

**目标**：跑起 Gazebo，用项目自己的 `app/models/agv.urdf` 学习 URDF 三要素。

```bash
# 安装 gazebo_ros（humble）
sudo apt update && sudo apt install -y ros-humble-gazebo-ros-pkgs

# 启动 Gazebo（先空场景）
ros2 launch gazebo_ros gazebo.launch.py

# 另开终端 spawn 模型
ros2 run gazebo_ros spawn_entity.py -entity agv -file /path/to/app/models/agv.urdf -x 0 -y 0
```

**用 agv.urdf 做解剖**：

| URDF 要素 | agv.urdf 中的对应 | 作用 |
|---|---|---|
| `link` | `base_link`（车身）、`wheel_fl/fr/bl/br`（4 轮） | 刚体单元 |
| `visual` | `<box size="0.7 0.4 0.16"/>`、`<cylinder radius="0.06" length="0.03"/>` | 渲染外观 |
| `collision` | 同 geometry | 碰撞检测（可简化，不影响外观） |
| `inertial` | `mass=1.0` + 6 个惯量分量 | 物理属性（Gazebo 必需） |
| `joint`（continuous） | `wheel_fl_joint` 等 4 个（axis 沿 Y） | 后轮驱动、前轮从动（diff_drive 插件） |
| `gazebo` | `libgazebo_ros_diff_drive.so` 插件块 | 订阅 /cmd_vel、发布 /odom（PyBullet 忽略此标签） |
| `origin` | `xyz="0.18 0.13 -0.055"` | 子 link 相对父 link 位姿 |

- 惯量公式（box）：`Ixx = m/12·(y²+z²)`、`Iyy = m/12·(x²+z²)`、`Izz = m/12·(x²+y²)`——agv.urdf 里的 `0.01547/0.04297/0.05417` 由此算出
- turtlebot3 用 `xacro`（宏模板），本项目先用纯 URDF 起步

**验收**：能讲清 agv.urdf 每个标签；spawn 后 `gz model --list` 看到 `agv`。

---

## W5-4：Python Node 控制移动（/cmd_vel）

**目标**：发 `/cmd_vel` 让车动起来。代码：`scripts/ros2_examples/cmd_vel_publisher.py`

> **用什么车？** 本任务用 ROS 2 官方学习机器人 turtlebot3（`sudo apt install ros-humble-turtlebot3-gazebo`），
> 它自带 diff_drive 插件订阅 `/cmd_vel`。**本项目没有 turtlebot 实现**——项目自己的
> `app/models/agv.urdf` 已带 `libgazebo_ros_diff_drive` 插件（订阅 `/cmd_vel`、发布 `/odom`），
> 学完本任务后可直接用 agv 复现，两者用法完全一致。

```python
class CmdVelPublisher(Node):
    def __init__(self):
        super().__init__('cmd_vel_pub')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)

    def go(self, vx=0.2, seconds=5.0):
        msg = Twist()
        msg.linear.x = vx            # 前进速度
        # msg.angular.z = 0.5        # 可加旋转（rad/s）
        self.pub.publish(msg)
        self.create_timer(seconds, self.stop)   # 定时停车

    def stop(self):
        self.pub.publish(Twist())    # 全零 = 停
```

**要点**：
- `Twist` 六字段：`linear.x/y/z` + `angular.x/y/z`，差分小车只用 `linear.x` 和 `angular.z`
- 停止 = 发布全零 Twist（ROS 2 约定）
- **对应本项目**：这就是 `SimBackend.move_robot_by_velocity()` 的 Gazebo 底层实现

**验收**：车前进 5s 后停下；`ros2 topic echo /cmd_vel` 看到消息流。

---

## W5-5：读 `/odom` 获取位置

**目标**：订阅里程计话题实时拿 x/y/yaw——Gazebo 版 `get_robot_pose()` 的数据源。代码：`scripts/ros2_examples/odom_reader.py`

```python
class OdomReader(Node):
    def __init__(self):
        super().__init__('odom_reader')
        self.sub = self.create_subscription(Odometry, '/odom', self.cb, 10)

    def cb(self, msg: Odometry):
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        siny = 2.0 * (ori.w * ori.z + ori.x * ori.y)
        cosy = 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z)
        yaw = math.atan2(siny, cosy)     # 四元数 → yaw
```

**要点**：
- `nav_msgs/msg/Odometry` 层级：`pose.pose.position` / `pose.pose.orientation`
- **对应关系**：`get_robot_pose()` 返回 `{position, yaw, zone, ...}` —— Gazebo 后端 = 本回调缓存 + `sim_geometry.get_zone_name()`

**验收**：W5-4 的车跑起来时本节点实时打印坐标变化。

---

## W6-1：封装 `Ros2Robot` 类

> 计划表原文"对应 SimEngine"已过时。现在：`Ros2Robot` 对应 PyBullet 的 **body_id 层**，
> 上层统一是 `SimBackend` 接口。

**代码**：`app/sim_gazebo_robot.py`

```python
class Ros2Robot:
    """单台 AGV 的 ROS 2 封装"""

    def __init__(self, robot_id: str, node: Node):
        self.robot_id = robot_id
        self.node = node                       # 共享一个 Node（多车共用，轻量）
        self.cmd_pub = node.create_publisher(Twist, f'/{robot_id}/cmd_vel', 10)
        self.odom_sub = node.create_subscription(Odometry, f'/{robot_id}/odom', self._on_odom, 10)
        self.scan_sub = node.create_subscription(LaserScan, f'/{robot_id}/scan', self._on_scan, 10)
        self._pose = None                      # 最新位姿缓存 (x, y, yaw)
        self._scan = None                      # 最新激光数据缓存
        self.status = 'idle'                   # 状态机：idle/moving/arrived

    def get_pose(self) -> dict:
        """返回与 PyBullet 后端同构的位姿 dict（契约一致）"""
        ...
    def move_by_velocity(self, vx: float, duration: float):
        """发 /cmd_vel 前进（对应 move_robot_by_velocity）"""
        ...
    def get_scan_ranges(self) -> list:
        """返回最近一次 /scan 的测距数组（对应 check_obstacle 数据源）"""
        ...
```

**设计决策**：
- **单 Node 多车**：话题用 `/{robot_id}/cmd_vel`、`/{robot_id}/odom`、`/{robot_id}/scan` 命名空间区分
- **位姿缓存**：odom 回调 ~100Hz，查询时读缓存不阻塞
- **状态机**：`idle/moving/arrived` 与 PyBullet 后端语义一致

**验收**：Gazebo 里 spawn 2 台车，分别驱动，`get_pose()` 各自返回正确 zone。

---

## W6-2：ROS 2 Service 封装 `move_to` 同步调用

**目标**：`move_robot` + `wait_arrival` 的"发起→阻塞等待→返回"语义，用 Service 天然实现。

**第 1 步：定义 Service 接口**（ROS 2 包 `sim_interfaces`，随文档附参考：`docs/ros2/sim_interfaces/srv/MoveTo.srv`）

```
float64 target_x
float64 target_y
float64 speed
---
bool success
string message
```

编译：`colcon build --packages-select sim_interfaces` 后 `source install/setup.bash`。

**第 2 步：服务端**（`app/sim_gazebo_srv.py` 中 `MoveToServer`）

```python
class MoveToServer(Node):
    def handle(self, request, response):
        """Service 回调：阻塞式移动到目标，到达后才返回"""
        rate = self.create_rate(20)                    # 20Hz 控制环
        while rclpy.ok():
            dist = math.hypot(request.target_x - self.pos[0],
                              request.target_y - self.pos[1])
            if dist < 0.05:                            # 到达阈值
                self.cmd_pub.publish(Twist())          # 停车
                response.success = True; response.message = 'arrived'
                return response                        # ← client 此刻才解除阻塞
            msg = Twist()
            msg.linear.x = min(request.speed, dist * 2)  # 接近时减速
            self.cmd_pub.publish(msg)
            rate.sleep()
```

**第 3 步：客户端同步封装**（`MoveToClient.call_sync`）

```python
def call_sync(self, x, y, speed):
    req = MoveTo.Request()
    req.target_x, req.target_y, req.speed = x, y, speed
    future = self.cli.call_async(req)                  # rclpy 只有异步 API
    rclpy.spin_until_future_complete(self, future)     # 手动转同步（阻塞）
    return future.result()
```

**要点**：
- `call_async` + `spin_until_future_complete` 是 ROS 2 的标准同步写法
- **对应契约**：`GazeboBackend.move_robot()` = 后台线程调 `call_sync`；`wait_arrival()` = 轮询 `Ros2Robot.status`

**验收**：
```bash
ros2 service call /agv_1/move_to sim_interfaces/srv/MoveTo "{target_x: 2.5, target_y: 2.5, speed: 0.5}"
# 命令挂起 → 车动 → 到达后返回 success=true
```

---

## W6-3：实现 `GazeboBackend`（11 方法全映射）

> 本任务已被热拔插改造提前解锁 80%：接口、开关、URDF、几何常量全部就位，
> 只差 `app/sim_gazebo.py` 这个实现文件（本次已生成骨架）。

**代码**：`app/sim_gazebo.py`（继承 `SimBackend`，实现全部 11 个抽象方法）

| SimBackend 方法 | Gazebo 实现方式 | 复用 |
|---|---|---|
| `reset` | 逐个 remove_robot | — |
| `step` | 空操作（Gazebo 实时物理） | — |
| `close` | `rclpy.shutdown()` | — |
| `create_robot` | spawn `agv.urdf` + 建 Ros2Robot | **URDF 复用** |
| `remove_robot` | delete_entity 服务 | — |
| `move_robot` | 防穿模校验 + 后台线程 move_to Service | **sim_geometry 校验复用** |
| `move_robot_by_velocity` | Ros2Robot | — |
| `wait_arrival` | 轮询 status（同 PyBullet 写法） | 逻辑复制 |
| `get_robot_pose` | Ros2Robot.get_pose | **get_zone_name** |
| `get_all_robots` | 列表推导 | — |
| `get_scene_info` | 常量拼装 | **sim_geometry** |
| `check_distance` | 纯几何 | **sim_geometry** |
| `check_obstacle` | `/scan` 激光雷达 | — |

**验收（三级）**：
1. `SIM_BACKEND=gazebo` 启动 API，`GET /api/sim/status` 正常
2. `scripts/test_sim.py` 全绿（同一份测试跑两个后端——热拔插的价值证明）
3. Agent 指令"agv_1去A取货→送D区"在 Gazebo 里完整执行（tools.py 零改动）

---

## W6-4：录制对比视频

1. **PyBullet 版**：`SIM_BACKEND=pybullet SIM_MODE=gui python3 scripts/sim_demo.py`，录制"agv_1去A取货→送D区"
2. **Gazebo 版**：`SIM_BACKEND=gazebo` + Gazebo GUI 同指令执行，录制
3. **并列剪辑**：左右分屏，加字幕标出两边工具调用日志（应完全一致）

**对比维度**：Agent 侧日志一致性 / 机器人轨迹（Gazebo 有真实摩擦惯性）/ 响应延迟

**验收**：证明"同一套 Agent，一行环境变量换引擎"。

---

## W6-5：博客/笔记大纲

```
标题：同一套 Agent，两种物理世界 —— SimBackend 接口让 PyBullet 换 Gazebo 只要一行环境变量

1. 背景：轻量验证（PyBullet）→ 高保真验证（Gazebo）
2. 核心设计：SimBackend 11 方法契约 / sim_geometry 公共几何 / agv.urdf 复用
3. 改造对比：改前 SimEngine 暴露 PyBullet 细节 → 改后 get_sim() 一行切换
4. 难点：状态机等价（wait_arrival）、激光雷达（rayTest → /scan）、防穿模校验复用
5. 数据：同指令耗时 / 轨迹偏差 / 物理保真度
6. 结论：接口抽象先行的收益
```

---

# 测试说明

## 环境要求

| 测试范围 | 环境 | 依赖 |
|---|---|---|
| W5 示例（scripts/ros2_examples/） | `osrf/ros:humble-desktop` 容器 | rclpy（镜像自带） |
| W6 实现（app/sim_gazebo*.py） | ROS 2 环境 + 本项目代码 | rclpy + gazebo_ros + sim_interfaces |
| PyBullet 回归 | 现有 API 容器 | 无新增依赖（默认路径不受影响） |

## W5 示例测试（学习容器内）

```bash
# 在 osrf/ros:humble-desktop 容器内
source /opt/ros/humble/setup.bash
cd /path/to/scripts/ros2_examples

# W5-2：两个终端分别跑（chatter 话题）
python3 talker.py     # 终端 1
python3 listener.py   # 终端 2 → 每 0.5s 打印"收到: hello ros2"

# W5-4（需 Gazebo + 车模型运行中）
python3 cmd_vel_publisher.py   # 车前进 5s 后停

# W5-5（需 odom 话题存在）
python3 odom_reader.py         # 实时打印 x/y/yaw
```

## W6 实现测试（ROS 2 + Gazebo 环境）

```bash
# 1. 编译 sim_interfaces（MoveTo.srv）
cd ~/ros2_ws/src && mkdir -p sim_interfaces && cp docs/ros2/sim_interfaces/* sim_interfaces/ -r
colcon build --packages-select sim_interfaces
source install/setup.bash

# 2. 起 Gazebo + spawn agv（同一 URDF！带 -robot_namespace 区分话题）
ros2 launch gazebo_ros gazebo.launch.py &
ros2 run gazebo_ros spawn_entity.py -entity agv_1 -file app/models/agv.urdf \
    -x 0 -y 0 -robot_namespace agv_1

# 2.5 为每台车起 move_to 服务端（独立进程，新终端）
cd /path/to/project
python3 scripts/ros2_examples/start_move_to_server.py agv_1

# 2.6 验证车已通电：能看到 /agv_1/cmd_vel 和 /agv_1/odom 话题
ros2 topic list | grep agv_1

# 3. 跑本项目（SIM_BACKEND 切换后端）
SIM_BACKEND=gazebo python3 -c "
from app.sim_engine import get_sim
sim = get_sim()                          # → GazeboBackend
print(sim.create_robot('agv_1', 0, 0))
print(sim.move_robot('agv_1', 2.5, 2.5))
print(sim.wait_arrival('agv_1'))
print(sim.get_robot_pose('agv_1'))
"

# 4. 同一份验证脚本跑两个后端对比
SIM_BACKEND=pybullet python3 scripts/verify_sim_backends.py
SIM_BACKEND=gazebo   python3 scripts/verify_sim_backends.py
```

## PyBullet 回归（现有容器，每次改造后必跑）

```bash
# Windows 侧改完代码同步后，容器内：
python3 scripts/test_sim.py          # 现有 4 项验证
# 或快速冒烟：
python3 -c "
from app.sim_engine import get_sim
sim = get_sim()
r = sim.create_robot('agv_test', 0, 0, color='blue')
r = sim.move_robot('agv_test', -2.5, 2.5); sim.wait_arrival('agv_test')
assert sim.get_robot_pose('agv_test')['zone'] == 'B'
r = sim.move_robot('agv_test', -3.0, 0.0)
assert 'error' in r, '防穿模应拒绝'
print('PYBULLET_REGRESSION_OK')
"
```

## 关键验收清单

- [ ] W5-2：talker/listener 互通，echo 旁观
- [ ] W5-3：agv.urdf 在 Gazebo 成功 spawn
- [ ] W5-4/5：车动起来 + odom 实时坐标
- [ ] W6-2：`ros2 service call /agv_1/move_to` 同步返回
- [ ] W6-3：`SIM_BACKEND=gazebo` 下 `test_sim.py` 全绿
- [ ] W6-3：同一条 Agent 指令两后端执行一致
- [ ] PyBullet 默认路径无回归（`SIM_BACKEND` 未设置时一切照旧）
