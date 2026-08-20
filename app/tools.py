import json
from datetime import datetime
from app.logger import logger

# 租户上下文（agent_unified 在每次请求时设置）
_current_tenant = "default"

def set_tenant(tenant_id: str):
    global _current_tenant
    _current_tenant = tenant_id

class Tools:
    """工具集 - 所有工具都定义为静态方法"""
    
    @staticmethod
    def get_weather(city: str) -> str:
        """获取天气（模拟）"""
        weather_data = {
            "北京": {"temp": 25, "weather": "晴", "humidity": 45},
            "上海": {"temp": 28, "weather": "多云", "humidity": 65},
            "广州": {"temp": 32, "weather": "雨", "humidity": 85},
            "深圳": {"temp": 30, "weather": "阴", "humidity": 75},
        }
        
        data = weather_data.get(city, {"temp": 22, "weather": "未知", "humidity": 60})
        return json.dumps({
            "city": city,
            "temperature": data["temp"],
            "weather": data["weather"],
            "humidity": data["humidity"],
            "time": datetime.now().strftime("%Y-%m-%d %H:%M")
        }, ensure_ascii=False)
    
    @staticmethod
    def calculator(expression: str) -> str:
        """计算数学表达式"""
        try:
            allowed_chars = "0123456789+-*/(). "
            if not all(c in allowed_chars for c in expression):
                return json.dumps({"error": "表达式包含非法字符"})
            
            result = eval(expression)
            return json.dumps({"expression": expression, "result": result})
        except Exception as e:
            return json.dumps({"error": f"计算错误: {str(e)}"})
    
    @staticmethod
    def get_time() -> str:
        """获取当前时间"""
        now = datetime.now()
        return json.dumps({
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": now.timestamp()
        }, ensure_ascii=False)

    @staticmethod
    def search_knowledge_base(query: str) -> str:
        """搜索知识库"""
        from app.knowledge_base import knowledge_base
        
        try:
            results = knowledge_base.search(query, top_k=3, tenant_id=_current_tenant)
            if not results:
                return json.dumps({"results": [], "message": "未找到相关内容"})
            
            formatted = []
            for r in results:
                formatted.append({
                    "content": r["text"][:500],
                    "source": r["metadata"].get("source", "未知"),
                    "score": r["score"]
                })
            
            return json.dumps({"results": formatted, "count": len(formatted)}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"知识库搜索失败: {e}")
            return json.dumps({"error": str(e)})
    
    @staticmethod
    def query_database(sql: str) -> str:
        """查询数据库（模拟）"""
        logger.info(f"模拟数据库查询: {sql}")
        
        if "weather" in sql.lower():
            return json.dumps({"data": [{"city": "北京", "temp": 25}]})
        elif "user" in sql.lower():
            return json.dumps({"data": [{"id": 1, "name": "test"}]})
        else:
            return json.dumps({"data": [], "message": "暂无数据"})

    @staticmethod
    def search_documents(keyword: str) -> str:
        """搜索文档"""
        # 注意：database 模块可能不存在，这里是占位
        return json.dumps({"results": [], "message": f"搜索: {keyword}"}, ensure_ascii=False)

    # ========== 仿真工具（W2）==========

    @staticmethod
    def move_robot(robot_id: str, x: float = None, y: float = None, zone: str = None) -> str:
        """
        移动仓库中的 AGV 小车到指定坐标或区域

        参数:
            robot_id: 小车编号，如 agv_1, agv_2
            x, y: 目标坐标（与 zone 二选一）
            zone: 目标区域 A/B/C/D（与 x,y 二选一）

        返回: 移动结果，含位置、距离、所在区域
        """
        try:
            from app.sim_engine import get_sim, ZONES
            sim = get_sim()

            if zone:
                zone = zone.upper()
                if zone not in ZONES:
                    return json.dumps({"error": f"无效区域: {zone}，可选: A/B/C/D"})
                tx, ty = ZONES[zone]
                result = sim.move_robot(robot_id, tx, ty)
                if "error" in result:
                    return json.dumps(result)
                # 等待到达（状态机 idle → moving → arrived），实现"Agent 等结果"
                status = sim.wait_arrival(robot_id, timeout=60.0)
                pose = sim.get_robot_pose(robot_id)
                return json.dumps({
                    "action": "move",
                    "robot_id": robot_id,
                    "target_zone": zone,
                    "position": pose["position"],
                    "zone": pose["zone"],
                    "status": status,
                    "distance": result["distance"],
                }, ensure_ascii=False)

            if x is not None and y is not None:
                result = sim.move_robot(robot_id, x, y)
                if "error" in result:
                    return json.dumps(result)
                # 等待到达（状态机 idle → moving → arrived），实现"Agent 等结果"
                status = sim.wait_arrival(robot_id, timeout=60.0)
                pose = sim.get_robot_pose(robot_id)
                return json.dumps({
                    "action": "move",
                    "robot_id": robot_id,
                    "position": pose["position"],
                    "zone": pose["zone"],
                    "status": status,
                    "distance": result["distance"],
                }, ensure_ascii=False)

            return json.dumps({"error": "请提供坐标 (x, y) 或区域 (zone)"})

        except ImportError:
            return json.dumps({"error": "仿真模块未安装"})
        except Exception as e:
            logger.error(f"移动机器人失败: {e}")
            return json.dumps({"error": str(e)})

    @staticmethod
    def check_distance(robot_id: str, target_x: float, target_y: float) -> str:
        """
        计算机器人到目标点的距离（传感器）

        参数:
            robot_id: 小车编号，如 agv_1
            target_x, target_y: 目标点坐标

        返回: 当前坐标、目标坐标、直线距离
        """
        try:
            from app.sim_engine import get_sim
            sim = get_sim()
            result = sim.check_distance(robot_id, target_x, target_y)
            return json.dumps(result, ensure_ascii=False)

        except ImportError:
            return json.dumps({"error": "仿真模块未安装"})
        except Exception as e:
            logger.error(f"距离计算失败: {e}")
            return json.dumps({"error": str(e)})

    @staticmethod
    def get_robot_status(robot_id: str = None) -> str:
        """
        查询 AGV 小车状态

        参数:
            robot_id: 小车编号，不传则返回所有小车

        返回: 小车位置、朝向、所在区域
        """
        try:
            from app.sim_engine import get_sim
            sim = get_sim()

            if robot_id:
                pose = sim.get_robot_pose(robot_id)
                return json.dumps(pose, ensure_ascii=False)

            robots = sim.get_all_robots()
            if not robots:
                return json.dumps({"message": "仓库中没有小车，请先创建"}, ensure_ascii=False)
            return json.dumps({"robots": robots, "count": len(robots)}, ensure_ascii=False)

        except ImportError:
            return json.dumps({"error": "仿真模块未安装"})
        except Exception as e:
            logger.error(f"查询机器人失败: {e}")
            return json.dumps({"error": str(e)})

    @staticmethod
    def check_obstacle(robot_id: str, direction: str = "forward") -> str:
        """
        检测 AGV 前方障碍物（激光雷达模拟）

        参数:
            robot_id: 小车编号
            direction: 检测方向 forward/left/right/back

        返回: 是否有障碍物及距离
        """
        try:
            from app.sim_engine import get_sim
            sim = get_sim()
            result = sim.check_obstacle(robot_id, direction)
            return json.dumps(result, ensure_ascii=False)

        except ImportError:
            return json.dumps({"error": "仿真模块未安装"})
        except Exception as e:
            logger.error(f"障碍检测失败: {e}")
            return json.dumps({"error": str(e)})


# ========== 工具映射（供 llm_client 使用）==========
TOOLS_MAP = {
    "get_weather": Tools.get_weather,
    "calculator": Tools.calculator,
    "get_time": Tools.get_time,
    "search_knowledge_base": Tools.search_knowledge_base,
    "query_database": Tools.query_database,
    "search_documents": Tools.search_documents,
    # 仿真工具
    "move_robot": Tools.move_robot,
    "get_robot_status": Tools.get_robot_status,
    "check_obstacle": Tools.check_obstacle,
    "check_distance": Tools.check_distance,
}


# ========== 便捷函数（供 agent.py 使用）==========
# 这样可以直接 from app.tools import get_weather
def get_weather(city: str) -> str:
    return Tools.get_weather(city)

def calculator(expression: str) -> str:
    return Tools.calculator(expression)

def get_time() -> str:
    return Tools.get_time()

def search_knowledge_base(query: str) -> str:
    return Tools.search_knowledge_base(query)

def query_database(sql: str) -> str:
    return Tools.query_database(sql)

def search_documents(keyword: str) -> str:
    return Tools.search_documents(keyword)

def move_robot(robot_id: str, x: float = None, y: float = None, zone: str = None) -> str:
    return Tools.move_robot(robot_id, x, y, zone)

def get_robot_status(robot_id: str = None) -> str:
    return Tools.get_robot_status(robot_id)

def check_obstacle(robot_id: str, direction: str = "forward") -> str:
    return Tools.check_obstacle(robot_id, direction)

def check_distance(robot_id: str, target_x: float, target_y: float) -> str:
    return Tools.check_distance(robot_id, target_x, target_y)