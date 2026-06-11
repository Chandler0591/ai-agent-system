import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
    ENV = os.getenv("ENV", "development")
    
    # Redis配置
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

    # 文件上传配置
    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

config = Config()
