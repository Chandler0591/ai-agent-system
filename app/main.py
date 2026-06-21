from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, APIRouter, Depends, Header, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from typing import Optional
import tempfile
import os
import uuid
import json
from datetime import datetime

from app.models import ChatRequest, ChatResponse, UploadResponse, AgentRunRequest, AgentRunResponse
from app.llm_client import llm_client
from app.knowledge_base import knowledge_base
from app.vector_store import vector_store
from app.rag_chain import rag_chain
from app.session_manager import session_manager
from app.agent_unified import unified_agent
from app.task_manager import task_manager, process_pdf_background
from app.logger import logger
from app.config import config

# 数据库初始化（单例，PG 不可用时自动降级 MemoryDB）
try:
    from app.database import database_manager
except Exception as e:
    logger.warning(f"数据库模块加载失败: {e}")

# ========== 企业级中间件 ==========
from app.middleware.auth import create_access_token, verify_token, get_tenant_id, get_current_user
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.tenant import TenantMiddleware
from app.monitoring import metrics_endpoint, track_documents

# ========== 第2阶段新模块（可选导入，无依赖时降级） ==========
try:
    from app.tasks import process_pdf_async
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False

try:
    from app.multi_agent import supervisor_agent
    MULTI_AGENT_AVAILABLE = True
except ImportError:
    MULTI_AGENT_AVAILABLE = False

app = FastAPI(
    title="AI Agent 企业版",
    version="2.0.0",
    description="企业级 RAG + Agent 智能系统：JWT认证、限流、多租户、异步任务、多Agent编排、Prometheus监控"
)

api_router = APIRouter(prefix="/api")

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 租户隔离中间件
app.add_middleware(TenantMiddleware)

# API 限流中间件
app.add_middleware(RateLimitMiddleware)

# ========== 租户提取（供 Depends 注入） ==========
def _get_tenant_id(authorization: Optional[str] = Header(None)) -> str:
    """从 JWT 提取 tenant_id，未登录时返回 default"""
    try:
        from app.middleware.auth import decode_token
        if authorization and authorization.startswith("Bearer "):
            payload = decode_token(authorization[7:])
            return payload.get("tenant_id", "default")
    except Exception:
        pass
    return "default"

# ========== 基础接口 ==========
@api_router.get("")
def api_root():
    return {
        "message": "AI Agent 系统运行中",
        "version": "2.0.0",
        "endpoints": [
            "/api/health", "/api/live", "/api/ready", "/api/stats",
            "/api/chat", "/api/agent/run", "/api/agent/stream",
            "/api/rag/upload", "/api/rag/ask", "/api/rag/search",
            "/api/session/create", "/api/session/{id}",
            "/api/task/{id}", "/api/tasks"
        ]
    }

@api_router.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@api_router.get("/live")
def live():
    """Kubernetes liveness probe — 进程是否存活"""
    return {"status": "alive"}

@api_router.get("/ready")
def ready():
    """Kubernetes readiness probe — 依赖是否就绪"""
    checks = {}
    
    # 检查 ChromaDB
    try:
        kb_stats = knowledge_base.get_stats()
        checks["chromadb"] = {"ok": True, "docs": kb_stats.get("document_count", 0)}
    except Exception as e:
        checks["chromadb"] = {"ok": False, "error": str(e)}
    
    # 检查 Redis
    try:
        from app.cache_manager import cache_manager
        if cache_manager.use_redis:
            cache_manager.redis_client.ping()
        checks["redis"] = {"ok": cache_manager.use_redis}
    except Exception:
        checks["redis"] = {"ok": False}
    
    # 检查 LLM 连通性（仅当非就绪时做一次诊断，避免每次探针调用 LLM）
    llm_ok = config.LLM_API_KEY is not None
    checks["llm"] = {"ok": llm_ok, "note": "API Key 已配置" if llm_ok else "未配置 LLM_API_KEY"}
    
    all_ok = all(v.get("ok", False) for v in checks.values())
    return {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    }

@api_router.get("/stats")
def get_stats():
    kb_stats = knowledge_base.get_stats()
    return {
        "knowledge_base": kb_stats,
        "sessions": len(session_manager.list_sessions()),
        "timestamp": datetime.now().isoformat()
    }


# ========== 统一 Agent 接口 ==========
@api_router.post("/agent/run", response_model=AgentRunResponse)
async def agent_run(request: AgentRunRequest, tenant_id: str = Depends(_get_tenant_id)):
    """运行统一 Agent"""
    try:
        session_id = request.session_id or str(uuid.uuid4())
        
        # 执行 Agent
        result = unified_agent.run(request.message, session_id, tenant_id=tenant_id)
        
        return AgentRunResponse(
            reply=result["answer"],
            session_id=result["session_id"],
            intent=result["intent"],
            used_tool=result.get("used_tool", False),
            used_rag=result.get("used_rag", False),
            steps=result.get("steps", []),
            sources=result.get("sources")
        )
    except Exception as e:
        logger.error(f"Agent 运行失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/agent/stream")
async def agent_stream(request: AgentRunRequest, tenant_id: str = Depends(_get_tenant_id)):
    """流式运行 Agent"""
    session_id = request.session_id or str(uuid.uuid4())
    
    async def generate():
        try:
            for chunk in unified_agent.run(request.message, session_id, stream=True, tenant_id=tenant_id):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")

@api_router.get("/agent/status")
async def agent_status():
    """获取 Agent 状态"""
    return unified_agent.get_status()

@api_router.get("/agent/health")
async def agent_health():
    """Agent 健康检查（别名）"""
    status = unified_agent.get_status()
    return {"status": "healthy", "tools": status["tools"]}

@api_router.post("/agent/mode")
async def agent_mode(mode: str):
    """切换 Agent 模式"""
    unified_agent.set_mode(mode)
    return {"status": "success", "mode": mode}


# ========== 简单对话接口==========
@api_router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """简单对话"""
    try:
        session_id = request.session_id or str(uuid.uuid4())
        messages = [{"role": "user", "content": request.message}]
        reply = llm_client.chat(messages, request.temperature)
        
        session_manager.add_message(session_id, "user", request.message)
        session_manager.add_message(session_id, "assistant", reply)
        
        return ChatResponse(reply=reply, session_id=session_id, sources=None)
    except Exception as e:
        logger.error(f"Chat失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== RAG 知识库接口 ==========


@api_router.post("/rag/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    tenant_id: str = Depends(_get_tenant_id),
    force: bool = False,  # ?force=true 强制重新上传
):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="只支持PDF文件")
    
    # 检查重复（force=true 时跳过，允许覆盖）
    if not force and vector_store.source_exists(file.filename, tenant_id=tenant_id):
        raise HTTPException(status_code=409, detail=f"'{file.filename}' 已存在于知识库中，传 ?force=true 强制覆盖")
    
    task_id = str(uuid.uuid4())
    
    import os as _os
    _tmp_dir = "/app/tmp"
    _os.makedirs(_tmp_dir, exist_ok=True)
    tmp_path = _os.path.join(_tmp_dir, f"upload_{task_id}.pdf")
    content = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(content)
    
    task_manager.create_task("upload_pdf", {"filename": file.filename, "path": tmp_path, "task_id": task_id, "tenant_id": tenant_id, "force": force})
    
    # Celery 可用时走异步队列，否则降级到 BackgroundTasks
    if CELERY_AVAILABLE:
        process_pdf_async.delay(task_id, tmp_path, file.filename, tenant_id, force)
        logger.info(f"PDF 已派发到 Celery 队列: {file.filename} (tenant={tenant_id}, force={force})")
    else:
        background_tasks.add_task(process_pdf_background, task_id, tmp_path, file.filename, tenant_id, force)
    
    return UploadResponse(
        status="processing",
        message="文件已接收，正在后台处理",
        file=file.filename,
        chunks=0,
        task_id=task_id
    )

@api_router.post("/rag/ask")
async def rag_ask(question: str, use_search: bool = True):
    result = rag_chain.ask(question, use_search)
    return result

@api_router.get("/rag/search")
async def search_knowledge(q: str, top_k: int = 3, tenant_id: str = Depends(_get_tenant_id)):
    results = knowledge_base.search(q, top_k, tenant_id=tenant_id)
    return {"query": q, "results": results, "total": len(results)}

@api_router.delete("/rag/clear")
async def clear_knowledge_base():
    knowledge_base.clear()
    return {"status": "success", "message": "知识库已清空"}

@api_router.get("/kb/documents")
async def list_kb_documents(tenant_id: str = Depends(_get_tenant_id)):
    """列出当前租户的知识库文档"""
    sources = knowledge_base.list_sources(tenant_id=tenant_id)
    return {"documents": sources, "total": len(sources)}

@api_router.delete("/kb/documents/{source_name:path}")
async def delete_kb_document(source_name: str, tenant_id: str = Depends(_get_tenant_id)):
    """删除当前租户下指定文档"""
    result = knowledge_base.delete_source(source_name, tenant_id=tenant_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="文档不存在")
    return result


# ========== 会话管理接口 ==========

# ========== 认证接口（W9） ==========
@api_router.get("/tenants")
async def list_tenants():
    """获取可用租户列表"""
    try:
        from app.database import database_manager
        if database_manager.available:
            rows = database_manager.list_tenants()
            if rows:
                return {"tenants": rows}
    except Exception:
        pass
    # 开发环境 / PG 不可用时返回默认列表
    return {"tenants": [
        {"tenant_id": "default", "name": "默认租户(共享)"},
        {"tenant_id": "demo1", "name": "演示租户1"},
        {"tenant_id": "demo2", "name": "演示租户2"},
    ]}


@api_router.post("/token")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    tenant_id: Optional[str] = Form(None)
):
    """获取 JWT token（需选择租户）"""
    from app.middleware.auth import create_access_token
    
    if not tenant_id:
        tenant_id = "default"
    
    # 生产环境：验证用户密码 + 租户权限
    if config.ENV != "development":
        from app.database import database_manager
        if not database_manager.verify_password(form_data.username, form_data.password):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        # 验证用户是否属于该租户
        user_tenants = database_manager.get_user_tenants(form_data.username)
        allowed = [t["tenant_id"] for t in user_tenants]
        if tenant_id not in allowed:
            raise HTTPException(status_code=403, detail=f"无权访问租户 '{tenant_id}'")
    
    token = create_access_token(
        username=form_data.username,
        tenant_id=tenant_id,
    )
    return {"access_token": token, "token_type": "bearer", "tenant_id": tenant_id}


@api_router.get("/me")
async def get_me(username: str = Depends(get_current_user), tenant: str = Depends(get_tenant_id)):
    """获取当前用户信息（需 JWT）"""
    return {"username": username, "tenant_id": tenant}


@api_router.post("/revoke")
async def revoke(authorization: Optional[str] = Header(None)):
    """登出：将 token 加入黑名单"""
    from app.middleware.auth import revoke_token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=400, detail="缺少 Authorization header")
    token = authorization[7:]
    revoke_token(token)
    return {"message": "已登出，token 已废止"}


# ========== 多 Agent 编排接口（W11） ==========
if MULTI_AGENT_AVAILABLE:
    @api_router.post("/multi-agent/run")
    async def multi_agent_run(task: str, auto_approve: bool = True):
        """运行 Supervisor 多 Agent 协作"""
        result = supervisor_agent.run(task, auto_approve=auto_approve)
        return {
            "final_answer": result.final_answer,
            "subtasks": [
                {"role": s.role.value, "description": s.description, "status": s.status.value}
                for s in result.subtasks
            ],
            "needs_human_review": result.needs_human_review,
        }


# ========== 监控接口（W12） ==========
@api_router.get("/metrics")
async def prometheus_metrics():
    """Prometheus 指标端点"""
    return await metrics_endpoint()


# ========== RAG 评估接口（W10） ==========
@api_router.post("/rag/evaluate")
async def evaluate_rag(query: str, answer: str):
    """RAGAS 质量评估"""
    try:
        from app.advanced_rag import ragas_evaluator
        contexts = [r["text"][:500] for r in knowledge_base.search(query, top_k=3)]
        result = ragas_evaluator.evaluate_all(query, answer, contexts)
        return result
    except Exception as e:
        return {"error": str(e)}


# ========== 会话管理接口 ==========
@api_router.post("/session/create")
async def create_session():
    session_id = session_manager.create_session()
    return {"session_id": session_id}

@api_router.get("/session/{session_id}")
async def get_session(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session

@api_router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    if session_manager.delete_session(session_id):
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="会话不存在")

@api_router.get("/sessions")
async def list_sessions():
    sessions = session_manager.list_sessions()
    return {"sessions": sessions, "count": len(sessions)}


# ========== 任务管理接口 ==========
@api_router.get("/task/{task_id}")
async def get_task(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task

@api_router.get("/tasks")
async def get_all_tasks(limit: int = 50):
    tasks = task_manager.get_tasks(limit)
    return {"tasks": tasks, "count": len(tasks)}


# ========== 全局异常处理 ==========
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """正确返回 HTTPException 的状态码（不被全局 500 吞掉）"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"全局异常: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误",
            "message": str(exc) if os.getenv("ENV") == "development" else "请联系管理员"
        }
    )


# ========== 前端 ==========
web_dir = os.path.join(os.path.dirname(__file__), "..", "web")

# 注册 API 路由
app.include_router(api_router)

@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(web_dir, "index.html"))

if os.path.exists(web_dir):
    app.mount("/web", StaticFiles(directory=web_dir), name="web")