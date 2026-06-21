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


# ========== 工具映射（供 llm_client 使用）==========
TOOLS_MAP = {
    "get_weather": Tools.get_weather,
    "calculator": Tools.calculator,
    "get_time": Tools.get_time,
    "search_knowledge_base": Tools.search_knowledge_base,
    "query_database": Tools.query_database,
    "search_documents": Tools.search_documents
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