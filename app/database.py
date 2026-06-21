"""
生产级数据库管理 —— psycopg2 连接池 + 多租户

表结构:
- tenants:     租户表（配额管理）
- sessions:    会话历史表（多租户隔离）
- tasks:       异步任务表（状态追踪）

依赖: pip install psycopg2-binary
不可用时降级到 MemoryDB
"""
import json
import time
import threading
from typing import List, Dict, Optional, Any
from contextlib import contextmanager
from datetime import datetime
from app.config import config
from app.logger import logger

try:
    import psycopg2
    from psycopg2 import pool, sql
    PG_AVAILABLE = True
except ImportError:
    PG_AVAILABLE = False
    logger.warning("psycopg2 未安装，使用 MemoryDB 降级")


class MemoryDB:
    """内存数据库（PostgreSQL 不可用时的 fallback）"""
    def __init__(self):
        self.documents = []

    def insert(self, doc: Dict):
        self.documents.append(doc)
        return len(self.documents) - 1

    def query(self, sql: str) -> List[Dict]:
        return self.documents

    def search_by_keyword(self, keyword: str) -> List[Dict]:
        results = []
        for doc in self.documents:
            if keyword in json.dumps(doc):
                results.append(doc)
        return results


# ==================== PostgreSQL DatabaseManager ====================

class DatabaseManager:
    """
    生产级 PostgreSQL 连接池管理器
    支持: 多租户 sessions、tasks、tenants 三张核心表
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._pool = None
        self._available = False
        if PG_AVAILABLE:
            self._init_pool()

    def _init_pool(self):
        """初始化连接池（含重试，适应 Docker 容器启动顺序）"""
        import time
        dsn = config.DATABASE_URL.replace("postgresql://", "postgres://")
        last_err = None
        for attempt in range(10):
            try:
                self._pool = pool.ThreadedConnectionPool(
                    minconn=2,
                    maxconn=10,
                    dsn=dsn
                )
                with self._get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                self._available = True
                self._init_tables()
                logger.info("PostgreSQL 连接池已就绪 (min=2, max=10)")
                return
            except Exception as e:
                last_err = e
                if self._pool:
                    self._pool.closeall()
                    self._pool = None
                if attempt < 9:
                    logger.info(f"PostgreSQL 连接重试 {attempt+1}/10（{e}）")
                    time.sleep(3)
        logger.warning(f"PostgreSQL 不可用（重试10次后放弃: {last_err}），降级为 MemoryDB")

    @contextmanager
    def _get_conn(self):
        """获取连接（上下文管理器）"""
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def _init_tables(self):
        """创建核心表（幂等）"""
        ddl = """
        CREATE TABLE IF NOT EXISTS tenants (
            id              SERIAL PRIMARY KEY,
            name            VARCHAR(128) UNIQUE NOT NULL,
            tenant_id       VARCHAR(64) UNIQUE NOT NULL,
            role            VARCHAR(32) DEFAULT 'user',
            document_quota  INTEGER DEFAULT 1000,
            api_call_quota  INTEGER DEFAULT 10000,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id              SERIAL PRIMARY KEY,
            session_id      VARCHAR(64) UNIQUE NOT NULL,
            tenant_id       VARCHAR(64) NOT NULL DEFAULT 'default',
            data_json       JSONB DEFAULT '{}'::jsonb,
            message_count   INTEGER DEFAULT 0,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON sessions(tenant_id);

        CREATE TABLE IF NOT EXISTS tasks (
            id              SERIAL PRIMARY KEY,
            task_id         VARCHAR(64) UNIQUE NOT NULL,
            tenant_id       VARCHAR(64) NOT NULL DEFAULT 'default',
            task_type       VARCHAR(64) NOT NULL,
            status          VARCHAR(32) DEFAULT 'pending',
            params_json     JSONB DEFAULT '{}'::jsonb,
            result_json     JSONB DEFAULT '{}'::jsonb,
            error           TEXT,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_tenant ON tasks(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

        CREATE TABLE IF NOT EXISTS users (
            id              SERIAL PRIMARY KEY,
            username        VARCHAR(64) UNIQUE NOT NULL,
            password_hash   VARCHAR(256) NOT NULL DEFAULT '',
            email           VARCHAR(128),
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS user_tenants (
            id              SERIAL PRIMARY KEY,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id       VARCHAR(64) NOT NULL,
            role            VARCHAR(32) DEFAULT 'user',
            created_at      TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, tenant_id)
        );
        CREATE INDEX IF NOT EXISTS idx_user_tenants_user ON user_tenants(user_id);
        CREATE INDEX IF NOT EXISTS idx_user_tenants_tenant ON user_tenants(tenant_id);
        """
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
        logger.info("数据库表初始化完成: tenants, sessions, tasks")

    @property
    def available(self) -> bool:
        return self._available and self._pool is not None

    # ========== Sessions ==========

    def create_session(self, session_id: str, tenant_id: str = "default",
                       data: Dict = None) -> bool:
        """创建会话记录"""
        if not self.available:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO sessions (session_id, tenant_id, data_json)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (session_id) DO NOTHING""",
                        (session_id, tenant_id, json.dumps(data or {}))
                    )
            return True
        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            return False

    def get_session(self, session_id: str) -> Optional[Dict]:
        """获取会话"""
        if not self.available:
            return None
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT session_id, tenant_id, data_json, created_at, updated_at "
                        "FROM sessions WHERE session_id = %s",
                        (session_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return {
                            "session_id": row[0],
                            "tenant_id": row[1],
                            "data": row[2],
                            "created_at": row[3].isoformat() if row[3] else None,
                            "updated_at": row[4].isoformat() if row[4] else None,
                        }
        except Exception as e:
            logger.error(f"获取会话失败: {e}")
        return None

    def update_session(self, session_id: str, data: Dict) -> bool:
        """更新会话数据"""
        if not self.available:
            return False
        try:
            msg_count = len(data.get("messages", []))
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE sessions SET data_json = %s, message_count = %s,
                           updated_at = NOW() WHERE session_id = %s""",
                        (json.dumps(data), msg_count, session_id)
                    )
            return True
        except Exception as e:
            logger.error(f"更新会话失败: {e}")
            return False

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        if not self.available:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
                    return cur.rowcount > 0
        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            return False

    def list_sessions(self, tenant_id: str = None, limit: int = 50) -> List[Dict]:
        """列出会话"""
        if not self.available:
            return []
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    if tenant_id:
                        cur.execute(
                            """SELECT session_id, tenant_id, message_count, created_at, updated_at
                               FROM sessions WHERE tenant_id = %s
                               ORDER BY updated_at DESC LIMIT %s""",
                            (tenant_id, limit)
                        )
                    else:
                        cur.execute(
                            """SELECT session_id, tenant_id, message_count, created_at, updated_at
                               FROM sessions ORDER BY updated_at DESC LIMIT %s""",
                            (limit,)
                        )
                    return [
                        {
                            "session_id": r[0],
                            "tenant_id": r[1],
                            "message_count": r[2],
                            "created_at": r[3].isoformat() if r[3] else None,
                            "updated_at": r[4].isoformat() if r[4] else None,
                        }
                        for r in cur.fetchall()
                    ]
        except Exception as e:
            logger.error(f"列出会话失败: {e}")
            return []

    # ========== Tasks ==========

    def create_task(self, task_id: str, task_type: str, tenant_id: str = "default",
                    params: Dict = None) -> bool:
        """创建任务记录"""
        if not self.available:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO tasks (task_id, tenant_id, task_type, params_json)
                           VALUES (%s, %s, %s, %s)""",
                        (task_id, tenant_id, task_type, json.dumps(params or {}))
                    )
            return True
        except Exception as e:
            logger.error(f"创建任务失败: {e}")
            return False

    def update_task(self, task_id: str, status: str, result: Dict = None,
                    error: str = None) -> bool:
        """更新任务状态"""
        if not self.available:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE tasks SET status = %s, result_json = %s, error = %s,
                           updated_at = NOW() WHERE task_id = %s""",
                        (status, json.dumps(result or {}), error, task_id)
                    )
            return True
        except Exception as e:
            logger.error(f"更新任务失败: {e}")
            return False

    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务"""
        if not self.available:
            return None
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT task_id, tenant_id, task_type, status, params_json, "
                        "result_json, error, created_at, updated_at "
                        "FROM tasks WHERE task_id = %s",
                        (task_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return {
                            "task_id": row[0],
                            "tenant_id": row[1],
                            "task_type": row[2],
                            "status": row[3],
                            "params": row[4],
                            "result": row[5],
                            "error": row[6],
                            "created_at": row[7].isoformat() if row[7] else None,
                            "updated_at": row[8].isoformat() if row[8] else None,
                        }
        except Exception as e:
            logger.error(f"获取任务失败: {e}")
        return None

    # ========== Tenants ==========

    def get_tenant(self, tenant_id: str) -> Optional[Dict]:
        """获取租户信息"""
        if not self.available:
            return None
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT name, tenant_id, role, document_quota, api_call_quota "
                        "FROM tenants WHERE tenant_id = %s",
                        (tenant_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return {
                            "name": row[0],
                            "tenant_id": row[1],
                            "role": row[2],
                            "document_quota": row[3],
                            "api_call_quota": row[4],
                        }
        except Exception as e:
            logger.error(f"获取租户失败: {e}")
        return None

    def create_tenant(self, name: str, tenant_id: str = None,
                      document_quota: int = 1000, api_call_quota: int = 10000) -> bool:
        """创建租户"""
        if not self.available:
            return False
        tenant_id = tenant_id or name
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO tenants (name, tenant_id, document_quota, api_call_quota)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (tenant_id) DO UPDATE SET name = EXCLUDED.name""",
                        (name, tenant_id, document_quota, api_call_quota)
                    )
            return True
        except Exception as e:
            logger.error(f"创建租户失败: {e}")
            return False

    def list_tenants(self) -> List[Dict]:
        """列出所有租户"""
        if not self.available:
            return []
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT tenant_id, name FROM tenants ORDER BY id")
                    rows = cur.fetchall()
                    return [{"tenant_id": r[0], "name": r[1]} for r in rows]
        except Exception as e:
            logger.error(f"列出租户失败: {e}")
            return []

    # ---- 用户管理 ----
    def create_user(self, username: str, password: str = "", email: str = "") -> Optional[int]:
        """创建用户，返回 user_id"""
        if not self.available:
            return None
        import hashlib
        pwd_hash = hashlib.sha256(password.encode()).hexdigest() if password else ""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO users (username, password_hash, email)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (username) DO NOTHING
                           RETURNING id""",
                        (username, pwd_hash, email)
                    )
                    row = cur.fetchone()
                    return row[0] if row else None
        except Exception as e:
            logger.error(f"创建用户失败: {e}")
            return None

    def get_user(self, username: str) -> Optional[Dict]:
        """根据用户名查询用户"""
        if not self.available:
            return None
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, username, password_hash, email, is_active FROM users WHERE username = %s",
                        (username,)
                    )
                    row = cur.fetchone()
                    if row:
                        return {"id": row[0], "username": row[1], "password_hash": row[2], "email": row[3], "is_active": row[4]}
        except Exception as e:
            logger.error(f"查询用户失败: {e}")
        return None

    def verify_password(self, username: str, password: str) -> bool:
        """验证用户密码"""
        import hashlib
        user = self.get_user(username)
        if not user or not user["is_active"]:
            return False
        if not user["password_hash"]:
            return True  # 空密码允许（开发模式）
        return user["password_hash"] == hashlib.sha256(password.encode()).hexdigest()

    # ---- 用户-租户关联 ----
    def add_user_to_tenant(self, username: str, tenant_id: str, role: str = "user") -> bool:
        """将用户关联到租户"""
        if not self.available:
            return False
        try:
            user = self.get_user(username)
            if not user:
                return False
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO user_tenants (user_id, tenant_id, role)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (user_id, tenant_id) DO NOTHING""",
                        (user["id"], tenant_id, role)
                    )
            return True
        except Exception as e:
            logger.error(f"关联用户租户失败: {e}")
            return False

    def get_user_tenants(self, username: str) -> List[Dict]:
        """获取用户关联的所有租户"""
        if not self.available:
            return []
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT t.tenant_id, t.name, ut.role
                           FROM user_tenants ut
                           JOIN users u ON ut.user_id = u.id
                           JOIN tenants t ON ut.tenant_id = t.tenant_id
                           WHERE u.username = %s""",
                        (username,)
                    )
                    rows = cur.fetchall()
                    return [{"tenant_id": r[0], "name": r[1], "role": r[2]} for r in rows]
        except Exception as e:
            logger.error(f"获取用户租户失败: {e}")
            return []

    def close(self):
        """关闭连接池"""
        if self._pool:
            self._pool.closeall()
            logger.info("PostgreSQL 连接池已关闭")


# 全局实例（单例）
database_manager = DatabaseManager()

# ========== 向后兼容出口 ==========
# 保持 db 引用，旧代码无需改动
db = MemoryDB()

# 插入测试数据
if not database_manager.available:
    assert isinstance(db, MemoryDB)
    db.insert({"title": "Docker教程", "content": "Docker是容器化平台"})
    db.insert({"title": "Python入门", "content": "Python是编程语言"})
