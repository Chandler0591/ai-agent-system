"""
数据库初始化脚本 —— 建表 + 种子数据
用法:
  python scripts/init_db.py              # 建表 + 默认租户
  python scripts/init_db.py --tables-only  # 仅建表
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import config
from app.logger import logger

# ---------- PostgreSQL 直连建表 ----------
def init_pg_tables():
    """直接连 PG 建表（不依赖 app.database 单例）"""
    try:
        import psycopg2
        dsn = config.DATABASE_URL.replace("postgresql://", "postgres://")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("""
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
        """)
        cur.execute("""
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
        """)
        cur.execute("""
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
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              SERIAL PRIMARY KEY,
                username        VARCHAR(64) UNIQUE NOT NULL,
                password_hash   VARCHAR(256) NOT NULL DEFAULT '',
                email           VARCHAR(128),
                is_active       BOOLEAN DEFAULT TRUE,
                created_at      TIMESTAMP DEFAULT NOW(),
                updated_at      TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.execute("""
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
        """)
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️  PG 建表失败: {e}")
        return False


if __name__ == "__main__":
    tables_only = "--tables-only" in sys.argv

    if init_pg_tables():
                print("✅ 表结构创建完成: tenants, sessions, tasks, users, user_tenants")
    else:
        print("⚠️  跳过表创建（PG 不可用）")
        sys.exit(1 if not tables_only else 0)

    if not tables_only:
        try:
            from app.database import database_manager
            if database_manager.available:
                database_manager.create_tenant(tenant_id="default", name="默认租户(共享)")
                database_manager.create_tenant(tenant_id="demo1", name="演示租户1")
                database_manager.create_tenant(tenant_id="demo2", name="演示租户2")
                print("✅ 租户: default(共享), demo1, demo2")

                # 种子用户 + 租户关联
                database_manager.create_user("admin", "admin123")
                database_manager.create_user("demo1", "demo1123")
                database_manager.create_user("demo2", "demo2123")
                database_manager.add_user_to_tenant("admin", "default", "admin")
                database_manager.add_user_to_tenant("demo1", "demo1", "user")
                database_manager.add_user_to_tenant("demo2", "demo2", "user")
                print("✅ 用户: admin(admin123, default/admin), demo1(demo1123, demo1), demo2(demo2123, demo2)")
        except Exception as e:
            print(f"⚠️  种子数据写入跳过: {e}")
