import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """统一配置中心 —— 12-Factor App 原则"""

    # ========== LLM API ==========
    # 通用变量名（推荐），向后兼容旧 DEEPSEEK_* 命名
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
    LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

    # ========== 多模态视觉模型 ==========
    # 启用方式: VISION_ENABLED=true + 配置对应 provider 的 KEY/URL
    # 支持厂商: openai / qwen / zhipu / moonshot / ollama (本地) / deepseek(预留)
    VISION_ENABLED = os.getenv("VISION_ENABLED", "false").lower() == "true"
    VISION_PROVIDER = os.getenv("VISION_PROVIDER", "openai")
    VISION_MODEL_NAME = os.getenv("VISION_MODEL_NAME", "gpt-4o")
    VISION_API_KEY = os.getenv("VISION_API_KEY", LLM_API_KEY)
    VISION_BASE_URL = os.getenv("VISION_BASE_URL", "")

    # 各厂商预置 Base URL（VISION_BASE_URL 为空时自动选择）
    VISION_PROVIDER_URLS = {
        "openai":   "https://api.openai.com/v1",
        "qwen":     "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "zhipu":    "https://open.bigmodel.cn/api/paas/v4",
        "moonshot": "https://api.moonshot.cn/v1",
        "ollama":   "http://localhost:11434/v1",        # 本地 Ollama 容器
        "deepseek": "https://api.deepseek.com",          # 暂不支持视觉，预留
    }
    # 各厂商推荐的视觉模型
    VISION_PROVIDER_MODELS = {
        "openai":   "gpt-4o",
        "qwen":     "qwen-vl-max",
        "zhipu":    "glm-4v",
        "moonshot": "moonshot-v1-8k-vision-preview",
        "ollama":   "llava:13b",                         # 也可用 llama3.2-vision / minicpm-v / bakllava
        "deepseek": "deepseek-chat",
    }

    # ========== 数据库 ==========
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres123@localhost:5432/ai_agent")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

    # ========== 安全 ==========
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", "60"))          # 每分钟请求数
    API_RATE_WINDOW = int(os.getenv("API_RATE_WINDOW", "60"))        # 限流窗口（秒）

    # ========== 租户配额 ==========
    DEFAULT_DOCUMENT_QUOTA = int(os.getenv("DEFAULT_DOCUMENT_QUOTA", "1000"))
    DEFAULT_API_CALL_QUOTA = int(os.getenv("DEFAULT_API_CALL_QUOTA", "10000"))

    # ========== Celery ==========
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

    # ========== 文件上传 ==========
    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

    # ========== 模型路径 ==========
    EMBEDDING_MODEL_PATH = os.getenv("EMBEDDING_MODEL_PATH", "./models/BAAI/bge-small-zh-v1.5")
    RERANKER_MODEL_PATH = os.getenv("RERANKER_MODEL_PATH", "./models/BAAI/bge-reranker-base")

    # ========== 环境 ==========
    ENV = os.getenv("ENV", "development")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


config = Config()
