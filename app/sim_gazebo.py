"""
Gazebo/ROS 2 仿真后端 — SimBackend 接口的 Gazebo 实现

架构：
    GazeboBackend（本文件）
      ├── Ros2Robot ×N（app/sim_gazebo_robot.py）
      └── MoveToClient ×N（app/sim_gazebo_srv.py）

启用方式：SIM_BACKEND=gazebo（get_sim() 读取环境变量切换，上层零改动）

注意：本模块依赖 rclpy（仅 ROS 2 环境可用）；rclpy 缺失时模块仍可被
import（不影响 SIM_BACKEND=pybullet 默认路径），实例化时才会报错。
"""

import math
import os
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

from app.logger import logger
from app.sim_backend import SimBackend
from app.sim_geometry import (
    WAREHOUSE_SIZE,
    ZONES,
    SHELF_POSITIONS,
    SHELF_SAFE_DISTANCE,
    ROBOT_COLORS,
    get_zone_name,
    check_path_clear,
)
from app.sim_gazebo_robot import Ros2Robot
from app.sim_gazebo_srv import MoveToClient

# AGV URDF 模型路径（与 PyBullet 后端共用同一文件）
_AGV_URDF_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "models", "agv.urdf")


class GazeboBackend(SimBackend):
    """Gazebo 仿真后端 — 实现 SimBackend 11 个方法"""

    _instance: Optional["GazeboBackend"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # rclpy 延迟导入（由 sim_gazebo_robot 检测；这里二次确认给出友好报错）
        try:
            import rclpy
            from rclpy.node import Node
        except ImportError as e:
            raise RuntimeError(
                "Gazebo 后端需要 ROS 2 环境（rclpy）：请在 osrf/ros:humble-desktop 等 "
                "ROS 2 环境中安装项目依赖后运行；或改用 SIM_BACKEND=pybullet"
            ) from e

        rclpy.init()
        self.node = Node("gazebo_backend")
        self.robots: Dict[str, Ros2Robot] = {}      # robot_id → Ros2Robot
        self.move_clients: Dict[str, MoveToClient] = {}  # robot_id → MoveToClient
        self.robot_speeds: Dict[str, float] = {}     # robot_id → m/s
        self._move_lock = threading.Lock()
        self.mode = "gazebo"
        self._step_count = 0

        # 专用 executor + spin 线程：处理 odom/scan 订阅回调与 Service 响应
        # （rclpy spin 非线程安全，必须集中在单一线程）
        from rclpy.executors import SingleThreadedExecutor
        self._running = True
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self._spin_thread = threading.Thread(
            target=self._spin_loop, daemon=True, name="gz-executor-spin")
        self._spin_thread.start()
        logger.info(f"Gazebo 后端已启动 (urdf={_AGV_URDF_PATH})")

    def _spin_loop(self):
        """executor spin 循环（专用线程，退出标志受 _running 控制）"""
        while self._running:
            self.executor.spin_once(timeout_sec=0.1)

    # ========== 生命周期 ==========

    def reset(self):
        """重置仿真：清除所有机器人，保留场景"""
        for robot_id in list(self.robots.keys()):
            self.remove_robot(robot_id)
        self._step_count = 0
        logger.info("仿真已重置")

    def step(self, count: int = 1):
        """Gazebo 物理世界实时运行，无需手动推进"""
        self._step_count += count

    def close(self):
        """关闭后端"""
        self._running = False                        # 先停 executor spin 循环
        try:
            self._spin_thread.join(timeout=2.0)
        except Exception:
            pass
        try:
            import rclpy
            rclpy.shutdown()
        except Exception:
            pass
        GazeboBackend._instance = None
        self._initialized = False
        logger.info("Gazebo 后端已关闭")

    # ========== 机器人管理 ==========

    def create_robot(self, robot_id: str, x: float = 0.0, y: float = 0.0,
                     z: float = 0.117, yaw: float = 0.0, color: str = None) -> Dict:
        """
        创建一台 AGV：spawn agv.urdf（与 PyBullet 共用同一模型）+ 建 Ros2Robot/MoveToClient

        z 默认 0.117：轮底在车身中心下 0.115，此处比触地高度高 2mm，
        刚超过 ODE 接触生成阈值（min_depth 1mm）——既保证落地即产生接触
        （零穿透时接触判定不稳定、轮子无摩擦空转），又让落地冲击足够小。
        旧值 0.13（高出 1.5cm）落地冲击大，实测约 1/3 概率车轮接触异常
        （轮子卡死打滑、车漂移）。
        """
        if robot_id in self.robots:
            logger.warning(f"机器人 {robot_id} 已存在，返回现有实例")
            return self.get_robot_pose(robot_id)

        # 1) 通过 spawn_entity 在 Gazebo 中生成模型
        #    -robot_namespace 与 URDF diff_drive 插件配套：话题落在 /{robot_id}/cmd_vel、/{robot_id}/odom
        cmd = [
            "ros2", "run", "gazebo_ros", "spawn_entity.py",
            "-entity", robot_id,
            "-file", _AGV_URDF_PATH,
            "-x", str(x), "-y", str(y), "-z", str(z),
            "-Y", str(yaw),      # -Y 是绕 Z 轴 yaw（弧度或角度由版本决定）
            "-robot_namespace", robot_id,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            logger.error(f"{robot_id} spawn 超时 30s：/spawn_entity 服务无响应，"
                         "Gazebo 可能未启动")
            return {"error": "spawn 超时：Gazebo 未运行或 /spawn_entity 服务无响应"}
        if result.returncode != 0:
            # 同名 entity 残留（上次运行异常退出未清理）→ 先删除再重试一次（自愈）
            logger.warning(f"{robot_id} spawn 失败，清理同名残留后重试: "
                           f"{result.stderr.strip()[:120]}")
            try:
                subprocess.run(
                    ["ros2", "service", "call", "/delete_entity",
                     "gazebo_msgs/srv/DeleteEntity", f"{{name: '{robot_id}'}}"],
                    capture_output=True, text=True, timeout=15)
            except subprocess.TimeoutExpired:
                pass
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                logger.error(f"{robot_id} spawn 重试仍超时：Gazebo 服务无响应")
                return {"error": "spawn 超时：Gazebo 未运行或 /spawn_entity 服务无响应"}
            if result.returncode != 0:
                return {"error": f"spawn 失败: {result.stderr.strip()[:200]}"}

        # 2) 建 ROS 2 封装与 move_to 客户端
        robot = Ros2Robot(robot_id, self.node)
        client = MoveToClient(robot_id, self.node)
        self.robots[robot_id] = robot
        self.move_clients[robot_id] = client
        self.robot_speeds[robot_id] = 0.5

        # 3) 等待首条 odom 数据（diff_drive 插件启动后持续发布，spawn 后约 1-2s 到达；
        #    否则上层立刻 move_robot 会拿到"尚无 odom 数据"）
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if "error" not in robot.get_pose():
                break
            time.sleep(0.2)
        else:
            logger.warning(f"{robot_id} 15s 内未收到 odom 数据")

        # 4) 自检 cmd_vel 订阅者：0 = Gazebo diff_drive 插件没监听话题，指令无人接收
        try:
            result = subprocess.run(
                ["ros2", "topic", "info", f"/{robot_id}/cmd_vel", "-v"],
                capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            result = None
        if result is not None and "Subscription count: 0" in result.stdout:
            logger.warning(f"{robot_id} cmd_vel 无订阅者：diff_drive 插件未监听该话题")
        elif result is not None:
            logger.info(f"{robot_id} cmd_vel 话题已连接（订阅者存在）")

        logger.info(f"创建机器人: {robot_id} @ ({x}, {y}) color={color or 'default'}")
        return {
            "robot_id": robot_id,
            "position": [x, y, z],
            "color": color or "default",
            "yaw": yaw,
        }

    def remove_robot(self, robot_id: str) -> Dict:
        """删除一台机器人（delete_entity 服务）"""
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}
        try:
            result = subprocess.run(
                ["ros2", "service", "call", "/delete_entity", "gazebo_msgs/srv/DeleteEntity",
                 f"{{name: '{robot_id}'}}"],
                capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            logger.warning(f"{robot_id} delete_entity 超时：Gazebo 服务无响应")
            result = None
        if result is not None and result.returncode != 0:
            logger.warning(f"{robot_id} delete_entity 失败，Gazebo 中将残留该模型: "
                           f"{result.stderr.strip()[:120]}")
        with self._move_lock:
            self.robots.pop(robot_id, None)
            self.move_clients.pop(robot_id, None)
            self.robot_speeds.pop(robot_id, None)
        logger.info(f"已删除机器人: {robot_id}")
        return {"robot_id": robot_id, "status": "removed"}

    # ========== 机器人控制 ==========

    def move_robot(self, robot_id: str, x: float, y: float,
                   speed: float = 0.5) -> Dict:
        """
        移动 AGV 到目标位置（状态机：idle → moving → arrived）
        后台线程调用 move_to Service（阻塞），到达后状态置 arrived。
        返回结构与 PyBullet 后端一致。
        """
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}

        # 防穿模校验：与 PyBulletBackend 相同的逻辑（复用公共几何常量）
        for sx, sy in SHELF_POSITIONS:
            dist_to_shelf = math.hypot(x - sx, y - sy)
            if dist_to_shelf < SHELF_SAFE_DISTANCE:
                return {
                    "error": f"目标点 ({x}, {y}) 与货架 ({sx}, {sy}) 冲突，"
                             f"距离 {dist_to_shelf:.2f}m < 安全距离 {SHELF_SAFE_DISTANCE}m，拒绝移动防穿模"
                }

        robot = self.robots[robot_id]
        pose = robot.get_pose()
        if "error" in pose:
            return pose
        cur = pose["position"]

        # 路径防穿模：目标点合法 ≠ 直线路径合法（路径可能贴着货架经过）
        path_error = check_path_clear(cur[0], cur[1], x, y)
        if path_error:
            return {"error": f"{path_error}，拒绝移动防穿模（请分段绕行）"}

        distance = math.hypot(x - cur[0], y - cur[1])

        if distance < 0.001:
            robot.status = "arrived"
            return {
                "robot_id": robot_id,
                "position": [x, y, cur[2]],
                "distance": 0.0,
                "from": [round(cur[0], 2), round(cur[1], 2)],
                "status": "arrived",
                "message": "已在目标位置，无需移动",
            }

        with self._move_lock:
            robot.status = "moving"
            self.robot_speeds[robot_id] = speed

        # 后台线程调 Service（阻塞式 move_to），完成后更新状态
        def _drive():
            try:
                resp = self.move_clients[robot_id].call_sync(x, y, speed)
                with self._move_lock:
                    if resp is not None and resp.success:
                        robot.status = "arrived"
                    else:
                        robot.status = "idle"
                        reason = "超时无响应" if resp is None else resp.message
                        logger.warning(f"{robot_id} move_to 失败: {reason}")
            except Exception as e:
                with self._move_lock:
                    robot.status = "idle"
                logger.error(f"{robot_id} move_to 异常: {e}")

        threading.Thread(target=_drive, daemon=True, name=f"gz-move-{robot_id}").start()

        logger.info(f"{robot_id} 开始移动 → ({x:.2f}, {y:.2f}) 距离={distance:.2f}m speed={speed}m/s")
        return {
            "robot_id": robot_id,
            "position": [round(cur[0], 3), round(cur[1], 3), round(cur[2], 3)],
            "target": [x, y],
            "distance": round(distance, 2),
            "from": [round(cur[0], 2), round(cur[1], 2)],
            "status": "moving",
        }

    def move_robot_by_velocity(self, robot_id: str, vx: float, vy: float,
                               duration: float = 1.0) -> Dict:
        """通过速度控制 AGV（发布 /cmd_vel，仅支持前进/后退速度）"""
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}
        self.robots[robot_id].move_by_velocity(vx, duration)
        pose = self.robots[robot_id].get_pose()
        return {"robot_id": robot_id, "position": pose.get("position"),
                "status": self.robots[robot_id].status}

    def wait_arrival(self, robot_id: str, timeout: float = 60.0) -> str:
        """
        阻塞等待 AGV 到达（与 PyBullet 后端同构：轮询 status）
        Returns: 最终状态：arrived / moving（超时）/ idle
        """
        elapsed = 0.0
        while elapsed < timeout:
            robot = self.robots.get(robot_id)
            if robot is None or robot.status != "moving":
                return robot.status if robot else "idle"
            time.sleep(0.1)
            elapsed += 0.1
        return self.robots.get(robot_id).status if robot_id in self.robots else "moving"

    # ========== 状态查询 ==========

    def get_robot_pose(self, robot_id: str) -> Dict:
        """获取机器人位置和朝向（Ros2Robot 保证同构 dict）"""
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}
        return self.robots[robot_id].get_pose()

    def get_all_robots(self) -> List[Dict]:
        """获取所有机器人状态"""
        return [r.get_pose() for r in self.robots.values()]

    def get_scene_info(self) -> Dict:
        """获取场景信息（结构对齐 PyBullet 后端）"""
        return {
            "warehouse_size": WAREHOUSE_SIZE,
            "zones": {k: list(v) for k, v in ZONES.items()},
            "robot_count": len(self.robots),
            "obstacle_count": len(SHELF_POSITIONS),
            "step_count": self._step_count,
            "mode": self.mode,
        }

    # ========== 传感器 ==========

    def check_distance(self, robot_id: str, target_x: float, target_y: float) -> Dict:
        """计算机器人到目标点的距离（纯几何，复用 sim_geometry）"""
        pose = self.get_robot_pose(robot_id)
        if "error" in pose:
            return pose
        pos = pose["position"]
        dist = math.hypot(target_x - pos[0], target_y - pos[1])
        return {
            "robot_id": robot_id,
            "distance": round(dist, 2),
            "from": [round(pos[0], 2), round(pos[1], 2)],
            "to": [target_x, target_y],
        }

    def check_obstacle(self, robot_id: str, direction: str = "forward",
                       range_m: float = 1.0) -> Dict:
        """
        检查指定方向是否有障碍物（/scan 激光雷达）

        direction: forward/left/right/back，取对应扇区最小测距
        Returns: 与 PyBullet 后端同构的 dict
        """
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}

        ranges = self.robots[robot_id].get_scan_ranges()
        if ranges is None:
            return {"error": f"{robot_id} 尚无 /scan 数据"}

        n = len(ranges)
        # 360° 扫描按方向切扇区（默认 0° 为车头前方）
        sector = {"forward": (0.875, 0.125), "back": (0.375, 0.625),
                  "left": (0.125, 0.375), "right": (0.625, 0.875)}
        lo_frac, hi_frac = sector.get(direction, (0.875, 0.125))
        idx_lo, idx_hi = int(n * lo_frac), int(n * hi_frac)
        if idx_lo < idx_hi:
            sector_ranges = ranges[idx_lo:idx_hi]
        else:  # 跨 0°（前方扇区）
            sector_ranges = ranges[idx_lo:] + ranges[:idx_hi]

        valid = [r for r in sector_ranges if r > 0.01]   # 过滤无效测量
        if not valid:
            return {"robot_id": robot_id, "obstacle_detected": False,
                    "direction": direction, "range": range_m}
        min_dist = min(valid)
        return {
            "robot_id": robot_id,
            "obstacle_detected": min_dist < range_m,
            "distance": round(min_dist, 2),
            "direction": direction,
        }
