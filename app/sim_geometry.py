"""
仿真场景几何常量 — PyBullet / Gazebo 后端共用

设计原则：
- 两个后端共享同一套场景几何，保证坐标一致、结果可比
- 引擎实现（sim_engine.py / 未来的 sim_gazebo.py）从这里取常量
- 上层（tools.py / sim_api.py）通过 sim_engine 的 re-export 使用 ZONES
"""

import math

# ========== 场地 ==========
WAREHOUSE_SIZE = 10.0          # 仓库边长（米）

# ========== 区域定义（A/B/C/D 四象限中心点） ==========
ZONES = {
    "A": ( 2.5,  2.5),
    "B": (-2.5,  2.5),
    "C": (-2.5, -2.5),
    "D": ( 2.5, -2.5),
}

# 区域判定半径（距区域中心 < 该值即判定在区域内）
ZONE_RADIUS = 1.2

# 区域标记可视化（半透明地面块半边长）
ZONE_MARK_HALF_EXTENTS = 1.2

# ========== 货架（静态障碍物） ==========
SHELF_POSITIONS = [
    ( 3.0,  0.0), (-3.0,  0.0),
    ( 0.0,  3.0), ( 0.0, -3.0),
]

SHELF_HALF_EXTENTS = (0.8, 0.3, 1.0)   # 货架半尺寸 (x, y, z)，高 2m
SHELF_HEIGHT = 2.0                      # 货架高度（中心 z = 1.0）
SHELF_SAFE_DISTANCE = 1.15              # 防穿模安全距离（货架半长0.8 + 车身半长0.35）

# ========== AGV 几何（与 models/agv.urdf 保持一致） ==========
AGV_HALF_EXTENTS = (0.35, 0.2, 0.08)    # 车身半尺寸
AGV_BODY_Z_OFFSET = 0.12                # 车身中心相对机器人 z 的偏移
AGV_WHEEL_RADIUS = 0.06                 # 轮子半径
AGV_WHEEL_LENGTH = 0.03                 # 轮子厚度
AGV_WHEEL_POSITIONS = [                 # 4 轮相对车身中心 (x, y)
    ( 0.18,  0.13),   # 前左
    ( 0.18, -0.13),   # 前右
    (-0.18,  0.13),   # 后左
    (-0.18, -0.13),   # 后右
]

# ========== 颜色 ==========
ROBOT_COLORS = {
    "red":    [1.0, 0.2, 0.2, 1.0],
    "blue":   [0.2, 0.4, 1.0, 1.0],
    "green":  [0.2, 0.8, 0.3, 1.0],
    "orange": [1.0, 0.6, 0.1, 1.0],
    "purple": [0.7, 0.3, 0.9, 1.0],
}

# ========== 车-车避障（公共纯函数，双后端共用） ==========

ROBOT_STOP_DISTANCE = 0.6    # 前方车距 < 此值停车等待（车长 0.7 + 余量）
ROBOT_SLOW_DISTANCE = 1.2    # 前方车距 < 此值减速一半
ROBOT_BLOCK_CONE_COS = 0.2   # 前方判定锥（投影 cos > 此值视为在前方）


def compute_blocking_factor(robot_pos, target, other_positions) -> float:
    """
    车-车避障减速因子：1.0 正常 / 0.5 缓行 / 0.0 停车等待。

    只对“前进方向锥内”的邻近车生效（避免身后/侧面无关车误挡）；
    距离越近降得越狠，小于 ROBOT_STOP_DISTANCE 直接停车。
    """
    dx, dy = target[0] - robot_pos[0], target[1] - robot_pos[1]
    remaining = math.hypot(dx, dy)
    if remaining < 1e-6:
        return 1.0
    ux, uy = dx / remaining, dy / remaining

    factor = 1.0
    for (ox, oy) in other_positions:
        rx, ry = ox - robot_pos[0], oy - robot_pos[1]
        dist = math.hypot(rx, ry)
        if dist <= 1e-6 or dist >= ROBOT_SLOW_DISTANCE:
            continue
        # 另一车在本车前进方向的投影占比（>0 在前方，<0 在身后）
        if (rx * ux + ry * uy) / dist <= ROBOT_BLOCK_CONE_COS:
            continue
        if dist < ROBOT_STOP_DISTANCE:
            return 0.0
        factor = min(factor, 0.5)
    return factor


# ========== 辅助函数 ==========

def get_zone_name(x: float, y: float) -> str:
    """根据坐标判断所在区域（不在任何区域则返回走道）"""
    for zone_name, (zx, zy) in ZONES.items():
        if abs(x - zx) < ZONE_RADIUS and abs(y - zy) < ZONE_RADIUS:
            return zone_name
    return "走道"


def check_path_clear(x0: float, y0: float, x1: float, y1: float):
    """
    直线路径防穿模校验：计算路径线段到各货架中心的最小距离，
    小于 SHELF_SAFE_DISTANCE 则返回冲突描述，否则返回 None。

    双后端在 move_robot 时共用：目标点合法 ≠ 直线路径合法
    （例：从 A 区直穿到 D 区会贴着货架经过）。
    """
    dx, dy = x1 - x0, y1 - y0
    seg_len2 = dx * dx + dy * dy
    for sx, sy in SHELF_POSITIONS:
        if seg_len2 < 1e-12:
            dist = math.hypot(sx - x0, sy - y0)
        else:
            # 点到线段最小距离：投影参数 t 截断到 [0, 1]
            t = max(0.0, min(1.0, ((sx - x0) * dx + (sy - y0) * dy) / seg_len2))
            px, py = x0 + t * dx, y0 + t * dy
            dist = math.hypot(sx - px, sy - py)
        if dist < SHELF_SAFE_DISTANCE:
            return (f"路径 ({x0:.2f},{y0:.2f}) → ({x1:.2f},{y1:.2f}) 经过货架 "
                    f"({sx:.0f},{sy:.0f}) 附近，最近距离 {dist:.2f}m "
                    f"< 安全距离 {SHELF_SAFE_DISTANCE}m")
    return None
