"""
Prometheus 监控指标 + 健康上报
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
import time
from functools import wraps
from app.logger import logger

# ========== 指标定义 ==========
api_requests_total = Counter(
    "api_requests_total", "API 请求总数",
    ["method", "endpoint", "status"]
)

api_request_duration = Histogram(
    "api_request_duration_seconds", "API 请求耗时",
    ["method", "endpoint"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

rag_queries_total = Counter(
    "rag_queries_total", "RAG 检索次数",
    ["relevance"]  # high/medium/low
)

agent_tool_calls_total = Counter(
    "agent_tool_calls_total", "Agent 工具调用次数",
    ["tool_name"]
)

active_sessions = Gauge(
    "active_sessions", "活跃会话数"
)

documents_uploaded = Counter(
    "documents_uploaded_total", "上传文档总数"
)

llm_tokens_used = Counter(
    "llm_tokens_used_total", "LLM Token 消耗"
)

task_queue_size = Gauge(
    "task_queue_size", "待处理任务数"
)


# ========== 装饰器 ==========
def track_api(method: str = "GET", endpoint: str = None):
    """自动记录 API 请求指标
    
    Usage:
        @app.get("/path")
        @track_api(method="GET", endpoint="my_handler")
        async def my_handler(request: Request):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            ep = endpoint or func.__name__
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                api_requests_total.labels(
                    method=method, endpoint=ep, status="200"
                ).inc()
                return result
            except Exception as e:
                api_requests_total.labels(
                    method=method, endpoint=ep, status="500"
                ).inc()
                raise
            finally:
                api_request_duration.labels(
                    method=method, endpoint=ep
                ).observe(time.time() - start)
        return wrapper
    return decorator


def track_rag_query(relevance: str):
    """记录 RAG 检索"""
    rag_queries_total.labels(relevance=relevance).inc()


def track_tool_call(tool_name: str):
    """记录 Agent 工具调用"""
    agent_tool_calls_total.labels(tool_name=tool_name).inc()


def track_documents(count: int):
    """记录上传文档数"""
    documents_uploaded.inc(count)


# ========== 暴露指标端点 ==========
async def metrics_endpoint():
    """返回 Prometheus 格式指标"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
