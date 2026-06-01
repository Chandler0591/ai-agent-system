import logging
import sys

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
    
    return logger

logger = setup_logger()
