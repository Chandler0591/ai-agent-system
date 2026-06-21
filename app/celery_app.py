"""
Celery 实例 —— 异步任务队列
启动 worker: celery -A app.celery_app worker --loglevel=info --concurrency=4
启动 flower: celery -A app.celery_app flower --port=5555
"""
from celery import Celery
from app.config import config

celery_app = Celery(
    "ai_agent_tasks",
    broker=config.CELERY_BROKER_URL,
    backend=config.CELERY_RESULT_BACKEND,
    include=["app.tasks"],  # 自动发现任务模块
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,       # 单个任务最长 10 分钟
    task_soft_time_limit=540,  # 软超时 9 分钟（触发 SoftTimeLimitExceeded）
    worker_max_tasks_per_child=200,  # 防止内存泄漏
    result_expires=3600,       # 结果保留 1 小时
)
