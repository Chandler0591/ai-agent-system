from typing import List, Dict
from app.llm_client import llm_client
from app.embeddings import embedding_model
from app.logger import logger

class HyDE:
    """HyDE (Hypothetical Document Embeddings) 假设文档嵌入"""
    
    def __init__(self):
        self.hyde_prompt = """基于以下问题，生成一段假设性的回答。回答要详细、准确，就像从文档中摘录的一样。

问题：{question}

假设性回答："""
    
    def generate_hypothetical_doc(self, question: str) -> str:
        """生成假设文档"""
        prompt = self.hyde_prompt.format(question=question)
        messages = [{"role": "user", "content": prompt}]
        
        try:
            hypothetical_doc = llm_client.chat(messages, temperature=0.5)
            logger.info(f"HyDE生成完成: {len(hypothetical_doc)}字符")
            return hypothetical_doc
        except Exception as e:
            logger.error(f"HyDE生成失败: {str(e)}")
            return question  # 失败时返回原问题
    
    def expand_query(self, question: str, num_docs: int = 3) -> List[str]:
        """查询扩展：生成多个假设文档"""
        # 生成多个不同的假设文档
        expanded_queries = [question]
        
        # 添加假设文档作为查询
        hypo_doc = self.generate_hypothetical_doc(question)
        expanded_queries.append(hypo_doc)
        
        # 生成简化版
        simple_prompt = f"用一句话概括以下问题的核心要点：{question}"
        simple_version = llm_client.chat([{"role": "user", "content": simple_prompt}], temperature=0.3)
        expanded_queries.append(simple_version)
        
        return expanded_queries[:num_docs]
    
    def hybrid_query_embedding(self, question: str) -> List[float]:
        """混合查询嵌入：原问题 + 假设文档的加权平均"""
        expanded_queries = self.expand_query(question)
        
        # 获取所有向量的加权平均
        embeddings = [embedding_model.encode(q) for q in expanded_queries]
        
        # 权重：原问题权重最高
        weights = [0.5, 0.3, 0.2]
        weighted_embedding = [0] * len(embeddings[0])
        
        for i, emb in enumerate(embeddings):
            weight = weights[i] if i < len(weights) else 0.1
            weighted_embedding = [
                weighted_embedding[j] + weight * emb[j] 
                for j in range(len(emb))
            ]
        
        logger.info(f"HyDE查询扩展完成: {len(expanded_queries)}个查询")
        return weighted_embedding

# 全局实例
hyde = HyDE()