from typing import List, Dict, Any, Callable, Optional
import json
from app.llm_client import llm_client
from app.logger import logger

class Tool:
    """工具定义"""
    def __init__(self, name: str, description: str, func: Callable, parameters: dict):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters
    
    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

class Agent:
    """通用Agent框架"""
    
    def __init__(self, tools: List[Tool] = None, system_prompt: str = None):
        self.tools = {tool.name: tool for tool in (tools or [])}
        self.system_prompt = system_prompt or "你是一个有用的AI助手，可以使用提供的工具来帮助用户。"
        self.conversation_history = []
    
    def register_tool(self, tool: Tool):
        self.tools[tool.name] = tool
        logger.info(f"注册工具: {tool.name}")
    
    def _build_messages(self, query: str) -> List[Dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        for msg in self.conversation_history[-10:]:
            messages.append(msg)
        messages.append({"role": "user", "content": query})
        return messages
    
    def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        if tool_name not in self.tools:
            return json.dumps({"error": f"未知工具: {tool_name}"})
        try:
            tool = self.tools[tool_name]
            result = tool.func(**arguments)
            # 如果结果已经是字符串，直接返回；否则转为 JSON
            if isinstance(result, str):
                return result
            return json.dumps({"result": result}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"工具执行失败: {tool_name}, {str(e)}")
            return json.dumps({"error": str(e)})
    
    def run(self, query: str) -> str:
        messages = self._build_messages(query)
        tools_schema = [tool.to_openai_schema() for tool in self.tools.values()]
        
        response = llm_client.client.chat.completions.create(
            model=llm_client.model,
            messages=messages,
            tools=tools_schema if tools_schema else None,
            tool_choice="auto" if tools_schema else None
        )
        
        message = response.choices[0].message
        
        if not message.tool_calls:
            self.conversation_history.append({"role": "user", "content": query})
            self.conversation_history.append({"role": "assistant", "content": message.content})
            return message.content
        
        messages.append(message)
        
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            logger.info(f"Agent调用工具: {tool_name}, 参数: {arguments}")
            result = self._execute_tool(tool_name, arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })
        final_response = llm_client.client.chat.completions.create(
            model=llm_client.model,
            messages=messages
        )
        
        final_answer = final_response.choices[0].message.content
        self.conversation_history.append({"role": "user", "content": query})
        self.conversation_history.append({"role": "assistant", "content": final_answer})
        
        return final_answer
    
    def clear_history(self):
        self.conversation_history = []
        logger.info("对话历史已清空")