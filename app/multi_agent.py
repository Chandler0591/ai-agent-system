"""
多 Agent 协作 —— Supervisor 编排模式 + Human-in-the-loop
架构:
    Supervisor（调度）
    ├── Researcher（检索专家）
    ├── Analyst（分析专家）  
    └── Executor（执行专家）
"""

import time
from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from enum import Enum
from app.llm_client import llm_client
from app.knowledge_base import knowledge_base
from app.workflow_tracker import workflow_tracker
from app.logger import logger


class AgentRole(Enum):
    SUPERVISOR = "supervisor"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    EXECUTOR = "executor"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"  # 等待人工审批
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SubTask:
    """子任务"""
    id: str
    role: AgentRole
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error: str = ""


@dataclass
class MultiAgentResult:
    """多 Agent 协作结果"""
    subtasks: List[SubTask] = field(default_factory=list)
    final_answer: str = ""
    needs_human_review: bool = False
    review_question: str = ""


# ==================== 子 Agent 定义 ====================

class ResearcherAgent:
    """检索专家 —— 负责知识库查询和 RAG"""

    SYSTEM_PROMPT = """你是一个检索专家。你擅长:
1. 从知识库中精确检索信息
2. 提取关键事实和数据
3. 判断检索结果的相关性和可信度

回答格式: 先给出检索结论，再列出关键发现。"""

    def execute(self, task: str, context: List[Dict] = None) -> str:
        results = knowledge_base.search(task, top_k=5)
        if not results:
            return "知识库中未找到相关信息。"

        ctx_text = "\n\n---\n\n".join(
            f"[来源: {r['metadata'].get('source', '未知')} | 相关度: {r.get('relevance', '未知')}]\n{r['text'][:500]}"
            for r in results
        )

        prompt = f"任务: {task}\n\n检索结果:\n{ctx_text}\n\n请基于以上信息给出结论:"
        return llm_client.chat([
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ], temperature=0.3)


class AnalystAgent:
    """分析专家 —— 负责数据分析和逻辑推理"""

    SYSTEM_PROMPT = """你是一个分析专家。你擅长:
1. 分析数据模式和趋势
2. 逻辑推理和因果分析
3. 对比优劣并给出建议

回答格式: 先给出分析结论，再列出推理过程。"""

    def execute(self, task: str, context: str = "") -> str:
        prompt = f"任务: {task}\n\n参考信息: {context}\n\n请分析并给出结论:"
        return llm_client.chat([
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ], temperature=0.3)


class ExecutorAgent:
    """执行专家 —— 负责生成代码、执行计划"""

    SYSTEM_PROMPT = """你是一个执行专家。你擅长:
1. 制定可执行的行动计划
2. 生成代码片段
3. 给出具体的操作步骤

回答格式: 先给出执行计划，再列出具体步骤。"""

    def execute(self, task: str, context: str = "") -> str:
        prompt = f"任务: {task}\n\n参考信息: {context}\n\n请给出执行计划:"
        return llm_client.chat([
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ], temperature=0.3)


# ==================== Supervisor 调度器 ====================

class SupervisorAgent:
    """
    Supervisor 模式 —— 分解复杂任务 → 分派子 Agent → 汇总结果
    """

    SUPERVISOR_PROMPT = """你是一个任务调度器。你需要:
1. 分析用户任务，拆解为子任务
2. 决定每个子任务由哪个专家执行
3. 汇总各专家结果，生成最终回答

可用专家:
- researcher: 检索知识库、查询信息
- analyst: 数据分析、逻辑推理、对比评估
- executor: 生成行动计划、代码、具体步骤

返回 JSON 格式:
{
  "subtasks": [
    {"role": "researcher|analyst|executor", "description": "子任务描述"}
  ],
  "needs_human_review": false,
  "review_question": ""
}

needs_human_review 标记是否需要人工审核（涉及删除/修改/敏感操作时设为 true）"""

    def __init__(self):
        self.researcher = ResearcherAgent()
        self.analyst = AnalystAgent()
        self.executor = ExecutorAgent()
        self._human_approval_callback = None

    def set_human_approval(self, callback):
        """设置人工审批回调"""
        self._human_approval_callback = callback

    def run(self, task: str, auto_approve: bool = True) -> MultiAgentResult:
        """
        运行 Supervisor 调度

        Args:
            task: 用户任务
            auto_approve: 是否自动批准（False 时需人工审批）

        Returns:
            MultiAgentResult
        """
        logger.info(f"[Supervisor] 开始处理任务: {task[:100]}")
        wf_id = f"multi-agent-{int(time.time())}"
        workflow_tracker.start_workflow("SupervisorMultiAgent", run_id=wf_id)

        # Step 1: 分解任务
        workflow_tracker.start_step("plan_task")
        plan = self._plan_task(task)
        workflow_tracker.finish_step("plan_task", success=True)
        subtask_defs = plan.get("subtasks", [])
        needs_human = plan.get("needs_human_review", False)
        review_question = plan.get("review_question", task)

        if not subtask_defs:
            # 简单任务，直接由 Supervisor 回答
            workflow_tracker.finish_workflow(success=True)
            return self._handle_simple_task(task)

        # Step 2: 执行子任务
        subtasks = []
        context = ""

        for i, st_def in enumerate(subtask_defs):
            role_str = st_def.get("role", "researcher")
            description = st_def.get("description", "")

            try:
                role = AgentRole(role_str)
            except ValueError:
                role = AgentRole.RESEARCHER

            step_name = f"subtask_{i}_{role.value}"
            workflow_tracker.start_step(step_name)

            sub = SubTask(
                id=f"subtask_{i}",
                role=role,
                description=description,
                status=TaskStatus.RUNNING
            )

            if role == AgentRole.RESEARCHER:
                sub.result = self.researcher.execute(description)
            elif role == AgentRole.ANALYST:
                sub.result = self.analyst.execute(description, context)
            elif role == AgentRole.EXECUTOR:
                sub.result = self.executor.execute(description, context)
            else:
                sub.result = self.researcher.execute(description)

            sub.status = TaskStatus.COMPLETED
            subtasks.append(sub)
            workflow_tracker.finish_step(step_name, success=True)
            context += f"\n[{role.value}] {sub.result}\n"

        # Step 3: 汇总子任务结果
        workflow_tracker.start_step("synthesize")
        final_answer = self._synthesize(task, subtasks)
        workflow_tracker.finish_step("synthesize", success=True)

        # Step 4: Human-in-the-loop
        if needs_human and not auto_approve:
            for sub in subtasks:
                sub.status = TaskStatus.WAITING_HUMAN
            workflow_tracker.finish_workflow(success=True)
            return MultiAgentResult(
                subtasks=subtasks,
                final_answer=final_answer,
                needs_human_review=True,
                review_question=review_question
            )

        workflow_tracker.finish_workflow(success=True)
        return MultiAgentResult(
            subtasks=subtasks,
            final_answer=final_answer
        )

    def _plan_task(self, task: str) -> Dict:
        """用 LLM 分解任务"""
        prompt = f"""{self.SUPERVISOR_PROMPT}

用户任务: {task}

请返回 JSON:"""
        try:
            import json
            response = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.2)
            return json.loads(response.strip())
        except Exception as e:
            logger.warning(f"任务分解失败: {e}")
            return {"subtasks": [], "needs_human_review": False}

    def _synthesize(self, task: str, subtasks: List[SubTask]) -> str:
        """汇总子 Agent 结果"""
        reports = "\n\n".join(
            f"### {sub.role.value}\n{sub.result}"
            for sub in subtasks if sub.status == TaskStatus.COMPLETED
        )
        prompt = f"""原始任务: {task}

专家报告:
{reports}

请基于以上专家报告，生成最终回答（使用纯文本，不要使用 HTML 标签）:"""
        answer = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.5)
        # 清理 LLM 偶尔输出的 HTML 标签
        return answer.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")

    def _handle_simple_task(self, task: str) -> MultiAgentResult:
        """简单任务直接回答"""
        answer = llm_client.chat([{"role": "user", "content": task}], temperature=0.5)
        return MultiAgentResult(
            subtasks=[],
            final_answer=answer
        )

    def approve_task(self, approved: bool, feedback: str = "") -> str:
        """人工审批后继续执行"""
        if approved:
            return f"已批准执行。{feedback}"
        return f"任务已驳回。原因: {feedback}"


# 全局实例
supervisor_agent = SupervisorAgent()
researcher = ResearcherAgent()
analyst = AnalystAgent()
executor_agent = ExecutorAgent()
