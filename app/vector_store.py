import chromadb
from typing import List, Dict, Optional
from datetime import datetime
from app.embeddings import embedding_model
from app.logger import logger

class VectorStore:
    """向量数据库"""

    def __init__(self, collection_name: str = "knowledge_base"):
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path="./chroma_data")

        # 优先获取已有集合，不存在则新建
        try:
            self.collection = self.client.get_collection(name=self.collection_name)
            logger.info(f"加载已有集合: {self.collection_name}")
        except Exception:
            self.collection = self.client.create_collection(
                name=self.collection_name,
                metadata={
                    "hnsw:space": "cosine",
                    "created_at": str(datetime.now())
                }
            )
            logger.info(f"创建新集合: {self.collection_name}")

    def add_documents(self, documents: List[Dict], batch_size: int = 100, tenant_id: str = "default") -> int:
        """批量添加文档（带租户标签）"""
        if not documents:
            return 0

        total_added = 0
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]

            ids = [doc["id"] for doc in batch]
            texts = [doc["text"] for doc in batch]
            metadatas = []

            for doc in batch:
                meta = doc.get("metadata", {}).copy()
                meta["added_at"] = str(datetime.now())
                meta["tenant_id"] = tenant_id  # 租户标签
                metadatas.append(meta)

            # 生成向量
            logger.info(f"生成向量: {len(batch)}个文档")
            vectors = embedding_model.encode_batch(texts)

            # 存入数据库
            self.collection.add(
                ids=ids,
                embeddings=vectors,
                documents=texts,
                metadatas=metadatas
            )
            total_added += len(batch)
            logger.info(f"已添加批次 {i // batch_size + 1}: {len(batch)}个文档")

        logger.info(f"向量数据库添加完成: {total_added}个文档")
        return total_added

    def search(self, query: str, top_k: int = 3, filter_metadata: Dict = None, tenant_id: str = "default") -> List[Dict]:
        """搜索相似文档，支持元数据过滤 + 租户隔离"""
        query_vector = embedding_model.encode(query)

        query_params = {
            "query_embeddings": [query_vector],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"]
        }

        # 合并租户过滤 + 自定义过滤
        # 非 default 租户同时可见 default 租户的共享文档
        if tenant_id != "default":
            where = {"$or": [{"tenant_id": tenant_id}, {"tenant_id": "default"}]}
        else:
            where = {"tenant_id": tenant_id}
        if filter_metadata:
            where = {"$and": [where, filter_metadata]}
        query_params["where"] = where

        results = self.collection.query(**query_params)

        documents = []
        if results['documents'] and results['documents'][0]:
            for i in range(len(results['documents'][0])):
                score = 1 - results['distances'][0][i]
                meta = results['metadatas'][0][i]
                documents.append({
                    "text": results['documents'][0][i],
                    "metadata": meta,
                    "score": score,
                    "relevance": self._get_relevance_label(score),
                    "shared": meta.get("tenant_id") == "default"  # 标记共享文档
                })

        return documents

    def search_by_vector(self, query_vector: List[float], top_k: int = 3, filter_metadata: Dict = None, tenant_id: str = "default") -> List[Dict]:
        """使用自定义向量搜索相似文档（带租户隔离）"""
        query_params = {
            "query_embeddings": [query_vector],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"]
        }

        # 非 default 租户同时可见 default 租户的共享文档
        if tenant_id != "default":
            where = {"$or": [{"tenant_id": tenant_id}, {"tenant_id": "default"}]}
        else:
            where = {"tenant_id": tenant_id}
        if filter_metadata:
            where = {"$and": [where, filter_metadata]}
        query_params["where"] = where

        results = self.collection.query(**query_params)

        documents = []
        if results['documents'] and results['documents'][0]:
            for i in range(len(results['documents'][0])):
                score = 1 - results['distances'][0][i]
                meta = results['metadatas'][0][i]
                documents.append({
                    "text": results['documents'][0][i],
                    "metadata": meta,
                    "score": score,
                    "relevance": self._get_relevance_label(score),
                    "shared": meta.get("tenant_id") == "default"
                })

        return documents

    def _get_relevance_label(self, score: float) -> str:
        """根据相似度返回相关性标签"""
        if score >= 0.8:
            return "高相关"
        elif score >= 0.6:
            return "中相关"
        elif score >= 0.4:
            return "低相关"
        else:
            return "弱相关"

    def get_collection_stats(self) -> Dict:
        """获取集合统计信息"""
        try:
            count = self.collection.count()
            return {
                "collection_name": self.collection_name,
                "document_count": count,
                "exists": True
            }
        except Exception as e:
            logger.error(f"获取统计失败: {str(e)}")
            return {
                "collection_name": self.collection_name,
                "document_count": 0,
                "exists": False
            }

    def get_count(self) -> int:
        """兼容上层调用：返回文档总数"""
        return self.collection.count()

    def delete_collection(self):
        """删除集合"""
        try:
            self.client.delete_collection(self.collection_name)
            logger.info(f"已删除集合: {self.collection_name}")
        except Exception as e:
            logger.error(f"删除集合失败: {str(e)}")

    def list_sources(self, tenant_id: str = "default") -> List[Dict]:
        """列出指定租户的所有唯一来源及其文档统计"""
        try:
            result = self.collection.get(
                where={"tenant_id": tenant_id},
                include=["metadatas"]
            )
            if not result or not result.get("ids"):
                return []
            
            sources = {}  # source_name -> {count, sample_id}
            for i, meta in enumerate(result["metadatas"]):
                src = meta.get("source", "未知")
                if src not in sources:
                    sources[src] = {"source": src, "chunks": 0}
                sources[src]["chunks"] += 1
            
            return sorted(sources.values(), key=lambda x: x["source"])
        except Exception as e:
            logger.error(f"列出来源失败: {str(e)}")
            return []

    def delete_by_source(self, source_name: str, tenant_id: str = "default") -> int:
        """删除指定租户下指定来源的所有文档"""
        try:
            result = self.collection.get(
                where={"$and": [{"source": source_name}, {"tenant_id": tenant_id}]},
                include=["metadatas"]
            )
            if not result or not result.get("ids"):
                logger.info(f"未找到来源 '{source_name}' 的文档")
                return 0
            
            delete_ids = result["ids"]
            self.collection.delete(ids=delete_ids)
            logger.info(f"已删除来源 '{source_name}': {len(delete_ids)} 个文档块")
            return len(delete_ids)
        except Exception as e:
            logger.error(f"删除来源失败: {str(e)}")
            return 0

    def source_exists(self, source_name: str, tenant_id: str = "default") -> bool:
        """检查指定租户下来源是否已存在"""
        try:
            result = self.collection.get(
                where={"$and": [{"source": source_name}, {"tenant_id": tenant_id}]},
                limit=1
            )
            return bool(result and result.get("ids"))
        except Exception:
            return False


vector_store = VectorStore()