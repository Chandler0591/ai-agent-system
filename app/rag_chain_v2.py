from typing import List, Dict, Optional
from app.knowledge_base import knowledge_base
from app.llm_client import llm_client
from app.hybrid_search import hybrid_search
from app.reranker import reranker
from app.hyde import hyde
from app.cache_manager import cache_manager
from app.logger import logger
from app.vector_store import vector_store

class RAGChainV2:
    """增强版RAG链 - 包含多路召回、重排序、HyDE、缓存"""
    
    def __init__(self):
        self.system_prompt = """你是一个专业的知识库助手。请根据提供的上下文信息回答用户问题。

## 上下文信息
{context}

## 用户问题
{question}

## 回答要求
1. 只根据上下文回答，不要编造信息
2. 如果上下文没有相关信息，明确说"没有找到相关信息"
3. 回答要简洁准确，不要使用编号引用或标注来源

## 你的回答
"""
    def retrieve_base_hybrid(self, question: str, top_k: int = 5, tenant_id: str = "default") -> Dict:
        """基础混合检索：BM25+向量粗召回"""
        cached = cache_manager.get_search_results(question, top_k)
        if cached:
            logger.info("使用缓存的检索结果")
            return {
                "documents": cached,
                "from_cache": True
            }

        all_docs = self._get_all_documents(tenant_id=tenant_id)
        if not all_docs:
            return {"documents": [], "from_cache": False}
        logger.info(f"获取知识库文档完成: {len(all_docs)}个文档")

        # 3. 构建混合检索索引
        hybrid_search.build_bm25_index(all_docs)

        # 4. 混合检索（BM25 + 向量）
        hybrid_results = hybrid_search.hybrid_search(question, top_k=10)

        # 7. 缓存结果
        cache_manager.set_search_results(question, top_k, hybrid_results)
        logger.info(f"混合检索完成: {len(hybrid_results)}个文档")

        return {
            "documents": hybrid_results,
            "from_cache": False
        }
    def retrieve_with_quality(self, question: str, top_k: int = 5, tenant_id: str = "default") -> Dict:
        """高质量检索：多路召回 + 重排序"""
        
        cached = cache_manager.get_search_results(question, top_k)
        if cached:
            logger.info("使用缓存的检索结果")
            return {
                "documents": cached,
                "from_cache": True
            }
        
        all_docs = self._get_all_documents(tenant_id=tenant_id)
        if not all_docs:
            return {"documents": [], "from_cache": False}
        logger.info(f"获取知识库文档完成: {len(all_docs)}个文档")
        # 3. 构建混合检索索引
        hybrid_search.build_bm25_index(all_docs)
        
        # 4. 混合检索
        hybrid_results = hybrid_search.hybrid_search(question, top_k=10)
        
        # 5. 重排序
        reranked_results = reranker.rerank_with_cross_encoder(question, hybrid_results)
        
        # 6. MMR多样性选择
        diverse_results = reranker.mmr_selection(question, reranked_results, 
                                                  lambda_param=0.7, top_k=top_k)
        
        # 7. 缓存结果
        cache_manager.set_search_results(question, top_k, diverse_results)
        
        logger.info(f"高质量检索完成: {len(diverse_results)}个文档")
        
        return {
            "documents": diverse_results,
            "from_cache": False
        }
    
    def _get_all_documents(self, tenant_id: str = "default") -> List[Dict]:
        """获取指定租户的所有文档（含 default 共享）"""
        
        try:
            if tenant_id != "default":
                result = vector_store.collection.get(
                    where={"$or": [{"tenant_id": tenant_id}, {"tenant_id": "default"}]},
                    include=["documents", "metadatas"]
                )
            else:
                result = vector_store.collection.get(
                    where={"tenant_id": tenant_id},
                    include=["documents", "metadatas"]
                )
            
            if not result or not result.get("ids"):
                return []
            
            documents = []
            for i, doc_id in enumerate(result["ids"]):
                documents.append({
                    "id": doc_id,
                    "text": result["documents"][i],
                    "metadata": result["metadatas"][i] if result["metadatas"] else {}
                })
            
            logger.info(f"从知识库获取文档: {len(documents)}个")
            return documents
            
        except Exception as e:
            logger.error(f"获取文档失败: {str(e)}")
            return []
    
    def ask_with_hyde(self, question: str, top_k: int = 3, tenant_id: str = "default") -> Dict:
        """使用HyDE的RAG问答（带租户隔离）"""
        
        cached = cache_manager.get_search_results(f"hyde:{tenant_id}:{question}", top_k)
        if cached:
            logger.info("HyDE使用缓存的检索结果")
            documents = cached
            from_cache = True
        else:
            enhanced_query_vector = hyde.hybrid_query_embedding(question)
            
            hyde_results = vector_store.search_by_vector(enhanced_query_vector, top_k=top_k, tenant_id=tenant_id)
            
            if not hyde_results:
                retrieval_result = self.retrieve_with_quality(question, top_k, tenant_id=tenant_id)
                documents = retrieval_result["documents"]
            else:
                documents = reranker.rerank_with_cross_encoder(question, hyde_results)
                documents = documents[:top_k]
            
            if documents:
                cache_manager.set_search_results(f"hyde:{tenant_id}:{question}", top_k, documents)
            from_cache = False
        
        if not documents:
            return {
                "answer": "没有找到相关信息",
                "sources": [],
                "method": "hyde",
                "from_cache": False
            }
        
        # 5. 构建上下文
        context = self._build_context(documents)
        
        # 6. 生成回答
        prompt = self.system_prompt.format(context=context, question=question)
        answer = llm_client.chat([{"role": "user", "content": prompt}])
        
        return {
            "answer": answer,
            "sources": documents,
            "method": "hyde",
            "from_cache": from_cache
        }
    
    def _build_context(self, documents: List[Dict]) -> str:
        """构建上下文"""
        context_parts = []
        for i, doc in enumerate(documents, 1):
            context_parts.append(f"[{i}] {doc['text']}")
        return "\n\n".join(context_parts)
    
    def compare_methods(self, question: str) -> Dict:
        """对比不同检索方法的效果"""
        
        # 方法1：纯向量检索
        # 方法2：混合检索
        # 方法3：混合检索 + 重排序
        # 方法4：HyDE + 混合检索 + 重排序
        
        results = {
            "question": question,
            "methods": {}
        }
        
        # 1. 基础RAG（原版）
        original = knowledge_base.get_context(question, top_k=3)
        
        # 2. 混合检索
        hybrid_search.build_bm25_index(self._get_all_documents())
        hybrid_results = hybrid_search.hybrid_search(question, top_k=5)
        
        # 3. 重排序
        reranked = reranker.rerank_with_cross_encoder(question, hybrid_results)
        
        # 4. HyDE增强
        hyde_enhanced = self.ask_with_hyde(question)
        
        results["methods"] = {
            "original": {"has_context": bool(original)},
            "hybrid": {"count": len(hybrid_results)},
            "reranked": {"count": len(reranked)},
            "hyde": {"answer": hyde_enhanced["answer"][:100]}
        }
        
        return results

# 全局实例
rag_v2 = RAGChainV2()