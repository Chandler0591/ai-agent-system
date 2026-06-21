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
from datetime import datetime
from app.config import config
from app.tools import get_weather, calculator, get_time, search_knowledge_base, query_database
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

# ========== 节点函数 ==========
def think_node(state: AgentState) -> AgentState:
    """
    思考节点：LLM 决定下一步行动（使用原生 function calling）
    """
    logger.info(f"🧠 思考节点 - 迭代: {state.get('iteration', 0)}")
    
    messages = state.get("messages", [])
    
    # 构建包含历史记录的完整消息列表
    llm_messages = [
        {"role": "system", "content": "你是一个智能助手，可以调用工具来帮助用户。当需要查询天气、计算、或获取时间时，请调用对应工具。如果不需要工具，直接回复即可。"}
    ]
    # 添加最近10条历史消息（交替的 user/assistant 对话）
    for msg in messages[-10:]:
        llm_messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    
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
            tool_call = message.tool_calls[0]
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            
            logger.info(f"  LLM 决定调用工具: {tool_name}({tool_args})")
            
            state["tool_calls"] = [{
                "tool_name": tool_name,
                "tool_args": tool_args
            }]
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
    执行工具节点：执行工具调用
    """
    logger.info(f"🔧 执行工具节点")
    
    tool_calls = state.get("tool_calls", [])
    results = []
    
    for tool_call in tool_calls:
        tool_name = tool_call.get("tool_name")
        tool_args = tool_call.get("tool_args", {})
        
        logger.info(f"   调用工具: {tool_name}, 参数: {tool_args}")
        
        result = execute_tool(tool_name, tool_args)
        results.append({
            "tool_name": tool_name,
            "result": result
        })
        
        # 将工具结果添加到消息历史
        state["messages"].append({
            "role": "assistant",
            "content": f"调用工具 {tool_name}，得到结果：{result}"
        })
    
    state["tool_results"] = results
    state["current_step"] = "reflect"
    state["tool_calls"] = []
    
    return state


def reflect_node(state: AgentState) -> AgentState:
    """
    反思节点：根据工具结果生成最终回答
    """
    logger.info(f"💭 反思节点")
    
    tool_results = state.get("tool_results", [])
    
    if not tool_results:
        state["current_step"] = "end"
        return state
    
    # 构建包含工具结果的 prompt
    context = "\n".join([
        f"工具 {r['tool_name']} 返回: {r['result']}"
        for r in tool_results
    ])
    
    prompt = f"""根据以下工具执行结果，回答用户的问题。

工具结果：
{context}

请给出简洁、准确的回答。"""
    
    from app.llm_client import llm_client
    
    try:
        response = llm_client.chat([{"role": "user", "content": prompt}], temperature=0.5)
        state["final_answer"] = response
    except Exception as e:
        state["final_answer"] = f"生成回答时出错: {str(e)}"
    
    state["current_step"] = "end"
    return state


def should_continue(state: AgentState) -> Literal["execute_tool", "reflect", "end"]:
    """决定下一步"""
    current_step = state.get("current_step", "think")
    
    if current_step == "execute_tool":
        return "execute_tool"
    elif current_step == "reflect":
        return "reflect"
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
    workflow.add_node("reflect", reflect_node)
    
    # 设置入口
    workflow.set_entry_point("think")
    
    # 添加边
    workflow.add_conditional_edges(
        "think",
        should_continue,
        {
            "execute_tool": "execute_tool",
            "reflect": "reflect",
            "end": END
        }
    )
    
    workflow.add_edge("execute_tool", "reflect")
    workflow.add_edge("reflect", END)
    
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
            "max_iterations": 5
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
            "max_iterations": 5
        }
        
        for output in self.graph.stream(initial_state, config=config):
            yield output


# 全局实例
langgraph_agent = LangGraphAgent()