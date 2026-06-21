import json
import base64
import os
import mimetypes
from openai import OpenAI
from typing import List, Dict, Optional
from app.config import config
from app.logger import logger
from app.tools import TOOLS_MAP

# 默认超时（可在 config 中覆盖）
_LLM_TIMEOUT = getattr(config, 'LLM_TIMEOUT', 60.0)

class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL
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
                  "name": "get_time",
                  "description": "获取当前系统时间",
                  "parameters": {
                      "type": "object",
                      "properties": {},  # 无需传参
                      "required": []       # 无必填参数
                  }
              }
          },
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge_base",
                    "description": "搜索知识库中的文档内容",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "搜索关键词"}
                        },
                        "required": ["query"]
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
            }
        ]
        
        # ========== 多模态视觉客户端（惰性初始化） ==========
        self._vision_client = None
        self._vision_initialized = False
        self._vision_available = False
    
    # ========== 多模态视觉 API ==========
    
    def _init_vision_client(self):
        """
        惰性初始化视觉模型客户端
        支持厂商: OpenAI / 通义千问(Qwen) / 智谱(Zhipu) / Moonshot / DeepSeek(预留)
        """
        if self._vision_initialized:
            return
        self._vision_initialized = True
        
        if not config.VISION_ENABLED:
            logger.info("视觉模型未启用（VISION_ENABLED=false）")
            return
        
        provider = config.VISION_PROVIDER
        api_key = config.VISION_API_KEY
        base_url = config.VISION_BASE_URL or config.VISION_PROVIDER_URLS.get(provider, "")
        model_name = config.VISION_MODEL_NAME or config.VISION_PROVIDER_MODELS.get(provider, "")
        
        if not api_key:
            logger.warning(f"视觉模型 [{provider}] 缺少 API Key，无法初始化")
            return
        if not base_url:
            logger.warning(f"视觉模型 [{provider}] 未知厂商，无法确定 Base URL")
            return
        
        try:
            self._vision_client = OpenAI(api_key=api_key, base_url=base_url)
            self._vision_model = model_name
            self._vision_provider = provider
            self._vision_available = True
            logger.info(
                f"视觉模型已就绪: provider={provider}, model={model_name}, "
                f"base_url={base_url}"
            )
        except Exception as e:
            logger.error(f"视觉模型初始化失败 [{provider}]: {e}")
            self._vision_available = False
    
    @property
    def is_vision_available(self) -> bool:
        """检查视觉模型是否可用"""
        if not self._vision_initialized:
            self._init_vision_client()
        return self._vision_available
    
    def describe_image(
        self,
        image_path: str,
        prompt: str = None,
        detail: str = "auto",
        max_tokens: int = 500
    ) -> Optional[str]:
        """
        使用多模态视觉模型描述图片内容
        
        支持的厂商及模型:
        - OpenAI:    gpt-4o / gpt-4-turbo
        - 通义千问:   qwen-vl-max / qwen-vl-plus
        - 智谱AI:    glm-4v
        - Moonshot:  moonshot-v1-8k-vision-preview
        
        Args:
            image_path: 图片文件路径（支持 jpg/png/webp/gif）
            prompt:     自定义提示词（默认: "请详细描述这张图片的内容"）
            detail:     图片细节级别 (auto/low/high)，仅 OpenAI 支持
            max_tokens: 最大输出 token 数
        
        Returns:
            图片文字描述，失败返回 None
        """
        if not self.is_vision_available:
            logger.warning("视觉模型不可用，跳过图片描述")
            return None
        
        # 检查文件存在
        if not os.path.exists(image_path):
            logger.error(f"图片文件不存在: {image_path}")
            return None
        
        # 编码图片为 base64
        try:
            base64_image = self._encode_image(image_path)
            mime_type = self._get_mime_type(image_path)
        except Exception as e:
            logger.error(f"图片编码失败: {e}")
            return None
        
        # 默认提示词
        if not prompt:
            prompt = "请详细描述这张图片的内容，包括主要对象、场景、文字信息等。"
        
        # 构建 vision 消息（OpenAI 兼容格式）
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}",
                            "detail": detail
                        }
                    }
                ]
            }
        ]
        
        try:
            response = self._vision_client.chat.completions.create(
                model=self._vision_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.3,
                timeout=_LLM_TIMEOUT
            )
            description = response.choices[0].message.content
            logger.info(
                f"图片描述完成 [{self._vision_provider}/{self._vision_model}]: "
                f"{os.path.basename(image_path)} → {len(description)}字符"
            )
            return description
        except Exception as e:
            logger.error(f"视觉模型调用失败 [{self._vision_provider}]: {e}")
            return None
    
    @staticmethod
    def _encode_image(image_path: str) -> str:
        """将图片文件编码为 base64 字符串"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    @staticmethod
    def _get_mime_type(image_path: str) -> str:
        """获取图片 MIME 类型"""
        mime_type, _ = mimetypes.guess_type(image_path)
        if mime_type and mime_type.startswith("image/"):
            return mime_type
        # 根据扩展名 fallback
        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
            ".gif": "image/gif", ".bmp": "image/bmp",
        }
        return mime_map.get(ext, "image/png")
    
    def chat_with_tools(self, messages, temperature=0.7):
        """支持工具调用的对话"""
        try:
            # 第一次调用，让AI决定是否需要工具
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=temperature,
                timeout=_LLM_TIMEOUT
            )
            
            message = response.choices[0].message
            
            # 如果没有工具调用，直接返回
            if not message.tool_calls:
                return message.content or ""
            
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
                temperature=temperature,
                timeout=_LLM_TIMEOUT
            )
            
            logger.info(f"工具调用完成，生成最终回答")
            
            return final_response.choices[0].message.content or ""
            
        except Exception as e:
            logger.error(f"工具调用失败: {str(e)}")
            return f"处理失败: {str(e)}"

    def chat_with_tools_stream(self, messages, temperature=0.7):
        """流式工具调用 —— 逐个 token 输出"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=temperature,
                stream=True,
                timeout=_LLM_TIMEOUT
            )
            
            # 收集流式 tool_calls（需要累积）
            tool_call_buffers = {}
            final_content = []
            has_tool_calls = False
            
            for chunk in response:
                delta = chunk.choices[0].delta
                
                # 检测 tool_calls
                if delta.tool_calls:
                    has_tool_calls = True
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_call_buffers:
                            tool_call_buffers[idx] = {
                                "id": "", "name": "", "arguments": ""
                            }
                        if tc.id:
                            tool_call_buffers[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_call_buffers[idx]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            tool_call_buffers[idx]["arguments"] += tc.function.arguments
                    continue
                
                # 普通文本内容 → 直接 yield
                if delta.content:
                    yield delta.content
            
            # 如果有工具调用，执行后流式输出最终回答
            if has_tool_calls and tool_call_buffers:
                # 构造 assistant message
                assistant_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": buf["id"],
                            "type": "function",
                            "function": {
                                "name": buf["name"],
                                "arguments": buf["arguments"]
                            }
                        }
                        for buf in tool_call_buffers.values()
                    ]
                }
                messages.append(assistant_msg)
                
                # 执行工具
                for buf in tool_call_buffers.values():
                    tool_name = buf["name"]
                    tool_args = json.loads(buf["arguments"]) if buf["arguments"] else {}
                    logger.info(f"流式工具调用: {tool_name}, 参数: {tool_args}")
                    
                    if tool_name in TOOLS_MAP:
                        result = TOOLS_MAP[tool_name](**tool_args)
                    else:
                        result = json.dumps({"error": f"未知工具: {tool_name}"})
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": buf["id"],
                        "content": result
                    })
                
                # 流式生成最终回答
                yield "\n"  # 分隔
                for token in self.chat_stream(messages, temperature):
                    yield token
                    
        except Exception as e:
            logger.error(f"流式工具调用失败: {str(e)}")
            yield f"错误: {str(e)}"

    def chat_stream(self, messages, temperature=0.7):
        """流式对话"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=True,
                timeout=_LLM_TIMEOUT
            )
            
            for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"流式调用失败: {str(e)}")
            yield f"错误: {str(e)}"
            
    def chat_with_context(self, messages: List[Dict], history: List[Dict] = None, 
                       temperature: float = 0.7) -> str:
        """带上下文的对话"""
        all_messages = []
        
        # 添加系统提示
        all_messages.append({
            "role": "system",
            "content": "你是一个智能助手，请基于对话历史理解上下文，连贯地回答用户问题。"
        })
        
        # 添加历史消息
        if history:
            all_messages.extend(history)
        
        # 添加当前消息
        all_messages.extend(messages)
        
        return self.chat(all_messages, temperature)
    
    def chat(self, messages, temperature=0.7):
        """普通对话（不使用工具）"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                timeout=_LLM_TIMEOUT
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM调用失败: {str(e)}")
            return f"LLM调用失败: {str(e)}"

llm_client = LLMClient()