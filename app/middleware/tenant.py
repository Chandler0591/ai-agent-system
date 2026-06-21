"""
多租户隔离中间件 —— 从 Header/Token 提取 tenant_id 注入路由上下文
"""
import contextvars
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# ContextVar 实现请求级租户隔离（协程安全）
current_tenant: contextvars.ContextVar = contextvars.ContextVar(
    "current_tenant", default="default"
)


class TenantMiddleware(BaseHTTPMiddleware):
    """从 X-Tenant-Id Header 提取租户信息"""

    async def dispatch(self, request: Request, call_next):
        tenant_id = request.headers.get("X-Tenant-Id", "default")
        token = current_tenant.set(tenant_id)
        try:
            response = await call_next(request)
            return response
        finally:
            current_tenant.reset(token)


def get_tenant_from_context() -> str:
    """获取当前请求的租户 ID"""
    try:
        return current_tenant.get()
    except LookupError:
        return "default"
