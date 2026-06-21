"""
API 限流中间件 —— Redis 原子滑动窗口（生产级）

特性:
- Redis + Lua 脚本保证原子性（多进程安全）
- ZSET 滑动窗口算法，精确到毫秒
- Redis 不可用时自动降级到内存计数
- 可跳过白名单路径（health/live/ready）
"""
import time
import redis as redis_lib
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
from typing import Dict, List
from app.config import config
from app.logger import logger

# ========== Lua 原子滑动窗口脚本 ==========
# KEYS[1]: 限流 key（如 rate_limit:{ip}）
# ARGV[1]: 当前时间戳（毫秒）
# ARGV[2]: 窗口大小（毫秒）
# ARGV[3]: 窗口内最大请求数
# 返回: {allowed (1|0), current_count}
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

-- 清理窗口外的过期记录
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)

-- 统计当前窗口内请求数
local count = redis.call('ZCARD', key)

if count >= limit then
    return {0, count}
end

-- 添加当前请求（score=timestamp, member=timestamp:random 防冲突）
redis.call('ZADD', key, now, now .. ':' .. math.random(1000000))
redis.call('EXPIRE', key, math.ceil(window / 1000) + 1)

return {1, count + 1}
"""

# 内存降级计数器（Redis 不可用时）
_memory_counters: Dict[str, List[float]] = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    滑动窗口限流中间件
    - Redis + Lua: 原子操作，多进程安全
    - 内存 fallback: 单进程部署场景
    """

    def __init__(self, app, max_requests: int = None, window: int = None):
        super().__init__(app)
        self.max_requests = max_requests or config.API_RATE_LIMIT
        self.window = window or config.API_RATE_WINDOW
        self._redis = None
        self._redis_checked = False

    def _get_redis(self):
        """惰性 Redis 连接"""
        if not self._redis_checked:
            self._redis_checked = True
            try:
                self._redis = redis_lib.from_url(config.REDIS_URL, decode_responses=True)
                self._redis.ping()
                # 预加载 Lua 脚本
                self._lua_sha = self._redis.script_load(_SLIDING_WINDOW_LUA)
                logger.info(f"限流器: Redis + Lua 已就绪 (SHA: {self._lua_sha[:12]}...)")
            except Exception as e:
                logger.warning(f"限流器: Redis 不可用 ({e})，降级为内存计数")
                self._redis = None
        return self._redis

    async def dispatch(self, request: Request, call_next):
        # 跳过白名单路径
        if request.url.path in ("/api/health", "/api/live", "/api/ready", "/", "/web") \
                or request.url.path.startswith("/api/task/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now_ms = int(time.time() * 1000)
        window_ms = self.window * 1000

        r = self._get_redis()

        if r:
            # ==== Redis 原子滑动窗口 ====
            key = f"rate_limit:{client_ip}"
            try:
                allowed, count = r.evalsha(
                    self._lua_sha, 1, key,
                    str(now_ms), str(window_ms), str(self.max_requests)
                )
                allowed, count = int(allowed), int(count)
            except Exception:
                # Lua SHA 失效时重新加载
                try:
                    self._lua_sha = r.script_load(_SLIDING_WINDOW_LUA)
                    allowed, count = r.evalsha(
                        self._lua_sha, 1, key,
                        str(now_ms), str(window_ms), str(self.max_requests)
                    )
                    allowed, count = int(allowed), int(count)
                except Exception as e:
                    logger.error(f"限流器 Lua 执行失败: {e}")
                    return await call_next(request)  # 宽容处理

            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail=f"请求过于频繁，每分钟上限 {self.max_requests} 次"
                )
        else:
            # ==== 内存 fallback ====
            now = time.time()
            _memory_counters[client_ip] = [
                t for t in _memory_counters[client_ip] if now - t < self.window
            ]
            if len(_memory_counters[client_ip]) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=f"请求过于频繁，每分钟上限 {self.max_requests} 次"
                )
            _memory_counters[client_ip].append(now)

        return await call_next(request)
