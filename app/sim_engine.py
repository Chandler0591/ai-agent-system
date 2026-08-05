"""
PyBullet 仿真引擎 — AI 调度系统的物理世界接口

设计原则：
- 单例模式，全局唯一仿真实例
- DIRECT 模式默认（Docker/服务器无头运行），GUI 模式按需开启
- 每个 AGV = 一个带颜色的方盒（后续可替换为 URDF 模型）
- 接口稳定：后续换 Gazebo/Isaac Sim 只需替换此类实现
"""

import os
import math
import json
from typing import Dict, List, Optional, Tuple

import pybullet as p
import pybullet_data

from app.logger import logger

# ========== 仓库场景常量 ==========
WAREHOUSE_SIZE = 10.0          # 仓库边长（米）
ROBOT_COLORS = {
    "red":    [1.0, 0.2, 0.2, 1.0],
    "blue":   [0.2, 0.4, 1.0, 1.0],
    "green":  [0.2, 0.8, 0.3, 1.0],
    "orange": [1.0, 0.6, 0.1, 1.0],
    "purple": [0.7, 0.3, 0.9, 1.0],
}

# 区域定义（A/B/C/D 四象限）
ZONES = {
    "A": ( 2.5,  2.5),
    "B": (-2.5,  2.5),
    "C": (-2.5, -2.5),
    "D": ( 2.5, -2.5),
}


class SimEngine:
    """仿真引擎单例 — Agent 通过此类控制物理世界"""

    _instance: Optional["SimEngine"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 从环境变量读取模式：SIM_MODE=gui 则开启窗口
        self.mode = os.getenv("SIM_MODE", "direct")
        self.client_id: int = -1
        self.robots: Dict[str, int] = {}       # robot_id → PyBullet body id
        self.obstacles: Dict[str, int] = {}     # obstacle_id → PyBullet body id
        self.robot_colors: Dict[str, list] = {} # robot_id → RGBA
        self._color_index = 0
        self._ground_id: int = -1
        self._step_count: int = 0

        self._connect()
        self._setup_scene()
        logger.info(f"仿真引擎已启动 (mode={self.mode}, client={self.client_id})")

    # ========== 生命周期 ==========

    def _connect(self):
        """连接 PyBullet 物理引擎"""
        try:
            if self.mode == "gui":
                self.client_id = p.connect(p.GUI)
            else:
                self.client_id = p.connect(p.DIRECT)
            p.setAdditionalSearchPath(pybullet_data.getDataPath())
            logger.info(f"PyBullet 连接成功 (client_id={self.client_id})")
        except Exception as e:
            logger.error(f"PyBullet 连接失败: {e}")
            raise

    def _setup_scene(self):
        """初始化仓库场景：地面 + 边界标记"""
        p.setGravity(0, 0, -9.8)
        p.setTimeStep(1.0 / 240.0)

        # 地面
        self._ground_id = p.loadURDF("plane.urdf")

        # 仓库地面纹理（半透明大平面）
        ground_visual = p.createVisualShape(
            shapeType=p.GEOM_BOX,
            halfExtents=[WAREHOUSE_SIZE / 2, WAREHOUSE_SIZE / 2, 0.01],
            rgbaColor=[0.15, 0.15, 0.18, 1.0],
        )
        ground_body = p.createMultiBody(
            baseVisualShapeIndex=ground_visual,
            basePosition=[0, 0, -0.005],
        )

        # 货架（静态障碍物）
        shelf_positions = [
            ( 3.0,  0.0), (-3.0,  0.0),
            ( 0.0,  3.0), ( 0.0, -3.0),
        ]
        shelf_visual = p.createVisualShape(
            shapeType=p.GEOM_BOX,
            halfExtents=[0.8, 0.3, 1.0],
            rgbaColor=[0.5, 0.35, 0.2, 1.0],
        )
        shelf_collision = p.createCollisionShape(
            shapeType=p.GEOM_BOX,
            halfExtents=[0.8, 0.3, 1.0],
        )
        for i, (sx, sy) in enumerate(shelf_positions):
            body_id = p.createMultiBody(
                baseMass=0,  # 静态
                baseCollisionShapeIndex=shelf_collision,
                baseVisualShapeIndex=shelf_visual,
                basePosition=[sx, sy, 1.0],  # 2m高货架，中心在z=1.0，底贴地面
            )
            self.obstacles[f"shelf_{i}"] = body_id

        # 区域标记（A/B/C/D）
        zone_colors = {
            "A": [0.2, 0.7, 0.3, 0.3],
            "B": [0.2, 0.4, 1.0, 0.3],
            "C": [0.7, 0.3, 0.9, 0.3],
            "D": [1.0, 0.6, 0.1, 0.3],
        }
        for zone_name, (zx, zy) in ZONES.items():
            vis = p.createVisualShape(
                shapeType=p.GEOM_BOX,
                halfExtents=[1.2, 1.2, 0.005],
                rgbaColor=zone_colors.get(zone_name, [0.3, 0.3, 0.3, 0.2]),
            )
            body = p.createMultiBody(
                baseVisualShapeIndex=vis,
                basePosition=[zx, zy, 0.001],
            )
            self.obstacles[f"zone_{zone_name}"] = body

        logger.info(f"仓库场景已初始化 (货架={len(shelf_positions)}, 区域={len(ZONES)})")

    def reset(self):
        """重置仿真：清除所有机器人，保留场景"""
        for robot_id in list(self.robots.keys()):
            self.remove_robot(robot_id)
        self._step_count = 0
        logger.info("仿真已重置")

    def step(self, count: int = 1):
        """推进物理仿真 N 步"""
        for _ in range(count):
            p.stepSimulation()
            self._step_count += 1

    def close(self):
        """关闭仿真连接"""
        if self.client_id >= 0:
            p.disconnect(self.client_id)
            self.client_id = -1
            SimEngine._instance = None
            self._initialized = False
            logger.info("仿真连接已关闭")

    # ========== 机器人管理 ==========

    def create_robot(self, robot_id: str, x: float = 0.0, y: float = 0.0,
                     z: float = 0.1, yaw: float = 0.0, color: str = None) -> Dict:
        """
        创建一台 AGV

        Args:
            robot_id: 唯一 ID（如 "agv_1"）
            x, y, z: 初始位置
            yaw: 朝向角（度），0=东, 90=北, 180=西, 270=南
            color: red/blue/green/orange/purple，不传则自动分配

        Returns:
            {"robot_id": "agv_1", "position": [x, y, z], "color": "blue", "yaw": 0}
        """
        if robot_id in self.robots:
            logger.warning(f"机器人 {robot_id} 已存在，返回现有实例")
            return self.get_robot_pose(robot_id)

        # 分配颜色
        if color and color in ROBOT_COLORS:
            rgba = ROBOT_COLORS[color]
        else:
            color_names = list(ROBOT_COLORS.keys())
            color = color_names[self._color_index % len(color_names)]
            rgba = ROBOT_COLORS[color]
            self._color_index += 1

        # 创建 AGV 模型（带"轮子"的方盒）
        body_id = self._create_agv_body(x, y, z, yaw, rgba)

        self.robots[robot_id] = body_id
        self.robot_colors[robot_id] = rgba

        # 推进几步让物理稳定
        self.step(10)

        logger.info(f"创建机器人: {robot_id} @ ({x:.2f}, {y:.2f}) color={color}")
        return {
            "robot_id": robot_id,
            "position": [x, y, z],
            "color": color,
            "yaw": yaw,
        }

    def _create_agv_body(self, x: float, y: float, z: float, yaw: float, rgba: list) -> int:
        """创建 AGV 物理模型（带 4 个轮子）"""
        # 朝向（度 → 四元数）
        orientation = p.getQuaternionFromEuler([0, 0, math.radians(yaw)])

        # 车身
        body_visual = p.createVisualShape(
            shapeType=p.GEOM_BOX,
            halfExtents=[0.35, 0.2, 0.08],
            rgbaColor=rgba,
        )
        body_collision = p.createCollisionShape(
            shapeType=p.GEOM_BOX,
            halfExtents=[0.35, 0.2, 0.08],
        )

        body_id = p.createMultiBody(
            baseMass=1.0,
            baseCollisionShapeIndex=body_collision,
            baseVisualShapeIndex=body_visual,
            basePosition=[x, y, z + 0.12],
            baseOrientation=orientation,
        )

        # 4 个轮子（圆柱体，固定关节）
        wheel_visual = p.createVisualShape(
            shapeType=p.GEOM_CYLINDER,
            radius=0.06,
            length=0.03,
            rgbaColor=[0.1, 0.1, 0.1, 1.0],
        )
        wheel_positions = [
            ( 0.18,  0.13),  # 前左
            ( 0.18, -0.13),  # 前右
            (-0.18,  0.13),  # 后左
            (-0.18, -0.13),  # 后右
        ]
        for wx, wy in wheel_positions:
            p.createMultiBody(
                baseMass=0.1,
                baseVisualShapeIndex=wheel_visual,
                basePosition=[x + wx, y + wy, z + 0.065],
            )

        return body_id

    def remove_robot(self, robot_id: str) -> Dict:
        """删除一台机器人"""
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}
        body_id = self.robots.pop(robot_id)
        self.robot_colors.pop(robot_id, None)
        p.removeBody(body_id)
        logger.info(f"已删除机器人: {robot_id}")
        return {"robot_id": robot_id, "status": "removed"}

    # ========== 机器人控制 ==========

    def move_robot(self, robot_id: str, x: float, y: float,
                   speed: float = 0.5) -> Dict:
        """
        移动 AGV 到目标位置（瞬时传送）

        Args:
            robot_id: AGV ID
            x, y: 目标坐标
            speed: 移动速度（m/s，当前为瞬时传送，后续用于动画）

        Returns:
            {"robot_id": "...", "position": [x, y, z], "distance": 1.5}
        """
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}

        body_id = self.robots[robot_id]
        current_pos, current_ori = p.getBasePositionAndOrientation(body_id)

        # 计算距离和运动方向
        dx, dy = x - current_pos[0], y - current_pos[1]
        distance = math.sqrt(dx * dx + dy * dy)

        # 朝向自动对齐运动方向（atan2(Δy, Δx) = 从东逆时针角度）
        if distance > 0.001:
            yaw = math.degrees(math.atan2(dy, dx))
        else:
            _, _, yaw = p.getEulerFromQuaternion(current_ori)
            yaw = math.degrees(yaw)
        target_ori = p.getQuaternionFromEuler([0, 0, math.radians(yaw)])

        # 瞬时传送（车头朝向运动方向）
        p.resetBasePositionAndOrientation(
            body_id,
            [x, y, current_pos[2]],
            target_ori,
        )
        self.step(5)

        logger.info(f"{robot_id} 移动到 ({x:.2f}, {y:.2f}) 距离={distance:.2f}m")
        return {
            "robot_id": robot_id,
            "position": [x, y, current_pos[2]],
            "distance": round(distance, 2),
            "from": [round(current_pos[0], 2), round(current_pos[1], 2)],
        }

    def move_robot_by_velocity(self, robot_id: str, vx: float, vy: float,
                                duration: float = 1.0) -> Dict:
        """
        通过速度控制 AGV（用于 Gazebo/Isaac Sim 迁移时接口一致）

        Args:
            robot_id: AGV ID
            vx, vy: 线速度 (m/s)
            duration: 持续时间 (秒)

        Returns:
            最终位置
        """
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}

        body_id = self.robots[robot_id]
        pos, _ = p.getBasePositionAndOrientation(body_id)
        target_x = pos[0] + vx * duration
        target_y = pos[1] + vy * duration

        return self.move_robot(robot_id, target_x, target_y)

    # ========== 状态查询 ==========

    def get_robot_pose(self, robot_id: str) -> Dict:
        """获取机器人位置和朝向"""
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}

        body_id = self.robots[robot_id]
        pos, ori = p.getBasePositionAndOrientation(body_id)
        # 四元数 → yaw
        _, _, yaw = p.getEulerFromQuaternion(ori)

        # 判断所在区域
        zone = self._get_zone(pos[0], pos[1])

        return {
            "robot_id": robot_id,
            "position": [round(pos[0], 3), round(pos[1], 3), round(pos[2], 3)],
            "yaw": round(math.degrees(yaw), 1),
            "zone": zone,
            "color": self._get_color_name(robot_id),
        }

    def get_all_robots(self) -> List[Dict]:
        """获取所有机器人状态"""
        return [self.get_robot_pose(rid) for rid in self.robots]

    def get_scene_info(self) -> Dict:
        """获取场景信息"""
        return {
            "warehouse_size": WAREHOUSE_SIZE,
            "zones": {k: list(v) for k, v in ZONES.items()},
            "robot_count": len(self.robots),
            "obstacle_count": len(self.obstacles),
            "step_count": self._step_count,
            "mode": self.mode,
        }

    def check_distance(self, robot_id: str, target_x: float, target_y: float) -> Dict:
        """计算机器人到目标点的距离"""
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}

        body_id = self.robots[robot_id]
        pos, _ = p.getBasePositionAndOrientation(body_id)
        dx, dy = target_x - pos[0], target_y - pos[1]
        dist = math.sqrt(dx * dx + dy * dy)
        return {
            "robot_id": robot_id,
            "distance": round(dist, 2),
            "from": [round(pos[0], 2), round(pos[1], 2)],
            "to": [target_x, target_y],
        }

    def check_obstacle(self, robot_id: str, direction: str = "forward",
                        range_m: float = 1.0) -> Dict:
        """
        检查前方是否有障碍物（激光雷达模拟）

        Args:
            robot_id: AGV ID
            direction: forward/left/right/back
            range_m: 检测范围 (米)

        Returns:
            {"robot_id": "...", "obstacle_detected": True, "distance": 0.5}
        """
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}

        body_id = self.robots[robot_id]
        pos, ori = p.getBasePositionAndOrientation(body_id)
        _, _, yaw = p.getEulerFromQuaternion(ori)

        # 根据方向计算检测射线终点
        dir_map = {"forward": 0, "left": 90, "right": -90, "back": 180}
        angle = yaw + math.radians(dir_map.get(direction, 0))
        ray_from = [pos[0], pos[1], pos[2]]
        ray_to = [pos[0] + range_m * math.cos(angle),
                    pos[1] + range_m * math.sin(angle),
                    pos[2]]

        results = p.rayTest(ray_from, ray_to)
        if results:
            hit_id = results[0][0]
            hit_fraction = results[0][2]
            if hit_id >= 0 and hit_id != body_id:
                hit_pos = results[0][3]
                hit_dist = hit_fraction * range_m
                return {
                    "robot_id": robot_id,
                    "obstacle_detected": True,
                    "distance": round(hit_dist, 2),
                    "direction": direction,
                    "hit_position": [round(hit_pos[0], 2), round(hit_pos[1], 2)],
                }

        return {
            "robot_id": robot_id,
            "obstacle_detected": False,
            "direction": direction,
            "range": range_m,
        }

    # ========== 辅助方法 ==========

    def _get_zone(self, x: float, y: float) -> str:
        """根据坐标判断所在区域"""
        for zone_name, (zx, zy) in ZONES.items():
            if abs(x - zx) < 1.2 and abs(y - zy) < 1.2:
                return zone_name
        return "走道"

    def _get_color_name(self, robot_id: str) -> str:
        """根据 RGBA 反查颜色名"""
        rgba = self.robot_colors.get(robot_id)
        if not rgba:
            return "unknown"
        for name, val in ROBOT_COLORS.items():
            if val == rgba:
                return name
        return "custom"


# ========== 全局单例 ==========
_sim_instance: Optional[SimEngine] = None


def get_sim() -> SimEngine:
    """获取仿真引擎单例（懒加载，避免 import 时就连 PyBullet）"""
    global _sim_instance
    if _sim_instance is None:
        _sim_instance = SimEngine()
    return _sim_instance
