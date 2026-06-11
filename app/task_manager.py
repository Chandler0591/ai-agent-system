import os
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from app.logger import logger

from app.knowledge_base import knowledge_base

class TaskManager:
    """异步任务管理器"""
    
    def __init__(self):
        self.tasks: Dict[str, Dict] = {}
    
    def create_task(self, task_type: str, params: Dict) -> str:
        """创建任务"""
        task_id = params.get("task_id") or str(uuid.uuid4())
        self.tasks[task_id] = {
            "id": task_id,
            "type": task_type,
            "params": params,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "result": None,
            "error": None
        }
        logger.info(f"创建任务: {task_id}, 类型: {task_type}")
        return task_id
    
    def update_task(self, task_id: str, status: str, result: Any = None, error: str = None):
        """更新任务状态"""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
            if result is not None:
                self.tasks[task_id]["result"] = result
            if error is not None:
                self.tasks[task_id]["error"] = error
            self.tasks[task_id]["updated_at"] = datetime.now().isoformat()
            logger.info(f"任务更新: {task_id} -> {status}")
        else:
            logger.warning(f"任务不存在: {task_id}")
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务信息"""
        return self.tasks.get(task_id)
    
    def get_tasks(self, limit: int = 50) -> list:
        """获取任务列表"""
        tasks = list(self.tasks.values())
        tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return tasks[:limit]


# 全局实例
task_manager = TaskManager()


# ========== 异步任务函数 ==========
def process_pdf_background(task_id: str, file_path: str, filename: str):
    """
    后台处理 PDF
    """
    
    try:
        task_manager.update_task(task_id, "processing")
        logger.info(f"开始处理 PDF: {filename}, task_id: {task_id}")
        
        # 调用知识库添加 PDF
        result = knowledge_base.add_pdf(file_path, filename)
        
        # 删除临时文件
        if os.path.exists(file_path):
            os.unlink(file_path)
        
        task_manager.update_task(task_id, "completed", result=result)
        logger.info(f"PDF 处理完成: {filename}, 块数: {result.get('chunks', 0)}")
        
    except Exception as e:
        logger.error(f"PDF 处理失败: {str(e)}")
        task_manager.update_task(task_id, "failed", error=str(e))
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
        except:
            pass