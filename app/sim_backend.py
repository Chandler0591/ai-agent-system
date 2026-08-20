"""
仿真后端抽象接口 — PyBullet / Gazebo 共用的引擎契约

设计原则：
- Agent（tools.py）与 API（sim_api.py）只依赖本接口，不关心底层引擎
- 返回结构契约：所有方法返回 dict，失败时含 "error" 键
- 状态机契约：idle → moving → arrived（move_robot 登记目标，wait_arrival 阻塞等待）
- 新增后端（Gazebo/Isaac Sim）只需实现本接口，get_sim() 按 SIM_BACKEND 切换
"""

from abc import ABC, abstractmethod
from typing import Dict, List


class SimBackend(ABC):
    """仿真后端抽象基类"""

    # ========== 生命周期 ==========

    @abstractmethod
    def reset(self):
        """重置仿真：清除所有机器人，保留场景"""

    @abstractmethod
    def step(self, count: int = 1):
        """推进物理仿真 N 步"""

    @abstractmethod
    def close(self):
        """关闭仿真连接"""

    # ========== 机器人管理 ==========

    @abstractmethod
    def create_robot(self, robot_id: str, x: float = 0.0, y: float = 0.0,
                     z: float = 0.1, yaw: float = 0.0, color: str = None) -> Dict:
        """
        创建一台 AGV
        Returns: {"robot_id", "position": [x,y,z], "color", "yaw"}
        """

    @abstractmethod
    def remove_robot(self, robot_id: str) -> Dict:
        """删除一台机器人，Returns: {"robot_id", "status": "removed"}"""

    # ========== 机器人控制 ==========

    @abstractmethod
    def move_robot(self, robot_id: str, x: float, y: float,
                   speed: float = 0.5) -> Dict:
        """
        移动 AGV 到目标位置（状态机：idle → moving → arrived）
        只登记目标并置 moving，由后台线程推进；需等待用 wait_arrival()
        Returns: {"robot_id", "position", "target", "distance", "status"} 或 {"error"}
        """

    @abstractmethod
    def move_robot_by_velocity(self, robot_id: str, vx: float, vy: float,
                               duration: float = 1.0) -> Dict:
        """通过速度控制 AGV（Gazebo 端对应 /cmd_vel 发布）"""

    @abstractmethod
    def wait_arrival(self, robot_id: str, timeout: float = 60.0) -> str:
        """
        阻塞等待 AGV 到达（供 Agent 工具使用，实现"Agent 等结果"）
        Returns: 最终状态：arrived / moving（超时）/ idle
        """

    # ========== 状态查询 ==========

    @abstractmethod
    def get_robot_pose(self, robot_id: str) -> Dict:
        """
        获取机器人位置和朝向
        Returns: {"robot_id", "position": [x,y,z], "yaw", "zone", "color", "status"}
        """

    @abstractmethod
    def get_all_robots(self) -> List[Dict]:
        """获取所有机器人状态"""

    @abstractmethod
    def get_scene_info(self) -> Dict:
        """获取场景信息（场地尺寸/区域/机器人数量等）"""

    # ========== 传感器 ==========

    @abstractmethod
    def check_distance(self, robot_id: str, target_x: float, target_y: float) -> Dict:
        """
        计算机器人到目标点的距离
        Returns: {"robot_id", "distance", "from", "to"} 或 {"error"}
        """

    @abstractmethod
    def check_obstacle(self, robot_id: str, direction: str = "forward",
                       range_m: float = 1.0) -> Dict:
        """
        检查指定方向是否有障碍物（激光雷达模拟）
        Returns: {"robot_id", "obstacle_detected", "distance", "direction"} 或 {"error"}
        """
