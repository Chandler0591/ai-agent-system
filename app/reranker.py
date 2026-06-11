import numpy as np
import os
from typing import List, Dict, Tuple
from sklearn.metrics.pairwise import cosine_similarity
from app.embeddings import embedding_model
from app.logger import logger
from sentence_transformers import CrossEncoder


class Reranker:
    """重排序：优先使用CrossEncoder，回退到二次向量相似度"""
    
    def __init__(self):
        self.cross_encoder = None
        self.use_cross_encoder = False
        self._load_cross_encoder()
        
    def _load_cross_encoder(self):
        model_path = os.getenv(
            "RERANKER_MODEL_PATH",
            "./models/BAAI/bge-reranker-base"
        )
        
        self.cross_encoder = CrossEncoder(
            model_path,
            max_length=512
        )
        self.use_cross_encoder = True
        logger.info(f"CrossEncoder模型加载成功: {model_path}")
        
    def rerank_with_cross_encoder(self, query: str, documents: List[Dict]) -> List[Dict]:
        """使用CrossEncoder重排序"""
        if not documents:
            return []
        
        if self.use_cross_encoder:
            return self._rerank_cross_encoder(query, documents)
        else:
            return self._rerank_bi_encoder(query, documents)
    
    def _rerank_cross_encoder(self, query: str, documents: List[Dict]) -> List[Dict]:
        """CrossEncoder重排序（精确版）"""
        # 构建 query-document 对
        pairs = [[query, doc["text"]] for doc in documents]
        
        # CrossEncoder打分
        scores = self.cross_encoder.predict(pairs)
        
        # 归一化分数到 [0, 1]
        min_score = float(np.min(scores))
        max_score = float(np.max(scores))
        score_range = max_score - min_score if max_score != min_score else 1.0
        
        for i, doc in enumerate(documents):
            raw_score = float(scores[i])
            normalized_score = (raw_score - min_score) / score_range
            doc["rerank_score"] = normalized_score
            doc["original_score"] = doc.get("score", 0)
            # 加权融合：80% cross-encoder + 20% original
            doc["final_score"] = 0.8 * normalized_score + 0.2 * doc.get("score", 0)
        
        sorted_docs = sorted(documents, key=lambda x: x["final_score"], reverse=True)
        logger.info(f"CrossEncoder重排序完成: {len(sorted_docs)}个文档")
        return sorted_docs
    
    def _rerank_bi_encoder(self, query: str, documents: List[Dict]) -> List[Dict]:
        """二次向量编码重排序（回退方案）"""
        query_vector = embedding_model.encode(query)
        
        # 批量编码文档向量
        doc_texts = [doc["text"] for doc in documents]
        doc_vectors = embedding_model.encode_batch(doc_texts)
        
        for i, doc in enumerate(documents):
            similarity = float(cosine_similarity(
                [query_vector], [doc_vectors[i]]
            )[0][0])
            doc["rerank_score"] = similarity
            doc["original_score"] = doc.get("score", 0)
            # 加权融合：70% rerank + 30% original
            doc["final_score"] = 0.7 * similarity + 0.3 * doc.get("score", 0)
        
        sorted_docs = sorted(documents, key=lambda x: x["final_score"], reverse=True)
        logger.info(f"BiEncoder重排序完成: {len(sorted_docs)}个文档")
        return sorted_docs
    
    def mmr_selection(self, query: str, documents: List[Dict], 
                      lambda_param: float = 0.7, top_k: int = 3) -> List[Dict]:
        """MMR (Maximum Marginal Relevance) 多样性选择"""
        if not documents:
            return []
        
        query_vector = embedding_model.encode(query)
        doc_texts = [doc["text"] for doc in documents]
        doc_vectors = embedding_model.encode_batch(doc_texts)
        
        selected = []  # 存储已选文档的原始索引
        remaining = list(range(len(documents)))  # 剩余候选的原始索引
        
        while len(selected) < top_k and remaining:
            best_doc_idx = -1
            best_mmr = float('-inf')
            
            for doc_idx in remaining:
                # 相关性得分
                relevance = float(cosine_similarity(
                    [query_vector], [doc_vectors[doc_idx]]
                )[0][0])
                
                # 多样性得分（与已选文档的最大相似度）
                if selected:
                    diversity = max([float(cosine_similarity(
                        [doc_vectors[doc_idx]], [doc_vectors[s]]
                    )[0][0]) for s in selected])
                else:
                    diversity = 0
                
                # MMR公式
                mmr = lambda_param * relevance - (1 - lambda_param) * diversity
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_doc_idx = doc_idx
            
            # 将最优文档从remaining移到selected
            selected.append(best_doc_idx)
            remaining.remove(best_doc_idx)
        
        return [documents[i] for i in selected]

# 全局实例
reranker = Reranker()