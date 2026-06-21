from app.tools import get_weather, calculator, get_time
from app.agent import Agent, Tool

# 创建工具
weather_tool = Tool(
    name="get_weather",
    description="获取指定城市的天气信息",
    func=get_weather,  # 直接使用函数
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名称"}
        },
        "required": ["city"]
    }
)

calc_tool = Tool(
    name="calculator",
    description="进行数学计算",
    func=calculator,  # 直接使用函数
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式"}
        },
        "required": ["expression"]
    }
)

time_tool = Tool(
    name="get_time",
    description="获取当前系统时间",
    func=get_time,  # 直接使用函数
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)

# 创建 Agent
agent = Agent(tools=[weather_tool, calc_tool, time_tool])
result = agent.run("北京天气怎么样？")
print(result)