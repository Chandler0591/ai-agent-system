from app.knowledge_base import knowledge_base
from app.llm_client import llm_client
from app.logger import logger
from typing import List, Dict, Optional

class RAGChain:
    """RAG问答链 - 支持多轮对话和来源引用"""
    
    def __init__(self):
        self.system_prompt = """你是一个专业的知识库助手。请根据提供的上下文信息回答用户问题。

## 核心原则
1. **准确性优先**：只根据上下文回答，不要编造信息
2. **诚实透明**：如果上下文没有相关信息，明确说"知识库中没有找到相关信息"
3. **引用来源**：回答时引用具体的来源文档
4. **简洁清晰**：答案要简洁、准确、易读

## 回答格式
- 如果有相关信息：先给出答案，然后在末尾标注 [来源X]
- 如果部分相关：说明已知信息，指出不确定的部分
- 如果不相关：直接说没有找到相关信息

## 上下文
{context}

## 用户问题
{question}

## 你的回答
"""
    
    def ask(self, question: str, use_search: bool = True, top_k: int = 3) -> Dict:
        """使用RAG回答问题，返回答案和来源"""
        if not use_search:
            # 不使用检索，直接LLM
            messages = [{"role": "user", "content": question}]
            answer = llm_client.chat(messages)
            return {"answer": answer, "sources": [], "has_context": False}
        
        # 1. 检索相关知识
        context = knowledge_base.get_context(question, top_k)
        sources = knowledge_base.search(question, top_k)
        
        if not context:
            return {
                "answer": "知识库中暂无相关信息，请先上传相关文档。",
                "sources": [],
                "has_context": False
            }
        
        # 2. 构建Prompt
        prompt = self.system_prompt.format(
            context=context,
            question=question
        )
        
        # 3. LLM生成答案
        messages = [{"role": "user", "content": prompt}]
        answer = llm_client.chat(messages)
        
        # 4. 格式化来源
        formatted_sources = []
        for s in sources:
            formatted_sources.append({
                "text": s["text"][:200] + "...",
                "source": s["metadata"].get("source", "未知"),
                "relevance": s["relevance"],
                "score": s["score"]
            })
        
        logger.info(f"RAG问答: {question[:50]}... -> {answer[:50]}...")
        
        return {
            "answer": answer,
            "sources": formatted_sources,
            "has_context": True
        }

# 全局实例
rag_chain = RAGChain()