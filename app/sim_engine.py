"""
PyBullet 仿真后端 — SimBackend 接口的 PyBullet 实现

设计原则：
- 单例模式，全局唯一仿真实例（PyBulletBackend）
- DIRECT 模式默认（Docker/服务器无头运行），GUI 模式按需开启
- 每个 AGV = URDF 模型（models/agv.urdf，与 Gazebo 共用同一模型定义）
- 实现 SimBackend 契约；切换 Gazebo 后端只需 get_sim() 读 SIM_BACKEND
"""

import os
import math
import threading
from typing import Dict, List, Optional, Tuple

import pybullet as p
import pybullet_data

from app.logger import logger
from app.sim_backend import SimBackend
# 几何常量下沉到公共模块，两个后端共用；re-export 保持上层 import 兼容
from app.sim_geometry import (
    WAREHOUSE_SIZE,
    ZONES,
    ZONE_MARK_HALF_EXTENTS,
    SHELF_POSITIONS,
    SHELF_HALF_EXTENTS,
    SHELF_SAFE_DISTANCE,
    AGV_BODY_Z_OFFSET,
    ROBOT_COLORS,
    get_zone_name,
    check_path_clear,
    compute_blocking_factor,
)

# AGV URDF 模型路径（与 Gazebo 共用同一文件）
_AGV_URDF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "agv.urdf")


class PyBulletBackend(SimBackend):
    """PyBullet 仿真后端 — 实现 SimBackend 接口"""

    _instance: Optional["PyBulletBackend"] = None

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

        # ========== 运动状态机（idle → moving → arrived） ==========
        self.robot_status: Dict[str, str] = {}              # robot_id → idle/moving/arrived
        self.robot_targets: Dict[str, Tuple[float, float]] = {}  # robot_id → (tx, ty)
        self.robot_speeds: Dict[str, float] = {}            # robot_id → m/s
        self.robot_wait_ticks: Dict[str, int] = {}          # robot_id → 连续停车 tick 数（避障防死锁）
        self._motion_lock = threading.Lock()
        self._stop_motion = threading.Event()

        self._connect()
        self._setup_scene()

        # 启动运动推进线程（驱动 moving 状态的 AGV 逐步逼近目标）
        self._motion_thread = threading.Thread(
            target=self._motion_loop, daemon=True, name="sim-motion-loop"
        )
        self._motion_thread.start()
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

        # 货架（静态障碍物，位置与尺寸来自公共几何常量）
        self.shelf_positions = list(SHELF_POSITIONS)  # 供 move_robot 防穿模校验使用
        shelf_visual = p.createVisualShape(
            shapeType=p.GEOM_BOX,
            halfExtents=list(SHELF_HALF_EXTENTS),
            rgbaColor=[0.5, 0.35, 0.2, 1.0],
        )
        shelf_collision = p.createCollisionShape(
            shapeType=p.GEOM_BOX,
            halfExtents=list(SHELF_HALF_EXTENTS),
        )
        for i, (sx, sy) in enumerate(SHELF_POSITIONS):
            body_id = p.createMultiBody(
                baseMass=0,  # 静态
                baseCollisionShapeIndex=shelf_collision,
                baseVisualShapeIndex=shelf_visual,
                basePosition=[sx, sy, SHELF_HALF_EXTENTS[2]],  # 中心在z=1.0，底贴地面
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
                halfExtents=[ZONE_MARK_HALF_EXTENTS, ZONE_MARK_HALF_EXTENTS, 0.005],
                rgbaColor=zone_colors.get(zone_name, [0.3, 0.3, 0.3, 0.2]),
            )
            body = p.createMultiBody(
                baseVisualShapeIndex=vis,
                basePosition=[zx, zy, 0.001],
            )
            self.obstacles[f"zone_{zone_name}"] = body

        logger.info(f"仓库场景已初始化 (货架={len(SHELF_POSITIONS)}, 区域={len(ZONES)})")

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
            self._stop_motion.set()
            p.disconnect(self.client_id)
            self.client_id = -1
            PyBulletBackend._instance = None
            self._initialized = False
            logger.info("仿真连接已关闭")

    # ========== 运动状态机 ==========

    def _motion_loop(self):
        """
        后台线程：推进 moving 状态的 AGV 逐步逼近目标点
        每个 tick 移动 speed*dt 米，到达后状态置为 arrived
        """
        dt = 0.05  # 50ms/tick
        while not self._stop_motion.is_set():
            with self._motion_lock:
                for robot_id in list(self.robot_targets.keys()):
                    if self.robot_status.get(robot_id) != "moving":
                        continue
                    body_id = self.robots.get(robot_id)
                    if body_id is None:
                        continue

                    tx, ty = self.robot_targets[robot_id]
                    pos, _ = p.getBasePositionAndOrientation(body_id)
                    dx, dy = tx - pos[0], ty - pos[1]
                    remaining = math.sqrt(dx * dx + dy * dy)
                    speed = self.robot_speeds.get(robot_id, 0.5)
                    step_dist = speed * dt

                    if remaining <= step_dist or remaining < 0.01:
                        # 到达目标：精确落点，状态 → arrived
                        yaw = math.degrees(math.atan2(dy, dx)) if remaining > 0.001 else None
                        if yaw is not None:
                            ori = p.getQuaternionFromEuler([0, 0, math.radians(yaw)])
                            p.resetBasePositionAndOrientation(body_id, [tx, ty, pos[2]], ori)
                        else:
                            p.resetBasePositionAndOrientation(
                                body_id, [tx, ty, pos[2]],
                                p.getQuaternionFromEuler([0, 0, 0]))
                        self.robot_status[robot_id] = "arrived"
                        self.robot_targets.pop(robot_id, None)
                        logger.info(f"{robot_id} 到达目标 ({tx:.2f}, {ty:.2f})")
                    else:
                        # 车-车避障：前进方向锥内有车时降速/停车，等太久强制缓行防死锁
                        other_positions = [
                            p.getBasePositionAndOrientation(b)[0][:2]
                            for rid, b in self.robots.items() if rid != robot_id
                        ]
                        factor = compute_blocking_factor(
                            [pos[0], pos[1]], [tx, ty], other_positions)
                        if factor <= 0.0:
                            ticks = self.robot_wait_ticks.get(robot_id, 0) + 1
                            self.robot_wait_ticks[robot_id] = ticks
                            if ticks > 100:   # 连续停车 5s 未疏通，0.3 速强制通行
                                factor = 0.3
                            else:
                                continue     # 本 tick 停车等待
                        else:
                            self.robot_wait_ticks.pop(robot_id, None)

                        # 小步推进，车头朝向目标
                        step_dist = speed * factor * dt
                        nx = pos[0] + dx / remaining * step_dist
                        ny = pos[1] + dy / remaining * step_dist
                        yaw = math.degrees(math.atan2(dy, dx))
                        ori = p.getQuaternionFromEuler([0, 0, math.radians(yaw)])
                        p.resetBasePositionAndOrientation(body_id, [nx, ny, pos[2]], ori)
                        self._step_count += 1

            # 有移动中的 AGV 时推进物理世界
            with self._motion_lock:
                has_moving = any(s == "moving" for s in self.robot_status.values())
            if has_moving:
                p.stepSimulation()
            self._stop_motion.wait(dt)

    def wait_arrival(self, robot_id: str, timeout: float = 60.0) -> str:
        """
        阻塞等待 AGV 到达（供 Agent 工具使用，实现"Agent 等结果"）

        Returns:
            最终状态：arrived / moving（超时）/ idle
        """
        import time
        elapsed = 0.0
        while elapsed < timeout:
            if self.robot_status.get(robot_id) != "moving":
                return self.robot_status.get(robot_id, "idle")
            time.sleep(0.1)
            elapsed += 0.1
        return self.robot_status.get(robot_id, "moving")

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
        self.robot_status[robot_id] = "idle"
        self.robot_speeds[robot_id] = 0.5

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
        """加载 AGV URDF 模型（models/agv.urdf，车身 + 4 固定轮），并应用车身颜色"""
        # 朝向（度 → 四元数）
        orientation = p.getQuaternionFromEuler([0, 0, math.radians(yaw)])

        body_id = p.loadURDF(
            _AGV_URDF_PATH,
            basePosition=[x, y, z + AGV_BODY_Z_OFFSET],
            baseOrientation=orientation,
        )

        # URDF 默认材质 → 按色表覆盖车身颜色（轮子保持 URDF 内定义的深色）
        p.changeVisualShape(body_id, -1, rgbaColor=rgba)

        return body_id

    def remove_robot(self, robot_id: str) -> Dict:
        """删除一台机器人"""
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}
        body_id = self.robots.pop(robot_id)
        self.robot_colors.pop(robot_id, None)
        self.robot_status.pop(robot_id, None)
        with self._motion_lock:
            self.robot_targets.pop(robot_id, None)
            self.robot_wait_ticks.pop(robot_id, None)
        self.robot_speeds.pop(robot_id, None)
        p.removeBody(body_id)
        logger.info(f"已删除机器人: {robot_id}")
        return {"robot_id": robot_id, "status": "removed"}

    # ========== 机器人控制 ==========

    def move_robot(self, robot_id: str, x: float, y: float,
                   speed: float = 0.5) -> Dict:
        """
        移动 AGV 到目标位置（状态机：idle → moving → arrived）

        本方法只登记目标并置状态为 moving，由后台 _motion_loop 线程逐步推进；
        需要同步等待到达请使用 wait_arrival()。

        Args:
            robot_id: AGV ID
            x, y: 目标坐标
            speed: 移动速度 (m/s)

        Returns:
            {"robot_id": "...", "position": [当前x,y,z], "target": [x,y],
             "distance": 1.5, "status": "moving"}
        """
        if robot_id not in self.robots:
            return {"error": f"机器人 {robot_id} 不存在"}

        body_id = self.robots[robot_id]
        current_pos, _ = p.getBasePositionAndOrientation(body_id)

        # 防穿模校验：目标点与任何货架中心距离 < 安全距离时拒绝移动
        for sx, sy in self.shelf_positions:
            dist_to_shelf = math.hypot(x - sx, y - sy)
            if dist_to_shelf < SHELF_SAFE_DISTANCE:
                return {
                    "error": f"目标点 ({x}, {y}) 与货架 ({sx}, {sy}) 冲突，"
                             f"距离 {dist_to_shelf:.2f}m < 安全距离 {SHELF_SAFE_DISTANCE}m，拒绝移动防穿模"
                }

        # 路径防穿模：目标点合法 ≠ 直线路径合法（路径可能贴着货架经过）
        path_error = check_path_clear(current_pos[0], current_pos[1], x, y)
        if path_error:
            return {"error": f"{path_error}，拒绝移动防穿模（请分段绕行）"}

        # 计算距离
        dx, dy = x - current_pos[0], y - current_pos[1]
        distance = math.sqrt(dx * dx + dy * dy)

        if distance < 0.001:
            # 已在目标点，直接标记 arrived
            with self._motion_lock:
                self.robot_status[robot_id] = "arrived"
                self.robot_targets.pop(robot_id, None)
            return {
                "robot_id": robot_id,
                "position": [x, y, current_pos[2]],
                "distance": 0.0,
                "from": [round(current_pos[0], 2), round(current_pos[1], 2)],
                "status": "arrived",
                "message": "已在目标位置，无需移动",
            }

        # 登记移动任务，后台线程推进
        with self._motion_lock:
            self.robot_targets[robot_id] = (x, y)
            self.robot_speeds[robot_id] = speed
            self.robot_status[robot_id] = "moving"
            self.robot_wait_ticks[robot_id] = 0   # 新任务重置避障等待计数

        logger.info(f"{robot_id} 开始移动 → ({x:.2f}, {y:.2f}) 距离={distance:.2f}m speed={speed}m/s")
        return {
            "robot_id": robot_id,
            "position": [round(current_pos[0], 3), round(current_pos[1], 3), round(current_pos[2], 3)],
            "target": [x, y],
            "distance": round(distance, 2),
            "from": [round(current_pos[0], 2), round(current_pos[1], 2)],
            "status": "moving",
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
            "status": self.robot_status.get(robot_id, "idle"),
        }

    def get_all_robots(self) -> List[Dict]:
        """获取所有机器人状态"""
        return [self.get_robot_pose(rid) for rid in self.robots]

    def get_scene_info(self) -> Dict:
        """获取场景信息"""
        return {
            "warehouse_size": WAREHOUSE_SIZE,
            "zones": {k: list(v) for k, v in ZONES.items()},
            "shelves": [list(s) for s in SHELF_POSITIONS],
            "shelf_half_extents": list(SHELF_HALF_EXTENTS),
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
        """根据坐标判断所在区域（公共几何函数）"""
        return get_zone_name(x, y)

    def _get_color_name(self, robot_id: str) -> str:
        """根据 RGBA 反查颜色名"""
        rgba = self.robot_colors.get(robot_id)
        if not rgba:
            return "unknown"
        for name, val in ROBOT_COLORS.items():
            if val == rgba:
                return name
        return "custom"


# ========== 全局单例（后端开关） ==========
_sim_instance: Optional[SimBackend] = None


def get_sim() -> SimBackend:
    """
    获取仿真后端单例（懒加载，避免 import 时就连引擎）

    按 SIM_BACKEND 环境变量选择后端：
    - pybullet（默认）：PyBulletBackend
    - gazebo：GazeboBackend（W5-W6 迭代实现）
    """
    global _sim_instance
    if _sim_instance is None:
        backend = os.getenv("SIM_BACKEND", "pybullet").strip().lower()
        if backend == "pybullet":
            _sim_instance = PyBulletBackend()
        elif backend in ("gazebo", "ros2"):
            try:
                from app.sim_gazebo import GazeboBackend
            except ImportError as e:
                logger.error(f"SIM_BACKEND={backend} 但 Gazebo 后端依赖缺失: {e}")
                raise RuntimeError(
                    "Gazebo 后端需要 ROS 2 环境（rclpy + gazebo_ros + sim_interfaces），"
                    "详见 docs/gazebo-ros2-roadmap.md；当前可改用 SIM_BACKEND=pybullet"
                ) from e
            _sim_instance = GazeboBackend()
        else:
            raise ValueError(f"未知仿真后端: {backend}，可选: pybullet / gazebo")
    return _sim_instance


# 向后兼容别名（scripts/test_sim.py 等旧引用）
SimEngine = PyBulletBackend
