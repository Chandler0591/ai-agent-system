import json
import uuid
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from app.logger import logger 
from app.context_compressor import context_compressor
from app.config import config

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis 模块未安装，将使用内存存储")


class SessionManager:
    """会话管理器 - 支持 Redis 和内存两种存储"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_client = None
        self.memory_sessions = {}
        
        if REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                self.redis_client.ping()
                logger.info("Redis 会话存储已启用")
            except Exception as e:
                logger.warning(f"Redis 连接失败，使用内存存储: {e}")
                self.redis_client = None
        
        # 会话配置
        self.max_history = 20  # 最多保留20条消息
        self.ttl_seconds = 3600  # 会话过期时间（1小时）
    
    def _get_key(self, session_id: str) -> str:
        """生成 Redis key"""
        return f"session:{session_id}"
    
    def create_session(self, session_id: str = None) -> str:
        """创建新会话"""
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        session_data = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "messages": [],
            "metadata": {}
        }
        
        if self.redis_client:
            self.redis_client.setex(
                self._get_key(session_id),
                self.ttl_seconds,
                json.dumps(session_data)
            )
        else:
            self.memory_sessions[session_id] = session_data
        
        logger.info(f"创建会话: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """获取会话"""
        if self.redis_client:
            data = self.redis_client.get(self._get_key(session_id))
            if data:
                return json.loads(data)
        else:
            return self.memory_sessions.get(session_id)
        
        return None
    
    def add_message(self, session_id: str, role: str, content: str, metadata: Dict = None):
        """添加消息到会话"""
        session = self.get_session(session_id)
        if not session:
            session_id = self.create_session(session_id)
            session = self.get_session(session_id)
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        session["messages"].append(message)
        
        # 限制历史长度（保留最近的消息）
        if len(session["messages"]) > self.max_history:
            session["messages"] = session["messages"][-self.max_history:]
        
        session["updated_at"] = datetime.now().isoformat()
        
        # 保存
        if self.redis_client:
            self.redis_client.setex(
                self._get_key(session_id),
                self.ttl_seconds,
                json.dumps(session)
            )
        else:
            self.memory_sessions[session_id] = session
        
        logger.info(f"会话 {session_id[:8]}... 添加消息: {role}")
    
    def get_history(self, session_id: str, limit: int = None) -> List[Dict]:
        """获取对话历史"""
        session = self.get_session(session_id)
        if not session:
            return []
        
        messages = session.get("messages", [])
        if limit:
            messages = messages[-limit:]
        
        return messages
    
    def get_context_messages(self, session_id: str, max_tokens: int = 2000) -> List[Dict]:
        """获取用于 LLM 的上下文消息（自动压缩）"""
        
        messages = self.get_history(session_id)
        if not messages:
            return []
        
        # 1. 先检查是否需要压缩
        if context_compressor.needs_compression(messages):
            logger.info(f"对话历史过长，触发压缩: {len(messages)}条")
            return context_compressor.compress(messages)
        
        # 2. 无需压缩时，按 token 数截断（从最新消息倒着取）
        context = []
        total_tokens = 0
        
        for msg in reversed(messages):
            msg_tokens = context_compressor.estimate_tokens(msg["content"])
            if total_tokens + msg_tokens > max_tokens:
                break
            context.insert(0, msg)
            total_tokens += msg_tokens
        
        return context
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        if self.redis_client:
            return bool(self.redis_client.delete(self._get_key(session_id)))
        else:
            if session_id in self.memory_sessions:
                del self.memory_sessions[session_id]
                return True
        return False
    
    def list_sessions(self, limit: int = 50) -> List[Dict]:
        """列出所有会话（Redis + 内存双模式）"""
        sessions = []
        
        if self.redis_client:
            # 使用 SCAN 遍历所有 session:* key
            pattern = "session:*"
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                for key in keys:
                    if len(sessions) >= limit:
                        break
                    data = self.redis_client.get(key)
                    if data:
                        try:
                            session = json.loads(data)
                            sessions.append({
                                "session_id": session.get("session_id", key),
                                "created_at": session.get("created_at"),
                                "updated_at": session.get("updated_at"),
                                "message_count": len(session.get("messages", []))
                            })
                        except json.JSONDecodeError:
                            pass
                if cursor == 0 or len(sessions) >= limit:
                    break
            sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        else:
            for session_id, data in list(self.memory_sessions.items())[:limit]:
                sessions.append({
                    "session_id": session_id,
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "message_count": len(data.get("messages", []))
                })
        
        return sessions[:limit]
    
    def clear_all(self):
        """清空所有会话（Redis + 内存双模式）"""
        if self.redis_client:
            # 使用 SCAN 遍历并删除所有 session:* key
            pattern = "session:*"
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = self.redis_client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    self.redis_client.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
            logger.info(f"已清空 {deleted} 个 Redis 会话")
        else:
            count = len(self.memory_sessions)
            self.memory_sessions.clear()
            logger.info(f"已清空 {count} 个内存会话")


# 全局实例
session_manager = SessionManager(config.REDIS_URL)