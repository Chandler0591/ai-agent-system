"""
JWT 认证中间件 —— 保护 API 端点
用法: @app.get("/path", dependencies=[Depends(verify_token)])

生产级特性:
- HS256 签名 + 过期时间 + JTI 黑名单（Redis TTL 自动过期）
- Redis 不可用时降级到内存 set（开发/单机场景）
"""
import uuid
import jwt
import redis as redis_lib
from fastapi import Header, HTTPException, Depends
from datetime import datetime, timedelta
from typing import Optional
from app.config import config
from app.logger import logger

# 内存黑名单（Redis 不可用时的 fallback）
_token_blacklist: set = set()

# 惰性 Redis 连接
_redis_client = None


def _get_redis():
    """获取 Redis 客户端（惰性连接，带缓存）"""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis_lib.from_url(config.REDIS_URL, decode_responses=True)
            _redis_client.ping()
            logger.info("Token 黑名单: Redis 已连接")
        except Exception as e:
            logger.warning(f"Token 黑名单: Redis 不可用 ({e})，降级为内存存储")
            _redis_client = False  # 标记"已尝试但失败"
    return _redis_client if _redis_client is not False else None


def create_access_token(
    username: str,
    tenant_id: str = "default",
    role: str = "user",
    expires_minutes: int = None
) -> str:
    """生成 JWT token（含 JTI 用于黑名单）"""
    expire = datetime.utcnow() + timedelta(
        minutes=expires_minutes or config.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": username,
        "tenant_id": tenant_id,
        "role": role,
        "jti": str(uuid.uuid4()),    # JWT ID — 用于精确撤销
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")


def decode_token(token: str, verify_exp: bool = True) -> dict:
    """解码并验证 JWT"""
    options = {} if verify_exp else {"verify_exp": False}
    return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"], options=options)


def revoke_token(token: str):
    """
    撤销 token（加入黑名单）
    - Redis 模式: key=blacklist:{jti}, TTL=剩余有效期，自动过期
    - 内存模式: fallback 到 set（服务重启后清空）
    """
    try:
        # 不验证过期 —— 因为可能撤销一个仍在有效期的 token
        payload = decode_token(token, verify_exp=False)
        jti = payload.get("jti")
        exp = payload.get("exp", 0)
        now_ts = datetime.utcnow().timestamp()
        ttl = max(int(exp - now_ts), 1)  # 至少保留 1 秒

        r = _get_redis()
        if r:
            r.setex(f"blacklist:{jti}", ttl, "1")
            logger.info(f"Token 已撤销: jti={jti[:8]}..., ttl={ttl}s")
        else:
            _token_blacklist.add(jti)
            logger.info(f"Token 已撤销（内存）: jti={jti[:8]}...")
    except jwt.InvalidTokenError:
        logger.warning("尝试撤销无效 token（忽略）")
    except Exception as e:
        logger.error(f"撤销 token 失败: {e}")


async def verify_token(authorization: Optional[str] = Header(None)) -> dict:
    """
    FastAPI 依赖注入 —— 验证 Bearer token
    三位一体: HS256 签名 → 过期时间 → JTI 黑名单
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证令牌")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="认证格式错误，需 Bearer token")

    try:
        payload = decode_token(token)
        jti = payload.get("jti")

        # JTI 黑名单检查（Redis 优先 → 内存 fallback）
        r = _get_redis()
        if r and jti:
            if r.exists(f"blacklist:{jti}"):
                raise HTTPException(status_code=401, detail="令牌已失效")
        elif jti and jti in _token_blacklist:
            raise HTTPException(status_code=401, detail="令牌已失效")

        return payload  # {"sub": username, "tenant_id": ..., "role": ..., "jti": ...}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效令牌")
    except HTTPException:
        raise



async def get_tenant_id(payload: dict = Depends(verify_token)) -> str:
    """从 JWT 提取 tenant_id"""
    return payload.get("tenant_id", "default")


async def get_current_user(payload: dict = Depends(verify_token)) -> str:
    """从 JWT 提取用户名"""
    return payload.get("sub", "anonymous")
