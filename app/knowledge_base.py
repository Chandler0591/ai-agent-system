import os
import uuid
from typing import List, Dict, Optional
from datetime import datetime
from app.vector_store import vector_store, VectorStore
from app.document_processor import document_processor
from app.logger import logger

class KnowledgeBase:
    """知识库管理系统 - 支持多文档、统计、删除"""
    
    def __init__(self):
        self.documents_cache = {}  # 简单缓存
        
    def add_pdf(self, pdf_path: str, source_name: str = None, skip_duplicate: bool = True, tenant_id: str = "default") -> Dict:
        """添加PDF到知识库（带租户隔离）"""
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"文件不存在: {pdf_path}")
        
        source_name = source_name or os.path.basename(pdf_path)
        
        # 检查重复（租户范围内）
        if skip_duplicate and vector_store.source_exists(source_name, tenant_id):
            file_size = os.path.getsize(pdf_path)
            return {
                "status": "duplicate",
                "file": source_name,
                "chunks": 0,
                "message": f"'{source_name}' 已存在于知识库中"
            }
        
        try:
            # 处理文档
            documents, stats = document_processor.process_pdf(pdf_path, source_name)
            
            # 存入向量库（Celery Worker 可能看不到 API 创建的集合，做容错重建）
            try:
                added_count = vector_store.add_documents(documents, tenant_id=tenant_id)
            except Exception as ve:
                logger.warning(f"向量库写入失败（{ve}），尝试重建集合...")
                vector_store.collection = vector_store.client.get_or_create_collection(
                    name=vector_store.collection_name,
                    metadata={"hnsw:space": "cosine"}
                )
                added_count = vector_store.add_documents(documents, tenant_id=tenant_id)
            
            result = {
                "status": "success",
                "file": source_name,
                "chunks": added_count,
                "stats": stats
            }
            
            logger.info(f"知识库添加成功: {source_name}, {added_count}个文档")
            return result
            
        except Exception as e:
            logger.error(f"添加PDF失败: {str(e)}")
            raise
    
    def search(self, query: str, top_k: int = 3, source_filter: str = None, tenant_id: str = "default") -> List[Dict]:
        """搜索知识库（租户隔离）"""
        filter_metadata = {}
        if source_filter:
            filter_metadata["source"] = source_filter
        
        results = vector_store.search(query, top_k, filter_metadata, tenant_id=tenant_id)
        
        # 按相关度排序
        results.sort(key=lambda x: x["score"], reverse=True)
        
        return results
    
    def get_context(self, query: str, top_k: int = 3) -> str:
        """获取用于LLM的上下文格式"""
        results = self.search(query, top_k)
        
        if not results:
            return ""
        
        context_parts = []
        for i, result in enumerate(results):
            source = result['metadata'].get('source', '未知来源')
            relevance = result['relevance']
            context_parts.append(
                f"[{i+1}] (相关性: {relevance}, 来源: {source})\n{result['text']}"
            )
        
        return "\n\n---\n\n".join(context_parts)
    
    def get_stats(self) -> Dict:
        """获取知识库统计"""
        stats = vector_store.get_collection_stats()
        return stats
    
    def clear(self):
        """清空知识库"""
        global vector_store  # 先声明 global
        vector_store.delete_collection()
        vector_store = VectorStore()
        logger.info("知识库已清空")

    def list_sources(self, tenant_id: str = "default") -> List[Dict]:
        """列出指定租户的所有文档来源"""
        return vector_store.list_sources(tenant_id=tenant_id)

    def delete_source(self, source_name: str, tenant_id: str = "default") -> Dict:
        """删除指定租户下指定来源的所有文档"""
        deleted = vector_store.delete_by_source(source_name, tenant_id=tenant_id)
        if deleted > 0:
            logger.info(f"从知识库删除来源: {source_name} ({deleted}块)")
            return {"status": "success", "source": source_name, "deleted_chunks": deleted}
        return {"status": "not_found", "source": source_name, "deleted_chunks": 0}

# 全局实例
knowledge_base = KnowledgeBase()