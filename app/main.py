from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from typing import Optional
import tempfile
import os
import uuid
from datetime import datetime

from app.models import ChatRequest, ChatResponse, UploadResponse, SearchRequest, SearchResponse
from app.llm_client import llm_client
from app.knowledge_base import knowledge_base
from app.rag_chain import rag_chain
from app.logger import logger
from app.task_manager import task_manager, process_pdf_background
from app.rag_chain_v2 import rag_v2
from app.evaluator import evaluator
from app.cache_manager import cache_manager

app = FastAPI(title="AI知识库系统", version="1.0.0", description="基于RAG的智能知识库")

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 会话存储（生产环境用Redis）
sessions = {}

# 挂载静态文件目录
web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.exists(web_dir):
    app.mount("/web", StaticFiles(directory=web_dir), name="web")
    
    @app.get("/")
    async def serve_frontend():
        return FileResponse(os.path.join(web_dir, "index.html"))

# ========== 基础接口 ==========
@app.get("/")
def root():
    return {"message": "AI知识库系统运行中", "status": "ok", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/stats")
def get_stats():
    """获取系统统计"""
    kb_stats = knowledge_base.get_stats()
    return {
        "knowledge_base": kb_stats,
        "sessions": len(sessions),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """查询任务状态"""
    from app.task_manager import task_manager
    
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    
    return {
        "task_id": task["id"],
        "status": task["status"],
        "type": task["type"],
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "result": task.get("result"),
        "error": task.get("error")
    }

@app.get("/tasks")
async def get_all_tasks(limit: int = 50):
    """获取所有任务列表"""
    from app.task_manager import task_manager
    
    tasks = task_manager.get_tasks(limit)
    return {
        "tasks": tasks,
        "count": len(tasks),
        "total": len(task_manager.tasks)
    }

# ========== 聊天接口 ==========
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """智能对话（支持工具调用和知识库）"""
    try:
        # 获取或创建会话
        session_id = request.session_id or str(uuid.uuid4())
        
        # 构建消息
        messages = [{"role": "user", "content": request.message}]
        
        # 使用工具调用
        reply = llm_client.chat_with_tools(messages, request.temperature)
        
        # 存储会话历史
        if session_id not in sessions:
            sessions[session_id] = []
        sessions[session_id].append({"user": request.message, "assistant": reply})
        
        return ChatResponse(
            reply=reply,
            session_id=session_id,
            sources=None
        )
    except Exception as e:
        logger.error(f"Chat失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ========== RAG知识库接口 ==========
@app.get("/rag/ask")
async def rag_ask(question: str, use_search: bool = True, top_k: int = 3):
    """RAG问答（带知识库检索）"""
    try:
        result = rag_chain.ask(question, use_search, top_k)
        return result
    except Exception as e:
        logger.error(f"RAG问答失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rag/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None
):
    """上传PDF到知识库（异步处理）"""
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="只支持PDF文件")
    
    # 先创建 task_id
    task_id = str(uuid.uuid4())
    
    # 保存临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name
    
    # 创建任务记录（使用同一个 task_id）
    task_manager.create_task("upload_pdf", {
        "filename": file.filename, 
        "path": tmp_path,
        "task_id": task_id  # 保存到参数中
    })
    
    # 添加后台任务（传递同一个 task_id）
    background_tasks.add_task(process_pdf_background, task_id, tmp_path, file.filename)
    
    # 立即返回
    return UploadResponse(
        status="processing",
        message="文件已接收，正在后台处理",
        file=file.filename,
        chunks=0,
        task_id=task_id  # 返回正确的 task_id
    )

@app.get("/rag/search")
async def search_knowledge(q: str, top_k: int = 3, source: Optional[str] = None):
    """搜索知识库"""
    try:
        results = knowledge_base.search(q, top_k, source)
        return {
            "query": q,
            "results": results,
            "total": len(results),
            "timestamp": str(datetime.now())
        }
    except Exception as e:
        logger.error(f"搜索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/rag/v2/search")
async def search_v2_knowledge(q: str, top_k: int = 3, source: Optional[str] = None):
    """基础混合检索"""
    try:
        result = rag_v2.retrieve_base_hybrid(q, top_k)
        return result
    except Exception as e:
        logger.error(f"基础混合检索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/rag/clear")
async def clear_knowledge_base():
    """清空知识库"""
    try:
        knowledge_base.clear()
        return {"status": "success", "message": "知识库已清空"}
    except Exception as e:
        logger.error(f"清空失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/rag/v2/ask")
async def rag_v2_ask(question: str, use_hyde: bool = True, top_k: int = 3):
    """增强版RAG问答"""
    try:
        if use_hyde:
            result = rag_v2.ask_with_hyde(question, top_k)
        else:
            result = rag_v2.retrieve_with_quality(question, top_k)
        return result
    except Exception as e:
        logger.error(f"V2 RAG失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/rag/compare")
async def compare_methods(question: str):
    """对比不同检索方法"""
    try:
        result = rag_v2.compare_methods(question)
        return result
    except Exception as e:
        logger.error(f"对比失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/rag/evaluate")
async def run_evaluation():
    """运行评估（基于知识库实际文档）"""
    from app.vector_store import vector_store
    
    # 从知识库获取实际存在的文档source
    try:
        all_docs = vector_store.collection.get(include=["metadatas"])
        sources = set()
        if all_docs and all_docs.get("metadatas"):
            for meta in all_docs["metadatas"]:
                src = meta.get("source", "")
                if src:
                    sources.add(src)
        
        sources_list = list(sources)
        if not sources_list:
            return {"error": "知识库为空，无法评估", "hit_rate": 0, "mrr": 0, "ndcg@3": 0, "ndcg@5": 0}
        
        # 构建测试用例：查询与实际文档来源匹配
        test_queries = [
            ("什么是Docker？", sources_list[:2]),
            ("Docker容器有什么特点", sources_list[:2]),
            ("容器化技术的优势", sources_list[:2]),
        ]
    except Exception as e:
        logger.error(f"评估准备失败: {str(e)}")
        return {"error": str(e), "hit_rate": 0, "mrr": 0, "ndcg@3": 0, "ndcg@5": 0}
    
    metrics = evaluator.evaluate_retrieval(test_queries)
    evaluator.log_metrics(metrics)
    return metrics

@app.delete("/cache/clear")
async def clear_cache():
    """清空缓存"""
    cache_manager.clear()
    return {"status": "success", "message": "缓存已清空"}        

# ========== 会话管理 ==========
@app.get("/sessions")
def list_sessions():
    """列出所有会话"""
    return {"sessions": list(sessions.keys()), "count": len(sessions)}

@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    """获取会话历史"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "history": sessions[session_id]}

# ========== 全局异常处理 ==========
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"全局异常: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误", "message": str(exc) if os.getenv("ENV") == "development" else "请联系管理员"}
    )