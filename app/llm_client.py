import json
from openai import OpenAI
from app.config import config
from app.logger import logger
from app.tools import TOOLS_MAP

class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL
        )
        self.model = config.MODEL_NAME
        
        # 定义工具列表
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "获取指定城市的天气信息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string", "description": "城市名称"}
                        },
                        "required": ["city"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "进行数学计算",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string", "description": "数学表达式"}
                        },
                        "required": ["expression"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "query_database",
                    "description": "查询数据库信息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "SQL查询语句"}
                        },
                        "required": ["sql"]
                    }
                }
            },
            {
              "type": "function",
              "function": {
                  "name": "get_time",
                  "description": "获取当前系统时间",
                  "parameters": {
                      "type": "object",
                      "properties": {},  # 无需传参
                      "required": []       # 无必填参数
                  }
              }
          }
        ]
    
    def chat_with_tools(self, messages, temperature=0.7):
        """支持工具调用的对话"""
        try:
            # 第一次调用，让AI决定是否需要工具
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=temperature
            )
            
            message = response.choices[0].message
            
            # 如果没有工具调用，直接返回
            if not message.tool_calls:
                return message.content
            
            # 有工具调用，执行工具
            messages.append(message.model_dump())
            
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                logger.info(f"调用工具: {tool_name}, 参数: {tool_args}")
                
                # 执行对应的工具
                if tool_name in TOOLS_MAP:
                    result = TOOLS_MAP[tool_name](**tool_args)
                else:
                    result = json.dumps({"error": f"未知工具: {tool_name}"})
                
                # 将工具结果添加到对话
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            
            # 第二次调用，让AI根据工具结果生成最终回答
            final_response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature
            )
            
            # ========== 在这里打印 response 和 messages ==========
            print("\n===== LLM 响应 response =====")
            print(json.dumps(final_response.model_dump(), indent=2, ensure_ascii=False))

            print("\n===== 对话消息 messages =====")
            print(json.dumps(messages, indent=2, ensure_ascii=False))
            
            return final_response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"工具调用失败: {str(e)}")
            return f"处理失败: {str(e)}"
    
    def chat(self, messages, temperature=0.7):
        """普通对话（不使用工具）"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM调用失败: {str(e)}")
            return f"LLM调用失败: {str(e)}"

llm_client = LLMClient()