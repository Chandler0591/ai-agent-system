from typing import List, Dict
from app.llm_client import llm_client
from app.logger import logger

class ContextCompressor:
    """对话上下文压缩器 - 防止 token 溢出"""
    
    def __init__(self, max_tokens: int = 3000):
        self.max_tokens = max_tokens
        self.compress_prompt = """请将以下对话历史压缩成简洁的摘要，保留关键信息（用户意图、重要事实、已完成的动作）。

对话历史：
{history}

压缩后的摘要："""
    
    def estimate_tokens(self, text: str) -> int:
        """估算 token 数"""
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.5)
    
    def needs_compression(self, messages: List[Dict]) -> bool:
        """检查是否需要压缩"""
        total_tokens = sum(self.estimate_tokens(msg["content"]) for msg in messages)
        return total_tokens > self.max_tokens
    
    def compress(self, messages: List[Dict]) -> List[Dict]:
        """压缩对话历史"""
        if not messages:
            return messages
        
        # 构建对话文本
        history_text = []
        for msg in messages:
            role = "用户" if msg["role"] == "user" else "助手"
            history_text.append(f"{role}: {msg['content']}")
        
        history = "\n".join(history_text)
        
        # 调用 LLM 压缩
        prompt = self.compress_prompt.format(history=history)
        try:
            compressed = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.3)
            logger.info(f"对话压缩完成: {len(history)} -> {len(compressed)} 字符")
            
            # 返回压缩后的系统消息
            return [{
                "role": "system",
                "content": f"【对话历史摘要】{compressed}\n\n请基于以上历史继续对话。"
            }]
        except Exception as e:
            logger.error(f"压缩失败: {e}")
            # 失败时保留最后5条消息
            return messages[-5:]
    
    def smart_truncate(self, messages: List[Dict], max_messages: int = 20) -> List[Dict]:
        """智能截断：保留系统消息 + 最近的对话"""
        result = []
        
        # 保留系统消息
        for msg in messages:
            if msg.get("role") == "system":
                result.append(msg)
        
        # 保留最近的对话
        recent = [m for m in messages if m.get("role") != "system"][-max_messages:]
        result.extend(recent)
        
        return result


# 全局实例
context_compressor = ContextCompressor()