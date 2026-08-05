"""
仿真 REST API — AI Agent 控制物理世界的桥梁

设计原则：
- 独立的 APIRouter，方便后续切换 Gazebo/Isaac Sim 时热拔插
- 所有写操作需 JWT 认证，读操作开放（方便监控面板）
- 返回 JSON，与前端 SSE/轮询无缝对接
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional

from app.sim_engine import get_sim
from app.logger import logger

# 创建子路由，前缀 /api/sim
sim_router = APIRouter(prefix="/sim", tags=["仿真"])


# ========== 认证依赖（从 main.py 传入，避免循环导入） ==========
# 在 main.py 注册路由时传入 dependencies


# ========== 场景查询 ==========

@sim_router.get("/status")
async def sim_status():
    """获取仿真场景总览"""
    try:
        sim = get_sim()
        info = sim.get_scene_info()
        robots = sim.get_all_robots()
        return {
            "scene": info,
            "robots": robots,
            "robot_count": len(robots),
        }
    except Exception as e:
        logger.error(f"仿真状态查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 机器人管理 ==========

@sim_router.post("/robot/create")
async def sim_create_robot(
    robot_id: str,
    x: float = 0.0,
    y: float = 0.0,
    yaw: float = 0.0,
    color: Optional[str] = None,
):
    """创建一台 AGV（yaw: 朝向角，0=东, 90=北, 180=西, 270=南）"""
    try:
        sim = get_sim()
        result = sim.create_robot(robot_id, x, y, yaw=yaw, color=color)
        return result
    except Exception as e:
        logger.error(f"创建机器人失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@sim_router.delete("/robot/{robot_id}")
async def sim_remove_robot(robot_id: str):
    """删除一台 AGV"""
    try:
        sim = get_sim()
        result = sim.remove_robot(robot_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除机器人失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 机器人控制 ==========

@sim_router.post("/robot/{robot_id}/move")
async def sim_move_robot(
    robot_id: str,
    x: float,
    y: float,
    speed: float = 0.5,
):
    """移动 AGV 到目标位置"""
    try:
        sim = get_sim()
        result = sim.move_robot(robot_id, x, y, speed=speed)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移动机器人失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@sim_router.post("/robot/{robot_id}/move-by-zone")
async def sim_move_robot_by_zone(
    robot_id: str,
    zone: str,
):
    """
    移动 AGV 到指定区域（A/B/C/D）
    例：POST /api/sim/robot/agv_1/move-by-zone?zone=B
    """
    from app.sim_engine import ZONES

    if zone.upper() not in ZONES:
        raise HTTPException(status_code=400, detail=f"无效区域: {zone}，可选: {list(ZONES.keys())}")

    target = ZONES[zone.upper()]
    try:
        sim = get_sim()
        result = sim.move_robot(robot_id, target[0], target[1])
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return {
            **result,
            "zone": zone.upper(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移动机器人到区域失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@sim_router.post("/robot/{robot_id}/velocity")
async def sim_move_robot_by_velocity(
    robot_id: str,
    vx: float = 0.0,
    vy: float = 0.0,
    duration: float = 1.0,
):
    """通过速度控制 AGV"""
    try:
        sim = get_sim()
        result = sim.move_robot_by_velocity(robot_id, vx, vy, duration)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"速度控制失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 状态查询 ==========

@sim_router.get("/robot/{robot_id}")
async def sim_get_robot(robot_id: str):
    """获取单个机器人状态"""
    try:
        sim = get_sim()
        result = sim.get_robot_pose(robot_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询机器人失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@sim_router.get("/robots")
async def sim_list_robots():
    """列出所有机器人"""
    try:
        sim = get_sim()
        return {
            "robots": sim.get_all_robots(),
            "count": len(sim.robots),
        }
    except Exception as e:
        logger.error(f"列出机器人失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 传感器 ==========

@sim_router.get("/robot/{robot_id}/distance")
async def sim_check_distance(
    robot_id: str,
    target_x: float,
    target_y: float,
):
    """计算机器人到目标点距离"""
    try:
        sim = get_sim()
        result = sim.check_distance(robot_id, target_x, target_y)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"计算距离失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@sim_router.get("/robot/{robot_id}/obstacle")
async def sim_check_obstacle(
    robot_id: str,
    direction: str = "forward",
    range_m: float = 1.0,
):
    """
    检测障碍物（激光雷达模拟）
    direction: forward / left / right / back
    """
    try:
        sim = get_sim()
        result = sim.check_obstacle(robot_id, direction, range_m)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"障碍检测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 场景管理 ==========

@sim_router.post("/reset")
async def sim_reset():
    """重置仿真（清除所有机器人）"""
    try:
        sim = get_sim()
        sim.reset()
        return {"status": "reset", "robot_count": 0}
    except Exception as e:
        logger.error(f"重置仿真失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@sim_router.get("/zones")
async def sim_zones():
    """获取区域定义"""
    from app.sim_engine import ZONES
    return {"zones": {k: list(v) for k, v in ZONES.items()}}
