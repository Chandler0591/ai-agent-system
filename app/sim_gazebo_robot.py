"""
Ros2Robot — 单台 AGV 的 ROS 2 封装

对应关系：
    Ros2Robot 对应 PyBullet 后端的 body_id 层（单台车操作），
    上层统一是 SimBackend 接口（app/sim_backend.py）。

设计决策：
- 单 Node 多车：所有 Ros2Robot 共享一个 rclpy.Node，
  话题用 /{robot_id}/cmd_vel、/{robot_id}/odom、/{robot_id}/scan 命名空间区分
- 位姿/雷达缓存：odom/scan 回调高频，查询时读缓存不阻塞
- 状态机：idle/moving/arrived，与 PyBullet 后端语义一致

注意：本模块依赖 rclpy（仅 ROS 2 环境可用）；rclpy 缺失时模块仍可被
import（不影响 SIM_BACKEND=pybullet 默认路径），实例化时才会报错。
"""

import math
from typing import Dict, List, Optional, Tuple

from app.logger import logger
from app.sim_geometry import get_zone_name

try:
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import LaserScan
    _RCLPY_AVAILABLE = True
except ImportError:
    _RCLPY_AVAILABLE = False
    rclpy = None
    Node = object
    Twist = None
    Odometry = None
    LaserScan = None


class Ros2Robot:
    """单台 AGV 的 ROS 2 封装 — 对应 PyBullet 的 body_id 层"""

    def __init__(self, robot_id: str, node: "Node"):
        if not _RCLPY_AVAILABLE:
            raise RuntimeError(
                "rclpy 未安装：Ros2Robot 需要在 ROS 2 环境中运行"
                "（如 docker osrf/ros:humble-desktop）"
            )
        self.robot_id = robot_id
        self.node = node                                   # 共享一个 Node（多车共用，轻量）
        self.cmd_pub = node.create_publisher(
            Twist, f"/{robot_id}/cmd_vel", 10)
        self.odom_sub = node.create_subscription(
            Odometry, f"/{robot_id}/odom", self._on_odom, 10)
        self.scan_sub = node.create_subscription(
            LaserScan, f"/{robot_id}/scan", self._on_scan, 10)

        self._pose: Optional[Tuple[float, float, float]] = None   # (x, y, yaw_deg) 缓存
        self._scan_ranges: Optional[List[float]] = None           # 最近一次 /scan 测距
        self.status: str = "idle"                                 # idle/moving/arrived

    # ========== 话题回调 ==========

    def _on_odom(self, msg: "Odometry"):
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        siny = 2.0 * (ori.w * ori.z + ori.x * ori.y)
        cosy = 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z)
        yaw_deg = math.degrees(math.atan2(siny, cosy))
        self._pose = (pos.x, pos.y, yaw_deg)

    def _on_scan(self, msg: "LaserScan"):
        self._scan_ranges = list(msg.ranges)

    # ========== 控制 ==========

    def move_by_velocity(self, vx: float, duration: float = 1.0):
        """发 /cmd_vel 前进，duration 秒后自动停车（对应 move_robot_by_velocity）"""
        msg = Twist()
        msg.linear.x = vx
        self.cmd_pub.publish(msg)
        self.node.create_timer(duration, lambda: self.cmd_pub.publish(Twist()))
        logger.info(f"{self.robot_id} 速度控制: vx={vx} m/s, {duration}s")

    # ========== 查询 ==========

    def get_pose(self) -> Dict:
        """返回与 PyBullet 后端同构的位姿 dict（SimBackend 契约一致）"""
        if self._pose is None:
            return {"error": f"{self.robot_id} 尚无 odom 数据"}
        x, y, yaw_deg = self._pose
        return {
            "robot_id": self.robot_id,
            "position": [round(x, 3), round(y, 3), 0.0],
            "yaw": round(yaw_deg, 1),
            "zone": get_zone_name(x, y),      # 复用公共几何
            "color": "unknown",               # Gazebo 端颜色由模型材质决定
            "status": self.status,
        }

    def get_scan_ranges(self) -> Optional[List[float]]:
        """最近一次 /scan 测距数组（对应 check_obstacle 数据源）"""
        return self._scan_ranges
