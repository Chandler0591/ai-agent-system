import json
from typing import List, Dict

class MemoryDB:
    """内存数据库模拟"""
    def __init__(self):
        self.documents = []
    
    def insert(self, doc: Dict):
        self.documents.append(doc)
        return len(self.documents) - 1
    
    def query(self, sql: str) -> List[Dict]:
        # 简单解析 SELECT * FROM documents WHERE ...
        # 这里先返回所有
        return self.documents
    
    def search_by_keyword(self, keyword: str) -> List[Dict]:
        """关键字搜索"""
        results = []
        for doc in self.documents:
            if keyword in json.dumps(doc):
                results.append(doc)
        return results

db = MemoryDB()

# 插入测试数据
db.insert({"title": "Docker教程", "content": "Docker是容器化平台"})
db.insert({"title": "Python入门", "content": "Python是编程语言"})
