from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from pydantic import BaseModel
from app.llm_client import llm_client
from fastapi import Request
from fastapi.responses import JSONResponse
from app.logger import logger

class ChatRequest(BaseModel):
    message: str
    temperature: float = 0.7

class ChatResponse(BaseModel):
    reply: str

app = FastAPI(title="AI Agent System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "AI Agent System Running", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        messages = [
            {"role": "user", "content": request.message}
        ]
        reply = llm_client.chat(messages, request.temperature)
        return ChatResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局异常: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "message": str(exc)}
    )