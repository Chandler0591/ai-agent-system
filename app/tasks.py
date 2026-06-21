"""
Celery 异步任务定义
使用方式:
    from app.tasks import process_pdf_async
    task = process_pdf_async.delay(task_id, file_path, filename)
    result = task.get(timeout=300)  # 同步等待结果
"""
import os
from app.celery_app import celery_app
from app.knowledge_base import knowledge_base
from app.logger import logger


@celery_app.task(bind=True, name="process_pdf", max_retries=2, default_retry_delay=30)
def process_pdf_async(self, task_id: str, file_path: str, filename: str, tenant_id: str = "default", force: bool = False) -> dict:
    """
    后台异步处理 PDF 文件

    Args:
        task_id: 任务ID（关联前端轮询）
        file_path: PDF 临时文件路径
        filename: 原始文件名
        tenant_id: 租户标识

    Returns:
        {"status": "success", "chunks": 23}
    """
    logger.info(f"[Celery] 开始处理 PDF: {filename}, task_id: {task_id}, tenant={tenant_id}")

    try:
        result = knowledge_base.add_pdf(file_path, filename, tenant_id=tenant_id, skip_duplicate=not force)

        # 清理临时文件
        if os.path.exists(file_path):
            os.unlink(file_path)

        logger.info(f"[Celery] PDF 处理完成: {filename}, 块数: {result.get('chunks', 0)}")
        return {
            "status": "success",
            "file": filename,
            "chunks": result.get("chunks", 0),
            "task_id": task_id,
        }

    except Exception as e:
        logger.error(f"[Celery] PDF 处理失败: {str(e)}")
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
        except Exception:
            pass
        # 自动重试
        raise self.retry(exc=e, countdown=30)


@celery_app.task(name="cleanup_temp_files")
def cleanup_temp_files(temp_dir: str = "/app/tmp", max_age_hours: int = 24):
    """定期清理临时文件"""
    import time
    cutoff = time.time() - max_age_hours * 3600
    deleted = 0
    try:
        for fname in os.listdir(temp_dir):
            fpath = os.path.join(temp_dir, fname)
            if os.path.isfile(fpath) and fname.endswith(".pdf"):
                if os.path.getmtime(fpath) < cutoff:
                    os.unlink(fpath)
                    deleted += 1
        logger.info(f"[Celery] 清理了 {deleted} 个临时文件")
    except Exception as e:
        logger.warning(f"[Celery] 临时文件清理失败: {e}")


# 定时任务配置（Celery Beat 调度）
celery_app.conf.beat_schedule = {
    "cleanup-every-6h": {
        "task": "cleanup_temp_files",
        "schedule": 21600.0,  # 6 小时
    },
}
