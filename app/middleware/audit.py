"""
审计中间件 —— 记录所有关键操作

数据库不可用时静默降级，不影响正常业务
"""
from app.database import database_manager
from app.logger import logger


def log_audit(tenant_id: str = "default", username: str = "anonymous",
              action: str = "", detail: str = "", ip_address: str = ""):
    """写入审计日志（异步安全）"""
    try:
        database_manager.add_audit_log(
            tenant_id=tenant_id,
            username=username,
            action=action,
            detail=detail,
            ip_address=ip_address,
        )
    except Exception as e:
        logger.debug(f"审计日志写入失败（非关键）: {e}")


# ---- 审计动作常量 ----
AUDIT_LOGIN = "login"
AUDIT_LOGOUT = "logout"
AUDIT_UPLOAD = "upload"
AUDIT_SEARCH = "search"
AUDIT_DELETE = "delete"
AUDIT_CHAT = "chat"
AUDIT_AGENT = "agent"
