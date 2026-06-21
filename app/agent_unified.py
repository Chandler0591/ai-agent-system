"""
统一 Agent 入口 - LangGraph 决策 + RAG V2 检索
"""

from typing import List, Dict, Optional, Generator
from app.llm_client import llm_client
from app.knowledge_base import knowledge_base
from app.rag_chain_v2 import rag_v2
from app.tools import set_tenant
from app.langgraph_agent import langgraph_agent
from app.session_manager import session_manager
from app.workflow_tracker import workflow_tracker
from app.logger import logger


class UnifiedAgent:
    """
    统一 Agent
    - 知识库有相关内容 → HyDE 增强 RAG（混合检索+重排）
    - 无相关知识 → LangGraph Agent（工具调用/直接对话）
    """
    
    def __init__(self):
        self.mode = "auto"  # auto / rag / agent
    
    def set_mode(self, mode: str):
        """切换 Agent 模式"""
        valid_modes = ["auto", "rag", "agent"]
        if mode in valid_modes:
            self.mode = mode
            logger.info(f"Agent 模式切换为: {mode}")
        else:
            logger.warning(f"无效的Agent模式: {mode}，可用: {valid_modes}")

    def _should_use_rag(self, query: str, tenant_id: str = "default") -> bool:
        """判断是否应该使用知识库检索"""
        kb_results = knowledge_base.search(query, top_k=2, tenant_id=tenant_id)
        if not kb_results:
            return False
        best = kb_results[0]
        # 必须中相关以上才进 RAG，避免"低相关"碰瓷
        return best.get("score", 0) >= 0.65 and best.get("relevance") in ("高相关", "中相关")
    
    def run(self, query: str, session_id: str = None, stream: bool = False, tenant_id: str = "default"):
        """运行 Agent（带租户隔离）"""
        set_tenant(tenant_id)  # 工具调用时使用
        if stream:
            return self._run_stream(query, session_id, tenant_id)
        else:
            return self._run_sync(query, session_id, tenant_id)
    
    def _run_sync(self, query: str, session_id: str = None, tenant_id: str = "default") -> Dict:
        """同步执行"""
        wf_id = f"agent-{session_id[:8] if session_id else 'anon'}"
        workflow_tracker.start_workflow("UnifiedAgent", run_id=wf_id)
        
        try:
            result = None
            
            # 先尝试知识库检索
            if self._should_use_rag(query, tenant_id):
                # Step 1: 知识库搜索
                workflow_tracker.start_step("knowledge_search")
                workflow_tracker.finish_step("knowledge_search", success=True)
                
                # Step 2: HyDE 增强检索
                workflow_tracker.start_step("hyde_enhance")
                rag_result = rag_v2.ask_with_hyde(query, tenant_id=tenant_id)
                workflow_tracker.finish_step("hyde_enhance", success=True)
                
                answer = rag_result.get("answer", "")
                # 只有拿到有效回答才采纳 RAG 结果
                if answer and "没有找到" not in answer and "暂无相关" not in answer:
                    workflow_tracker.start_step("llm_generate")
                    workflow_tracker.finish_step("llm_generate", success=True)
                    result = {
                        "query": query,
                        "answer": answer,
                        "intent": "rag",
                        "used_tool": False,
                        "used_rag": True,
                        "session_id": session_id,
                        "steps": ["knowledge_search", "hyde_enhance", "rerank", "llm_generate"],
                        "sources": rag_result.get("sources", []),
                        "from_cache": rag_result.get("from_cache", False)
                    }
            
            # RAG 无有效结果 → fallback 到 Agent
            if result is None:
                workflow_tracker.start_step("langgraph_agent")
                lang_result = langgraph_agent.run(query, thread_id=session_id, verbose=True)
                workflow_tracker.finish_step("langgraph_agent", success=True)
                result = {
                    "query": query,
                    "answer": lang_result["answer"],
                    "intent": "tool" if lang_result.get("used_tool") else "chat",
                    "used_tool": lang_result.get("used_tool", False),
                    "used_rag": False,
                    "session_id": session_id,
                    "steps": lang_result.get("steps", []),
                    "sources": lang_result.get("sources", [])
                }
            
            # 保存到会话历史
            if session_id:
                session_manager.add_message(session_id, "user", query)
                session_manager.add_message(session_id, "assistant", result["answer"])
            
            workflow_tracker.finish_workflow(success=True)
            return result
            
        except Exception as e:
            logger.error(f"Agent 执行失败: {e}")
            workflow_tracker.finish_workflow(success=False, error=str(e))
            return {
                "query": query,
                "answer": f"处理失败: {str(e)}",
                "intent": "error",
                "used_tool": False,
                "used_rag": False,
                "session_id": session_id,
                "steps": [f"error: {str(e)}"]
            }
    
    def _run_stream(self, query: str, session_id: str = None, tenant_id: str = "default") -> Generator:
        """流式执行 —— SSE 逐 token 输出"""
        wf_id = f"agent-stream-{session_id[:8] if session_id else 'anon'}"
        workflow_tracker.start_workflow("UnifiedAgentStream", run_id=wf_id)
        
        try:
            # 先尝试 RAG，有结果就走 RAG，否则 fallback 到 Agent
            if self._should_use_rag(query, tenant_id):
                workflow_tracker.start_step("knowledge_search")
                workflow_tracker.finish_step("knowledge_search", success=True)
                
                workflow_tracker.start_step("hyde_enhance")
                # 使用 rag_v2 的 HyDE 增强检索（与同步路径保持一致）
                rag_result = rag_v2.ask_with_hyde(query, tenant_id=tenant_id)
                workflow_tracker.finish_step("hyde_enhance", success=True)
                answer = rag_result.get("answer", "")
                sources = rag_result.get("sources", [])

                if answer and "没有找到" not in answer and "暂无相关" not in answer:
                    # === RAG 路径：有有效回答，流式输出 ===
                    workflow_tracker.start_step("llm_stream")
                    yield {"type": "intent", "data": "rag"}
                    yield {"type": "info", "data": "检索知识库..."}
                    yield {"type": "info", "data": "生成回答中..."}

                    # 将 HyDE 生成的回答拆分为 token 流式输出
                    import re
                    tokens = re.split(r'(\s+)', answer)
                    for token in tokens:
                        if token:
                            yield {"type": "token", "data": token}

                    if sources:
                        formatted_sources = []
                        for s in sources:
                            formatted_sources.append({
                                "text": s.get("text", "")[:200],
                                "source": s.get("metadata", {}).get("source", "未知"),
                                "relevance": s.get("relevance", "中相关"),
                                "score": s.get("score", 0)
                            })
                        yield {"type": "sources", "data": formatted_sources}

                    if session_id:
                        session_manager.add_message(session_id, "user", query)
                        session_manager.add_message(session_id, "assistant", answer)

                    workflow_tracker.finish_step("llm_stream", success=True)
                    workflow_tracker.finish_workflow(success=True)
                    yield {"type": "done", "data": "complete"}
                    return
                # RAG 无有效回答 → fallback 到 Agent
            
            # === Agent 路径：工具调用/直接对话 ===
            workflow_tracker.start_step("agent_direct")
            yield {"type": "intent", "data": "agent"}
            
            messages = [{
                "role": "system",
                "content": "你是一个智能助手，可以调用工具来帮助用户。当需要查询天气、计算、获取时间、搜索知识库时，请调用对应工具。"
            }]
            # 加载会话历史，让 LLM 拥有多轮对话记忆
            if session_id:
                history = session_manager.get_context_messages(session_id)
                for h in history:
                    messages.append({"role": h["role"], "content": h["content"]})
            messages.append({"role": "user", "content": query})
            
            full_answer = ""
            for token in llm_client.chat_with_tools_stream(messages, temperature=0.5):
                full_answer += token
                yield {"type": "token", "data": token}
            
            # 收集 Agent 路径中的知识库来源（仅中相关及以上，避免无关文档污染）
            kb_results = knowledge_base.search(query, top_k=3, tenant_id=tenant_id)
            relevant_results = [s for s in kb_results if s.get("score", 0) >= 0.5]
            if relevant_results:
                formatted_sources = []
                for s in relevant_results:
                    formatted_sources.append({
                        "text": s.get("text", "")[:200],
                        "source": s.get("metadata", {}).get("source", "未知"),
                        "relevance": s.get("relevance", "中相关"),
                        "score": s.get("score", 0)
                    })
                if formatted_sources:
                    yield {"type": "sources", "data": formatted_sources}
            
            if session_id:
                session_manager.add_message(session_id, "user", query)
                session_manager.add_message(session_id, "assistant", full_answer)
            
            workflow_tracker.finish_step("agent_direct", success=True)
            workflow_tracker.finish_workflow(success=True)
            yield {"type": "done", "data": "complete"}
            
        except Exception as e:
            logger.error(f"流式执行失败: {e}")
            workflow_tracker.finish_workflow(success=False, error=str(e))
            yield {"type": "error", "data": str(e)}
    
    def get_status(self) -> Dict:
        """获取 Agent 状态"""
        return {
            "tools": ["get_weather", "calculator", "get_time", "search_knowledge_base"],
            "rag_engine": "HyDE + 混合检索 + CrossEncoder重排 + MMR",
            "agent_engine": "LangGraph (think → execute_tool → reflect)",
            "session_enabled": True
        }


# 全局实例
unified_agent = UnifiedAgent()