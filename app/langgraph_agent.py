from typing import TypedDict, Annotated, List, Dict, Any, Literal
from langgraph.graph import StateGraph, END
# langgraph 0.3.x 兼容两种导入路径
try:
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:
    from langgraph.checkpoint.memory import InMemorySaver as MemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
import json
import re
import concurrent.futures
from datetime import datetime
from app.config import config
from app.tools import get_weather, calculator, get_time, search_knowledge_base, query_database, move_robot, get_robot_status, check_obstacle, check_distance
from app.logger import logger
from app.llm_client import llm_client

from app.models import (
    AgentState
)

# ========== 工具映射 ==========

TOOL_FUNCTIONS = {
    "get_weather": get_weather,
    "calculator": calculator,
    "get_time": get_time,
    "search_knowledge_base": search_knowledge_base,
    "query_database": query_database,
    "move_robot": move_robot,
    "get_robot_status": get_robot_status,
    "check_obstacle": check_obstacle,
    "check_distance": check_distance,
}

def execute_tool(tool_name: str, tool_args: Dict) -> str:
    """执行工具"""
    if tool_name in TOOL_FUNCTIONS:
        try:
            result = TOOL_FUNCTIONS[tool_name](**tool_args)
            return result
        except Exception as e:
            return json.dumps({"error": str(e)})
    return json.dumps({"error": f"未知工具: {tool_name}"})


# ========== 复合指令拆解（确定性） ==========

def _parse_task_steps(query: str) -> Dict[str, List[str]]:
    """
    解析复合指令中的顺序移动任务（确定性拆解），支持多机器人各自的序列：
    "agv_1 先去 B 然后送 D / agv_2去B然后到A"
    → {"agv_1": ["B", "D"], "agv_2": ["B", "A"]}

    按分隔符（/ 、 ； ； ， ,）切段，每段累积一台机器人的区域序列；
    只有区域数 ≥2 的机器人才加入拆解，其余指令保持 LLM 自由调度。
    """
    acc: Dict[str, List[str]] = {}
    last_robot = None
    for seg in re.split(r'[/；;，,]\s*', query):
        robots = re.findall(r'agv_\d+', seg, re.IGNORECASE)
        robot = robots[0] if robots else last_robot
        if robot is None:
            continue
        zones = re.findall(r'(?:去|到|送|往|前往|移至|→|->)\s*([ABCD])', seg)
        if zones:
            acc.setdefault(robot, []).extend(z.upper() for z in zones)
        last_robot = robot
    return {r: zs for r, zs in acc.items() if len(zs) >= 2}

# ========== 节点函数 ==========
def think_node(state: AgentState) -> AgentState:
    """
    思考节点：LLM 决定下一步行动（使用原生 function calling）
    多轮循环：工具执行结果会反馈回本节点，由 LLM 决定是否继续调用工具
    """
    logger.info(f"🧠 思考节点 - 迭代: {state.get('iteration', 0)}")

    # 迭代上限保护，防止工具调用死循环
    max_iterations = state.get("max_iterations", 8)
    if state.get("iteration", 0) >= max_iterations:
        state["final_answer"] = "已达到最大工具调用轮数，任务可能未全部完成，请检查小车状态。"
        state["current_step"] = "end"
        return state

    # 复合指令任务序列：程序确定性驱动，并行执行每台机器人的当前步骤（不经过 LLM 决策）
    task_steps = state.get("task_steps", {})
    task_progress = state.get("task_progress", {})
    pending = []
    for rid, steps in task_steps.items():
        idx = task_progress.get(rid, 0)
        if idx < len(steps):
            pending.append((rid, steps[idx]))
    if pending:
        state["tool_calls"] = [
            {"tool_name": "move_robot", "tool_args": {"robot_id": rid, "zone": zone}}
            for rid, zone in pending
        ]
        state["current_step"] = "execute_tool"
        desc = ", ".join(f"{rid}→{zone}" for rid, zone in pending)
        logger.info(f"  任务序列：并行执行 {desc}")
        state["iteration"] = state.get("iteration", 0) + 1
        return state

    messages = state.get("messages", [])
    
    # 构建包含历史记录的完整消息列表
    llm_messages = [
        {"role": "system", "content": "你是一个智能助手，控制着仓库中的AGV小车。\n\n重要规则：\n- 用户说\"移动\"\"去\"\"到\"某个地方 → 必须调用 move_robot\n- 用户询问\"在哪\"\"位置\" → 调用 get_robot_status\n- 批量调度：用户要求移动多台小车（如\"把 agv_1 和 agv_2 都移到 C 区\"）时，必须为每台小车调用一次 move_robot，可以一次返回多个工具调用，也可以分多轮调用，直到所有小车移动完成\n- 完成所有移动后，基于工具结果总结回答，不要只移动第一台就结束\n- 不要自作主张查询状态，按用户指令行事\n- 复合指令（如\"去A取货→送D区\"）：按顺序逐步执行每一步移动，上一步返回 status=arrived 后再执行下一步，不要反复重复同一步\n- 禁止重复调用：若 move_robot 返回 status=arrived 或 error，说明该步已完成/被拒绝，不要再次调用相同的移动命令；error 时用自然语言向用户说明拒绝原因（例如“目标点与货架冲突，无法移动”），禁止把工具返回的 JSON 原文作为回答输出\n\n可用工具：\n- move_robot: 移动AGV小车（robot_id必填，zone指定A/B/C/D，或x,y指定坐标）。返回 status=moving 表示正在移动，status=arrived 表示已到达\n- get_robot_status: 查询小车当前位置\n- check_obstacle: 检测前方障碍物\n- check_distance: 计算小车到目标点的距离\n- get_weather: 获取天气\n- calculator: 计算\n- get_time: 时间\n- search_knowledge_base: 搜索知识库"}
    ]
    # 添加最近10条历史消息（交替的 user/assistant 对话）
    for msg in messages[-10:]:
        llm_messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    # 复合指令任务序列已全部执行完：提示 LLM 基于工具结果总结
    all_done = bool(task_steps) and all(
        task_progress.get(rid, 0) >= len(steps)
        for rid, steps in task_steps.items()
    )
    if all_done:
        llm_messages.append({
            "role": "system",
            "content": "任务序列已全部执行完毕，请基于工具返回结果总结回答用户，不要重复调用工具。"
        })
    
    # 使用原生 function calling API（不是 JSON 解析）
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的天气信息",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "城市名称"}},
                    "required": ["city"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "进行数学计算",
                "parameters": {
                    "type": "object",
                    "properties": {"expression": {"type": "string", "description": "数学表达式"}},
                    "required": ["expression"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "获取当前系统时间",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": "搜索知识库中的文档内容，获取与用户问题相关的文档片段",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "move_robot",
                "description": "移动仓库中的AGV小车到指定区域或坐标。区域可选A/B/C/D，也可以传x,y坐标",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "robot_id": {"type": "string", "description": "小车编号，如 agv_1"},
                        "x": {"type": "number", "description": "目标X坐标"},
                        "y": {"type": "number", "description": "目标Y坐标"},
                        "zone": {"type": "string", "description": "目标区域 A/B/C/D（与坐标二选一）"}
                    },
                    "required": ["robot_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_robot_status",
                "description": "查询AGV小车的当前位置、所在区域和朝向",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "robot_id": {"type": "string", "description": "小车编号，不传则返回所有小车"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_obstacle",
                "description": "检测AGV小车前方是否有障碍物（激光雷达模拟）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "robot_id": {"type": "string", "description": "小车编号"},
                        "direction": {"type": "string", "description": "检测方向 forward/left/right/back，默认forward"}
                    },
                    "required": ["robot_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_distance",
                "description": "计算AGV小车到目标点的直线距离（传感器）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "robot_id": {"type": "string", "description": "小车编号"},
                        "target_x": {"type": "number", "description": "目标点X坐标"},
                        "target_y": {"type": "number", "description": "目标点Y坐标"}
                    },
                    "required": ["robot_id", "target_x", "target_y"]
                }
            }
        }
    ]
    
    try:
        # 使用原生 tools API 调用 LLM（带 timeout）
        _LLM_TIMEOUT = getattr(config, 'LLM_TIMEOUT', 60.0)
        response = llm_client.client.chat.completions.create(
            model=llm_client.model,
            messages=llm_messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.3,
            timeout=_LLM_TIMEOUT
        )
        
        message = response.choices[0].message
        
        # 检查是否调用了工具
        if message.tool_calls:
            # 收集本轮所有工具调用（LLM 可能一次请求多个工具，如批量移动多台小车）
            tool_calls = []
            for tool_call in message.tool_calls:
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}
                tool_calls.append({
                    "tool_name": tool_call.function.name,
                    "tool_args": tool_args
                })
                logger.info(f"  LLM 决定调用工具: {tool_call.function.name}({tool_args})")
            
            state["tool_calls"] = tool_calls
            state["current_step"] = "execute_tool"
        else:
            # 无需工具，直接返回 LLM 的回答
            answer = message.content or "无法处理该请求"
            state["final_answer"] = answer
            state["current_step"] = "end"
            
    except Exception as e:
        logger.error(f"思考节点失败: {e}")
        state["final_answer"] = f"思考过程出错: {str(e)}"
        state["current_step"] = "end"
    
    state["iteration"] = state.get("iteration", 0) + 1
    return state


def execute_tool_node(state: AgentState) -> AgentState:
    """
    执行工具节点：并行执行多个工具调用（批量移动多台小车时同时出发，避免串行等待叠加）
    """
    logger.info(f"🔧 执行工具节点")
    
    tool_calls = state.get("tool_calls", [])
    results = []
    
    def _run_and_log(tool_call):
        tool_name = tool_call.get("tool_name")
        tool_args = tool_call.get("tool_args", {})
        logger.info(f"   调用工具: {tool_name}, 参数: {tool_args}")
        return tool_name, execute_tool(tool_name, tool_args)

    def _format_result_message(tool_name: str, result: str) -> str:
        """工具结果消息格式化：error 转自然语言描述，避免 LLM 原样复述 JSON"""
        try:
            rj = json.loads(result)
            if isinstance(rj, dict) and "error" in rj:
                return f"调用工具 {tool_name} 失败：{rj['error']}"
        except Exception:
            pass
        return f"调用工具 {tool_name}，得到结果：{result}"
    
    if len(tool_calls) > 1:
        # 多工具并行执行（如 agv_1 + agv_2 同时移动）
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
            futures = [(tc, pool.submit(_run_and_log, tc)) for tc in tool_calls]
            for tc, fut in futures:
                try:
                    tool_name, result = fut.result(timeout=90)
                except Exception as e:
                    tool_name, result = "unknown", json.dumps({"error": str(e)})
                results.append({"tool_name": tool_name, "tool_args": tc.get("tool_args", {}), "result": result})
                # 将工具结果添加到消息历史
                state["messages"].append({
                    "role": "assistant",
                    "content": _format_result_message(tool_name, result)
                })
    else:
        for tool_call in tool_calls:
            tool_name, result = _run_and_log(tool_call)
            results.append({"tool_name": tool_name, "tool_args": tool_call.get("tool_args", {}), "result": result})
            # 将工具结果添加到消息历史
            state["messages"].append({
                "role": "assistant",
                "content": _format_result_message(tool_name, result)
            })
    
    # 复合指令任务序列推进：仅当工具参数与该机器人当前步骤匹配且到达时推进；
    # 若该步被拒绝（error，如防穿模），该机器人序列终止，交由 LLM 总结说明
    task_steps = state.get("task_steps", {})
    task_progress = dict(state.get("task_progress", {}))
    for r in results:
        if r.get("tool_name") != "move_robot":
            continue
        args = r.get("tool_args", {})
        rid = args.get("robot_id", "")
        if rid not in task_steps:
            continue
        steps = task_steps[rid]
        idx = task_progress.get(rid, 0)
        if idx >= len(steps):
            continue
        try:
            rj = json.loads(r["result"])
        except Exception:
            continue
        if not isinstance(rj, dict):
            continue
        if "error" in rj:
            logger.warning(f"  任务序列 {rid} 第 {idx + 1} 步被拒绝: {rj['error']}，该车序列终止")
            task_progress[rid] = len(steps)
            continue
        if rj.get("status") == "arrived" and args.get("zone") == steps[idx]:
            task_progress[rid] = idx + 1
            logger.info(f"  任务序列 {rid} 第 {idx + 1}/{len(steps)} 步完成 ({steps[idx]})")
    state["task_progress"] = task_progress

    state["tool_results"] = results
    state["current_step"] = "think"   # 回到 think 循环：LLM 基于工具结果决定是否继续（支持批量调度）
    state["tool_calls"] = []
    
    return state


def should_continue(state: AgentState) -> Literal["execute_tool", "end"]:
    """决定下一步"""
    current_step = state.get("current_step", "think")
    
    if current_step == "execute_tool":
        return "execute_tool"
    else:
        return "end"


# ========== 构建 Graph ==========

def create_agent_graph():
    """创建 Agent Graph"""
    
    # 定义图
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("think", think_node)
    workflow.add_node("execute_tool", execute_tool_node)
    
    # 设置入口
    workflow.set_entry_point("think")
    
    # 添加边
    workflow.add_conditional_edges(
        "think",
        should_continue,
        {
            "execute_tool": "execute_tool",
            "end": END
        }
    )
    
    # 工具执行后回到 think 循环：LLM 看到结果后决定是否继续调用工具，
    # 直到所有小车移动完成（支持"把 agv_1 和 agv_2 都移到 C 区"批量调度）
    workflow.add_edge("execute_tool", "think")
    
    # 编译
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    
    return app


# ========== Agent 封装 ==========

class LangGraphAgent:
    """LangGraph Agent 封装"""
    
    def __init__(self):
        self.graph = create_agent_graph()
        self.thread_id = None
    
    def run(self, query: str, thread_id: str = None, verbose: bool = True) -> dict:
        """
        运行 Agent
        
        Args:
            query: 用户输入
            thread_id: 会话ID（用于记忆）
            verbose: 是否打印详细日志
        
        Returns:
            {"answer": str, "steps": list, "used_tool": bool}
        """
        if thread_id:
            self.thread_id = thread_id
        
        config = {"configurable": {"thread_id": self.thread_id or "default"}}
        
        # 初始状态
        initial_state = {
            "messages": [{"role": "user", "content": query}],
            "current_step": "think",
            "tool_calls": [],
            "tool_results": [],
            "final_answer": "",
            "iteration": 0,
            "max_iterations": 8,
            "task_steps": _parse_task_steps(query),
            "task_progress": {},
        }
        
        if verbose:
            logger.info(f"🤖 Agent 开始处理: {query[:50]}...")
        
        # 收集执行步骤
        steps = []
        used_tool = False
        final_state = None
        
        for output in self.graph.stream(initial_state, config=config):
            if verbose:
                for node_name, node_state in output.items():
                    logger.info(f"  执行节点: {node_name}")
                    steps.append(node_name)
                    if node_state.get("final_answer"):
                        logger.info(f"  最终答案: {node_state['final_answer'][:100]}...")
                    if node_state.get("tool_results"):
                        used_tool = True
            final_state = output
        
        # 获取最终答案
        answer = "处理失败"
        if final_state:
            for node_state in final_state.values():
                if isinstance(node_state, dict) and node_state.get("final_answer"):
                    answer = node_state["final_answer"]
        
        return {
            "answer": answer,
            "steps": steps,
            "used_tool": used_tool
        }
    
    def stream(self, query: str, thread_id: str = None):
        """流式执行（生成器）"""
        if thread_id:
            self.thread_id = thread_id
        
        config = {"configurable": {"thread_id": self.thread_id or "default"}}
        
        initial_state = {
            "messages": [{"role": "user", "content": query}],
            "current_step": "think",
            "tool_calls": [],
            "tool_results": [],
            "final_answer": "",
            "iteration": 0,
            "max_iterations": 8,
            "task_steps": _parse_task_steps(query),
            "task_progress": {},
        }
        
        for output in self.graph.stream(initial_state, config=config):
            yield output


# 全局实例
langgraph_agent = LangGraphAgent()