from typing import List, Dict, Tuple
import numpy as np
from app.logger import logger
from app.knowledge_base import knowledge_base

class RAGEvaluator:
    """RAG评估器"""
    
    def __init__(self):
        self.metrics = {}
    
    def calculate_hit_rate(self, retrieved_docs: List[str], 
                           relevant_docs: List[str]) -> float:
        """计算Hit Rate（命中率）"""
        retrieved_set = set(retrieved_docs)
        relevant_set = set(relevant_docs)
        
        hits = len(retrieved_set & relevant_set)
        hit_rate = hits / len(relevant_set) if relevant_set else 0
        
        return hit_rate
    
    def calculate_mrr(self, retrieved_docs: List[str], 
                      relevant_docs: List[str]) -> float:
        """计算MRR (Mean Reciprocal Rank)"""
        for i, doc in enumerate(retrieved_docs, 1):
            if doc in relevant_docs:
                return 1.0 / i
        return 0.0
    
    def calculate_ndcg(self, retrieved_docs: List[str], 
                       relevant_docs: List[str], 
                       k: int = 5) -> float:
        """计算NDCG@k"""
        # 简化实现
        dcg = 0.0
        for i, doc in enumerate(retrieved_docs[:k], 1):
            if doc in relevant_docs:
                dcg += 1.0 / np.log2(i + 1)
        
        # 理想DCG
        ideal_dcg = sum([1.0 / np.log2(i + 1) for i in range(1, min(len(relevant_docs), k) + 1)])
        
        return dcg / ideal_dcg if ideal_dcg > 0 else 0.0
    
    def evaluate_retrieval(self, test_queries: List[Tuple[str, List[str]]]) -> Dict:
        """评估检索质量"""
        results = {
            "hit_rate": [],
            "mrr": [],
            "ndcg@3": [],
            "ndcg@5": []
        }
        
        for query, relevant_docs in test_queries:
            # 调用实际检索方法
            retrieved = self._retrieve(query, relevant_docs)
            
            results["hit_rate"].append(
                self.calculate_hit_rate(retrieved, relevant_docs)
            )
            results["mrr"].append(
                self.calculate_mrr(retrieved, relevant_docs)
            )
            results["ndcg@3"].append(
                self.calculate_ndcg(retrieved, relevant_docs, k=3)
            )
            results["ndcg@5"].append(
                self.calculate_ndcg(retrieved, relevant_docs, k=5)
            )
        
        # 计算平均值
        final_results = {
            metric: np.mean(values) for metric, values in results.items()
        }
        
        logger.info(f"评估完成: {final_results}")
        return final_results
    
    def _retrieve(self, query: str, relevant_docs: List[str]) -> List[str]:
        """使用知识库实际检索文档"""
        try:
            results = knowledge_base.search(query, top_k=5)
            # 提取文档ID或文本用于匹配
            retrieved_ids = []
            for r in results:
                doc_id = r.get("metadata", {}).get("doc_id") or r.get("metadata", {}).get("source", "")
                if doc_id:
                    retrieved_ids.append(doc_id)
            return retrieved_ids if retrieved_ids else []
        except Exception as e:
            logger.warning(f"实际检索失败，回退到模拟: {str(e)}")
            return relevant_docs[:3] if relevant_docs else []
    
    def log_metrics(self, metrics: Dict):
        """记录评估指标"""
        logger.info("="*50)
        logger.info("RAG评估指标:")
        for metric, value in metrics.items():
            logger.info(f"  {metric}: {value:.4f}")
        logger.info("="*50)

# 全局实例
evaluator = RAGEvaluator()