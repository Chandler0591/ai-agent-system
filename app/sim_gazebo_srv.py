"""
move_to ROS 2 Service — 同步移动调用封装

对应关系：
    MoveToServer.handle_move_request() 阻塞式移动到目标 ≈ SimBackend.move_robot() + wait_arrival()
    MoveToClient.call_sync() 是 rclpy 异步 API 手动转同步的标准写法

前置条件：
    1. 编译 sim_interfaces 包（MoveTo.srv 参考 docs/ros2/sim_interfaces/srv/MoveTo.srv）
       colcon build --packages-select sim_interfaces && source install/setup.bash
    2. Gazebo 中已 spawn 对应 robot_id 的模型（话题 /{robot_id}/cmd_vel、/{robot_id}/odom）

注意：本模块依赖 rclpy（仅 ROS 2 环境可用）；rclpy 缺失时模块仍可被
import（不影响 SIM_BACKEND=pybullet 默认路径），实例化时才会报错。
"""

import math
import threading
import time

from app.logger import logger

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    _RCLPY_AVAILABLE = True
except ImportError:
    _RCLPY_AVAILABLE = False
    rclpy = None
    Node = object
    MutuallyExclusiveCallbackGroup = None
    MultiThreadedExecutor = None
    Twist = None
    Odometry = None

# sim_interfaces 为自定义 ROS 2 包（需先 colcon build）
try:
    from sim_interfaces.srv import MoveTo
    _MOVE_TO_AVAILABLE = True
except ImportError:
    _MOVE_TO_AVAILABLE = False
    MoveTo = None


class MoveToServer(Node):
    """
    move_to 服务端：阻塞式移动到目标点，到达后才返回 response

    运行：python3 -c "from app.sim_gazebo_srv import MoveToServer; MoveToServer.spin('agv_1')"
    """

    def __init__(self, robot_id: str):
        if not _RCLPY_AVAILABLE:
            raise RuntimeError("rclpy 未安装：需要在 ROS 2 环境中运行")
        if not _MOVE_TO_AVAILABLE:
            raise RuntimeError(
                "sim_interfaces 未安装：请先 colcon build 编译 MoveTo.srv"
            )
        super().__init__(f"move_to_server_{robot_id}")
        self.robot_id = robot_id
        # 注意：回调名不能叫 handle —— rclpy.Node 基类有同名 property，
        # 子类同名方法会覆盖它，导致 Node.__init__ 的 with self.handle 报错
        #
        # 移动回调互斥串行：同一辆车同时只有一个移动指令在执行，第二个请求
        # 排队等前一个结束（同步 Service 语义）。odom 订阅用独立回调组，
        # 移动循环阻塞期间位置/朝向缓存仍持续更新（否则 pos 冻结死等）
        self.srv = self.create_service(
            MoveTo, f"/{robot_id}/move_to", self.handle_move_request,
            callback_group=MutuallyExclusiveCallbackGroup())
        self.cmd_pub = self.create_publisher(
            Twist, f"/{robot_id}/cmd_vel", 10)
        self.pos = None                                           # (x, y) 缓存
        self.yaw = 0.0                                            # 车头朝向（弧度）缓存
        self.create_subscription(
            Odometry, f"/{robot_id}/odom", self._on_odom, 10,
            callback_group=MutuallyExclusiveCallbackGroup())
        logger.info(f"move_to 服务已注册: /{robot_id}/move_to")

    def _on_odom(self, msg: "Odometry"):
        p = msg.pose.pose.position
        o = msg.pose.pose.orientation
        siny = 2.0 * (o.w * o.z + o.x * o.y)
        cosy = 1.0 - 2.0 * (o.y * o.y + o.z * o.z)
        if self.pos is None:
            logger.info(f"{self.robot_id} 收到首条 odom: ({p.x:.2f}, {p.y:.2f})")
        self.pos = (p.x, p.y)
        self.yaw = math.atan2(siny, cosy)

    def handle_move_request(self, request, response):
        """Service 回调：先转向对准目标再前进，到达后才返回（client 同步解除阻塞）"""
        logger.info(f"{self.robot_id} 收到 move_to 请求 → "
                    f"({request.target_x}, {request.target_y}), 当前位置 {self.pos}")
        if self.pos is None:
            response.success = False
            response.message = "尚无 odom 数据"
            logger.warning(f"{self.robot_id} 尚无 odom 数据，直接拒绝请求")
            return response

        rate = self.create_rate(20)                               # 20Hz 控制环
        # 单次移动最长 100s：必须小于客户端 call_sync 的 120s 超时，
        # 否则上一轮移动未结束、新一轮请求排队，客户端先超时放弃
        deadline = time.time() + 100.0
        last_log = 0.0
        while rclpy.ok():
            if time.time() > deadline:
                self.cmd_pub.publish(Twist())                     # 停车
                response.success = False
                response.message = "move timeout"
                logger.warning(f"{self.robot_id} 移动超时（未到达目标）")
                return response
            dx = request.target_x - self.pos[0]
            dy = request.target_y - self.pos[1]
            dist = math.hypot(dx, dy)
            if dist < 0.05:                                       # 到达阈值 5cm
                self.cmd_pub.publish(Twist())                     # 停车
                response.success = True
                response.message = "arrived"
                logger.info(f"{self.robot_id} 到达目标 ({request.target_x}, {request.target_y})")
                return response
            # 转向 + 前进闭环：先原地转向对准目标方向，前进途中持续纠偏
            target_yaw = math.atan2(dy, dx)
            yaw_err = math.atan2(math.sin(target_yaw - self.yaw),
                                 math.cos(target_yaw - self.yaw))  # 归一化到 [-π, π]
            msg = Twist()
            if abs(yaw_err) > 0.15:                               # 朝向差 > ~9°：原地转向
                msg.angular.z = max(-1.0, min(1.0, 2.0 * yaw_err))
            else:
                msg.linear.x = min(request.speed, dist * 2)       # 接近时减速
                msg.angular.z = max(-0.8, min(0.8, 2.0 * yaw_err))
            # 每 5s 打印一次进度（诊断用：pos 不变 = 车没动 / 无进度 = 请求没到）
            if time.time() - last_log >= 5.0:
                last_log = time.time()
                logger.info(f"{self.robot_id} 移动中: pos=({self.pos[0]:.2f}, {self.pos[1]:.2f}), "
                            f"yaw={math.degrees(self.yaw):.0f}°, 距目标 {dist:.2f}m")
            self.cmd_pub.publish(msg)
            rate.sleep()

    @classmethod
    def spin(cls, robot_id: str):
        """独立进程运行入口（多线程 executor：阻塞式移动回调与 odom 订阅并行）"""
        rclpy.init()
        server = cls(robot_id)
        # 3 线程：1 个阻塞式移动回调 + 1 个 odom 订阅 + 1 个缓冲
        executor = MultiThreadedExecutor(num_threads=3)
        executor.add_node(server)
        try:
            executor.spin()
        finally:
            server.destroy_node()
            rclpy.shutdown()


class MoveToClient:
    """
    move_to 客户端：call_sync() 同步阻塞调用（供 GazeboBackend.move_robot 使用）
    """

    def __init__(self, robot_id: str, node: "Node"):
        if not _RCLPY_AVAILABLE:
            raise RuntimeError("rclpy 未安装：需要在 ROS 2 环境中运行")
        if not _MOVE_TO_AVAILABLE:
            raise RuntimeError(
                "sim_interfaces 未安装：请先 colcon build 编译 MoveTo.srv"
            )
        self.robot_id = robot_id
        self.node = node
        self.cli = node.create_client(MoveTo, f"/{robot_id}/move_to")
        # 等服务端上线（最多等 10s）
        deadline = node.get_clock().now().to_msg().sec + 10
        while not self.cli.wait_for_service(timeout_sec=1.0):
            logger.warning(f"等待 move_to 服务上线: /{robot_id}/move_to ...")
            if node.get_clock().now().to_msg().sec > deadline:
                raise RuntimeError(f"move_to 服务超时未上线: /{robot_id}/move_to")

    def call_sync(self, x: float, y: float, speed: float = 0.5, timeout: float = 120.0):
        """
        同步调用 move_to。

        注意：不用 rclpy.spin_until_future_complete（spin 函数线程不安全，
        且本 Node 已挂在 GazeboBackend 的 executor 上），改为 future 回调 +
        Event 等待，可在任意线程调用（多车并发安全）。

        Returns: MoveTo.Response；超时返回 None
        """
        req = MoveTo.Request()
        req.target_x = x
        req.target_y = y
        req.speed = speed
        done = threading.Event()
        result_box: dict = {}

        future = self.cli.call_async(req)

        def _on_done(fut):
            try:
                result_box['resp'] = fut.result()
            except Exception as e:
                result_box['error'] = e
            finally:
                done.set()

        future.add_done_callback(_on_done)
        if not done.wait(timeout=timeout):
            logger.warning(f"{self.robot_id} move_to 超时 ({timeout}s)")
            return None
        return result_box.get('resp')
