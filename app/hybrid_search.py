import numpy as np
import re
from typing import List, Dict, Tuple
from rank_bm25 import BM25Okapi
from app.embeddings import embedding_model
from app.logger import logger

class HybridSearch:
    """混合检索：向量检索 + BM25关键词检索"""
    
    def __init__(self):
        self.bm25 = None
        self.corpus = []  # 存储所有文档文本
        self.doc_ids = []  # 存储文档ID
        self.doc_vectors = []  # 缓存文档向量
        self._index_built = False  # 索引是否已构建
        self._doc_count = 0  # 上次构建索引时的文档数
        
    def build_bm25_index(self, documents: List[Dict]):
        """构建BM25索引（增量判断，避免重复构建）"""
        if not documents:
            return
        
        # 如果文档数量没变且索引已存在，跳过重建
        if self._index_built and len(documents) == self._doc_count:
            return
        
        self.corpus = [doc["text"] for doc in documents]
        self.doc_ids = [doc["id"] for doc in documents]
        
        # 分词
        tokenized_corpus = [self._tokenize(text) for text in self.corpus]
        self.bm25 = BM25Okapi(tokenized_corpus)
        
        # 批量编码文档向量（一次性计算，缓存复用）
        self.doc_vectors = embedding_model.encode_batch(self.corpus)
        
        self._index_built = True
        self._doc_count = len(documents)
        logger.info(f"BM25索引构建完成: {len(self.corpus)}个文档")
    
    def _tokenize(self, text: str) -> List[str]:
        """中文分词：字级别 + 英文词级别"""
        tokens = []
        # 英文单词和数字保持完整
        english_and_numbers = re.findall(r'[a-zA-Z]+|[0-9]+', text)
        tokens.extend([w.lower() for w in english_and_numbers])
        
        # 中文按字分割（unigram + bigram）
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        tokens.extend(chinese_chars)  # unigram
        # 添加 bigram 提升词组匹配能力
        for i in range(len(chinese_chars) - 1):
            tokens.append(chinese_chars[i] + chinese_chars[i+1])
        
        return tokens
    
    def vector_search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """向量检索（使用缓存的文档向量）"""
        if not self.doc_vectors:
            return []
        
        query_vector = np.array(embedding_model.encode(query))
        doc_vecs = np.array(self.doc_vectors)
        
        # 批量计算余弦相似度
        query_norm = np.linalg.norm(query_vector)
        doc_norms = np.linalg.norm(doc_vecs, axis=1)
        
        # 避免除零
        valid_mask = doc_norms > 0
        similarities = np.zeros(len(doc_vecs))
        similarities[valid_mask] = np.dot(doc_vecs[valid_mask], query_vector) / (
            doc_norms[valid_mask] * query_norm
        )
        
        # 取top_k
        indices = np.argsort(similarities)[::-1][:top_k]
        return [(int(i), float(similarities[i])) for i in indices]
    
    def bm25_search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """BM25检索"""
        if not self.bm25:
            return []
        
        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        
        # 取top_k
        indices = np.argsort(scores)[::-1][:top_k]
        return [(int(i), scores[i]) for i in indices]
    
    def rrf_fusion(self, vector_results: List[Tuple[int, float]], 
                   bm25_results: List[Tuple[int, float]], 
                   k: int = 60) -> List[Tuple[int, float]]:
        """RRF (Reciprocal Rank Fusion) 融合算法"""
        scores = {}
        
        # 向量检索结果
        for rank, (idx, score) in enumerate(vector_results):
            scores[idx] = scores.get(idx, 0) + 1 / (k + rank + 1)
        
        # BM25检索结果
        for rank, (idx, score) in enumerate(bm25_results):
            scores[idx] = scores.get(idx, 0) + 1 / (k + rank + 1)
        
        # 按融合分数排序
        sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(idx, score) for idx, score in sorted_results]
    
    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """混合检索"""
        # 1. 向量检索
        vector_results = self.vector_search(query, top_k=10)
        
        # 2. BM25检索
        bm25_results = self.bm25_search(query, top_k=10)
        
        # 3. RRF融合
        fused_results = self.rrf_fusion(vector_results, bm25_results)
        
        # 4. 返回结果
        results = []
        for idx, score in fused_results[:top_k]:
            results.append({
                "id": self.doc_ids[idx],
                "text": self.corpus[idx],
                "score": score,
                "method": "hybrid"
            })
        
        logger.info(f"混合检索完成: {len(results)}个结果")
        return results

# 全局实例
hybrid_search = HybridSearch()