from openai import OpenAI
import json

client = OpenAI(
    api_key="",  # 临时测试用
    base_url="https://api.deepseek.com"
)

# 1. 定义工具
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，如：北京、上海"
                }
            },
            "required": ["city"]
        }
    }
}]

# 2. 发送请求
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "北京今天天气怎么样？"}],
    tools=tools
)

# 3. 查看响应
message = response.choices[0].message
print(f"是否有工具调用: {message.tool_calls is not None}")

if message.tool_calls:
    tool_call = message.tool_calls[0]
    print(f"工具名称: {tool_call.function.name}")
    print(f"工具参数: {tool_call.function.arguments}")
