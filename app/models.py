from pydantic import BaseModel
from typing import Optional, List, Dict, Any, TypedDict, Annotated
from datetime import datetime
import operator

class ChatRequest(BaseModel):
    message: str
    temperature: float = 0.7
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    reply: str
    session_id: str
    sources: Optional[List[Dict]] = None

class UploadResponse(BaseModel):
    status: str
    message: str
    file: str
    chunks: int
    task_id: str

class SearchRequest(BaseModel):
    query: str
    top_k: int = 3

class SearchResponse(BaseModel):
    query: str
    results: List[Dict]
    timestamp: datetime

class SessionCreateRequest(BaseModel):
    session_id: Optional[str] = None

class SessionResponse(BaseModel):
    session_id: str
    created_at: str
    message_count: int

class ConversationRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    temperature: float = 0.7
    use_context: bool = True  # 是否使用历史上下文

class ConversationResponse(BaseModel):
    reply: str
    session_id: str
    history_length: int
    from_cache: bool = False

class AgentRunRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    mode: Optional[str] = "auto"

class AgentRunResponse(BaseModel):
    reply: str
    session_id: str
    intent: str
    used_tool: bool
    used_rag: bool
    steps: Optional[List[str]] = None
    sources: Optional[list] = None

class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[List[Dict[str, Any]], operator.add]  # 对话历史（追加模式）
    current_step: str               # 当前步骤
    tool_calls: List[Dict]          # 待执行的工具调用
    tool_results: List[Dict]        # 工具执行结果
    final_answer: str               # 最终答案
    iteration: int                  # 迭代次数
    max_iterations: int             # 最大迭代次数