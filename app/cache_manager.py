import hashlib
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import redis
from app.logger import logger

class CacheManager:
    """缓存管理器 - 使用Redis"""
    
    def __init__(self, redis_url: str = "redis://localhost:6380"):
        self.redis_client = None
        self.use_redis = False
        
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.redis_client.ping()
            self.use_redis = True
            logger.info("Redis缓存已启用")
        except Exception as e:
            logger.warning(f"Redis不可用，使用内存缓存: {str(e)}")
            self.memory_cache = {}
    
    def _get_key(self, prefix: str, query: str, **kwargs) -> str:
        """生成缓存key"""
        data = {"query": query, **kwargs}
        key_str = f"{prefix}:{json.dumps(data, sort_keys=True)}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get_embeddings(self, text: str) -> Optional[list]:
        """获取缓存的向量"""
        key = self._get_key("emb", text)
        
        if self.use_redis:
            cached = self.redis_client.get(key)
            if cached:
                return json.loads(cached)
        else:
            if key in self.memory_cache:
                return self.memory_cache[key]
        
        return None
    
    def set_embeddings(self, text: str, embedding: list, ttl: int = 3600):
        """缓存向量"""
        key = self._get_key("emb", text)
        
        if self.use_redis:
            self.redis_client.setex(key, ttl, json.dumps(embedding))
        else:
            self.memory_cache[key] = embedding
    
    def get_search_results(self, query: str, top_k: int) -> Optional[list]:
        """获取缓存的搜索结果"""
        key = self._get_key("search", query, top_k=top_k)
        
        if self.use_redis:
            cached = self.redis_client.get(key)
            if cached:
                return json.loads(cached)
        else:
            if key in self.memory_cache:
                return self.memory_cache[key]
        
        return None
    
    def set_search_results(self, query: str, top_k: int, results: list, ttl: int = 300):
        """缓存搜索结果（5分钟）"""
        key = self._get_key("search", query, top_k=top_k)
        
        # 只缓存可序列化的数据，并处理numpy类型
        serializable_results = []
        for r in results:
            if isinstance(r, dict):
                clean = {}
                for k, v in r.items():
                    if hasattr(v, 'item'):  # numpy scalar
                        clean[k] = v.item()
                    elif isinstance(v, (int, float, str, bool, list, dict, type(None))):
                        clean[k] = v
                    else:
                        clean[k] = str(v)
                serializable_results.append(clean)
        
        if self.use_redis:
            self.redis_client.setex(key, ttl, json.dumps(serializable_results))
        else:
            self.memory_cache[key] = serializable_results
    
    def clear(self):
        """清空缓存"""
        if self.use_redis:
            # 使用 scan 遍历所有key并删除
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(cursor=cursor, count=100)
                if keys:
                    self.redis_client.delete(*keys)
                if cursor == 0:
                    break
        else:
            self.memory_cache.clear()
        logger.info("缓存已清空")

# 全局实例
cache_manager = CacheManager()