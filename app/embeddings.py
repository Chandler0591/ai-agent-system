from sentence_transformers import SentenceTransformer
from app.logger import logger
import os

class EmbeddingModel:
    """向量化模型"""
    
    def __init__(self):
        model_path = os.getenv(
            "EMBEDDING_MODEL_PATH",
            "./models/BAAI/bge-small-zh-v1.5"
        )

        self.model = SentenceTransformer(model_path)
        self.dimension = 512
        
        logger.info(f"向量模型加载成功: {model_path}")
        
    def encode(self, text: str) -> list:
        """将文本转换为向量"""
        vector = self.model.encode(text)
        return vector.tolist()
    
    def encode_batch(self, texts: list) -> list:
        """批量转换"""
        vectors = self.model.encode(texts)
        return [v.tolist() for v in vectors]

# 全局实例
embedding_model = EmbeddingModel()