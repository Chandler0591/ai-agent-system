"""
工作流追踪 + 重试机制
- 记录每个节点的执行状态和耗时
- 自动重试（指数退避）
- 导出 DOT 格式可视化
"""

import time
import asyncio
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from app.logger import logger


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    """工作流步骤"""
    name: str
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: float = 0.0
    error: Optional[str] = None
    retry_count: int = 0
    metadata: Dict = field(default_factory=dict)


@dataclass
class WorkflowRun:
    """一次工作流执行"""
    run_id: str
    name: str
    steps: List[WorkflowStep] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    status: StepStatus = StepStatus.PENDING
    total_retries: int = 0


class WorkflowTracker:
    """
    工作流追踪器 —— 记录、重试、可视化
    """

    def __init__(self):
        self.runs: Dict[str, WorkflowRun] = {}
        self._current_run: Optional[WorkflowRun] = None

    # ========== 生命周期 ==========

    def start_workflow(self, name: str, run_id: str = None) -> WorkflowRun:
        """开始一个工作流"""
        run_id = run_id or f"wf-{int(time.time())}"
        run = WorkflowRun(run_id=run_id, name=name)
        run.started_at = datetime.now()
        run.status = StepStatus.RUNNING
        self.runs[run_id] = run
        self._current_run = run
        logger.info(f"工作流开始: {name} ({run_id})")
        return run

    def finish_workflow(self, success: bool = True, error: str = None):
        """结束工作流"""
        if self._current_run:
            self._current_run.finished_at = datetime.now()
            self._current_run.status = StepStatus.SUCCESS if success else StepStatus.FAILED
            if error and self._current_run.steps:
                self._current_run.steps[-1].error = error
            elapsed = (self._current_run.finished_at - self._current_run.started_at).total_seconds()
            logger.info(
                f"工作流结束: {self._current_run.name} -> "
                f"{'成功' if success else '失败'} ({elapsed:.1f}s, "
                f"{len(self._current_run.steps)}步骤)"
            )
            self._current_run = None

    def add_step(self, name: str) -> WorkflowStep:
        """添加步骤"""
        if not self._current_run:
            self._current_run = WorkflowRun(
                run_id=f"wf-{int(time.time())}",
                name="unnamed"
            )
        step = WorkflowStep(name=name)
        self._current_run.steps.append(step)
        return step

    def start_step(self, name: str) -> WorkflowStep:
        """开始一个步骤"""
        step = self._get_or_create_step(name)
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now()
        return step

    def finish_step(self, name: str, success: bool = True, error: str = None):
        """完成一个步骤"""
        step = self._get_step(name)
        if step:
            step.finished_at = datetime.now()
            step.status = StepStatus.SUCCESS if success else StepStatus.FAILED
            step.error = error
            if step.started_at:
                step.duration_ms = (step.finished_at - step.started_at).total_seconds() * 1000

    # ========== 重试机制 ==========

    def retry_step(
        self,
        name: str,
        fn: Callable,
        max_retries: int = 3,
        base_delay: float = 1.0,
        backoff_factor: float = 2.0,
        *args, **kwargs
    ):
        """
        带指数退避的重试执行

        Args:
            name: 步骤名称
            fn: 要执行的函数
            max_retries: 最大重试次数
            base_delay: 初始延迟（秒）
            backoff_factor: 退避因子（每次 × N）
        """
        step = self._get_or_create_step(name)
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now()

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                result = fn(*args, **kwargs)
                step.finished_at = datetime.now()
                step.status = StepStatus.SUCCESS
                if step.started_at:
                    step.duration_ms = (step.finished_at - step.started_at).total_seconds() * 1000
                return result
            except Exception as e:
                last_error = e
                step.retry_count = attempt + 1
                if self._current_run:
                    self._current_run.total_retries += 1

                if attempt < max_retries:
                    delay = base_delay * (backoff_factor ** attempt)
                    logger.warning(
                        f"步骤 '{name}' 失败 (尝试 {attempt + 1}/{max_retries + 1}): "
                        f"{e}，{delay:.1f}s 后重试"
                    )
                    time.sleep(delay)
                    step.status = StepStatus.RETRYING
                else:
                    logger.error(f"步骤 '{name}' 最终失败: {e}")

        step.finished_at = datetime.now()
        step.status = StepStatus.FAILED
        step.error = str(last_error)
        if step.started_at:
            step.duration_ms = (step.finished_at - step.started_at).total_seconds() * 1000
        raise last_error

    # ========== 可视化 ==========

    def to_dot(self, run_id: str = None) -> str:
        """导出为 Graphviz DOT 格式"""
        target = self.runs.get(run_id) if run_id else self._current_run
        if not target or not target.steps:
            return "digraph { label=\"无数据\"; }"

        lines = ['digraph G {']
        lines.append(f'  label="{target.name}";')
        lines.append('  rankdir=LR;')
        lines.append('  node [shape=box, style=rounded];')

        colors = {
            StepStatus.SUCCESS: "green",
            StepStatus.FAILED: "red",
            StepStatus.RUNNING: "orange",
            StepStatus.RETRYING: "yellow",
            StepStatus.SKIPPED: "gray",
            StepStatus.PENDING: "lightgray",
        }

        for i, step in enumerate(target.steps):
            color = colors.get(step.status, "lightgray")
            label = f"{step.name}\\n({step.duration_ms:.0f}ms)" if step.duration_ms else step.name
            if step.error:
                label += f"\\n⚠ {step.error[:30]}"
            if step.retry_count:
                label += f"\\n🔄 重试{step.retry_count}次"
            lines.append(f'  node{i} [label="{label}", color={color}];')
            if i > 0:
                lines.append(f'  node{i - 1} -> node{i};')

        lines.append('}')
        return '\n'.join(lines)

    def get_summary(self, run_id: str = None) -> Dict:
        """获取工作流摘要"""
        target = self.runs.get(run_id) if run_id else self._current_run
        if not target:
            return {"error": "无活动工作流"}

        total_ms = sum(s.duration_ms for s in target.steps)
        failed = [s.name for s in target.steps if s.status == StepStatus.FAILED]
        return {
            "name": target.name,
            "status": target.status.value,
            "total_steps": len(target.steps),
            "completed": sum(1 for s in target.steps if s.status == StepStatus.SUCCESS),
            "failed": failed,
            "retries": target.total_retries,
            "total_duration_ms": total_ms,
        }

    # ========== 内部辅助 ==========

    def _get_or_create_step(self, name: str) -> WorkflowStep:
        step = self._get_step(name)
        if not step:
            step = self.add_step(name)
        return step

    def _get_step(self, name: str) -> Optional[WorkflowStep]:
        if not self._current_run:
            return None
        for s in reversed(self._current_run.steps):
            if s.name == name and s.status != StepStatus.SUCCESS:
                return s
        return None


# 全局实例
workflow_tracker = WorkflowTracker()
