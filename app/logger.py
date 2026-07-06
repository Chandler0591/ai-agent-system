import logging
import sys
import os


def setup_logger(name="ai_agent", level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(handler)
    
    # 添加敏感信息过滤器
    logger.addFilter(SensitiveDataFilter())
    
    return logger


class SensitiveDataFilter(logging.Filter):
    """过滤日志中的敏感信息（API Key、密码等）"""
    _patterns = None

    @classmethod
    def _get_patterns(cls):
        if cls._patterns is not None:
            return cls._patterns
        patterns = []
        # 从环境变量收集敏感值
        for key in ["LLM_API_KEY", "DEEPSEEK_API_KEY", "SECRET_KEY",
                     "VISION_API_KEY", "DATABASE_URL", "REDIS_URL"]:
            val = os.getenv(key, "")
            if val and len(val) > 8:
                patterns.append(val)
        cls._patterns = patterns
        return cls._patterns

    def filter(self, record):
        msg = str(record.msg)
        for secret in self._get_patterns():
            msg = msg.replace(secret, "***FILTERED***")
        record.msg = msg
        return True


logger = setup_logger()
