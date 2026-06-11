from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime

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