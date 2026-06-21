import hashlib
import re
from typing import List, Dict, Optional
from pypdf import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from app.logger import logger

from datetime import datetime

class DocumentProcessor:
    """文档处理器 - 支持PDF解析和智能切分"""
    
    def __init__(self):
        # 文本切分器：每500字一段，重叠50字
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
            length_function=len
        )
    
    def extract_text_from_pdf(self, pdf_path: str) -> tuple:
        """从PDF提取文本，返回(文本, 页数)"""
        try:
            reader = PdfReader(pdf_path)
            text = ""
            pages_metadata = []
            
            for page_num, page in enumerate(reader.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
                    pages_metadata.append({
                        "page": page_num,
                        "text_preview": page_text[:100]
                    })
            
            logger.info(f"PDF解析完成: {len(reader.pages)}页, {len(text)}字符")
            return text, len(reader.pages)
        except Exception as e:
            err_str = str(e)
            if "Odd-length string" in err_str:
                logger.error(f"PDF解析失败（文件可能已损坏或编码不兼容）: {err_str}")
                raise ValueError("PDF 文件可能已损坏或编码不兼容，无法解析")
            logger.error(f"PDF解析失败: {err_str}")
            raise
    
    def clean_text(self, text: str) -> str:
        """清洗文本"""
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text)
        # 移除特殊字符
        text = re.sub(r'[^\w\u4e00-\u9fff\s\.\,\!\?\;\:\'\"\(\)\[\]\{\}]', '', text)
        return text.strip()
    
    def split_text(self, text: str) -> List[str]:
        """智能切分文本"""
        # 先清洗
        text = self.clean_text(text)
        
        # 切分
        chunks = self.splitter.split_text(text)
        
        # 过滤太短的chunk
        chunks = [chunk for chunk in chunks if len(chunk) > 20]
        
        logger.info(f"文本切分完成: 原始{len(text)}字符 -> {len(chunks)}段")
        return chunks
    
    def process_pdf(self, pdf_path: str, source_name: str = None) -> tuple:
        """处理PDF文件，返回(文档列表, 统计信息)"""
        # 1. 提取文本
        text, page_count = self.extract_text_from_pdf(pdf_path)
        
        if not text.strip():
            raise ValueError("PDF文件没有提取到文本内容")
        
        # 2. 提取文档级元数据（year、author、topic、language 等）
        doc_metadata = self.extract_metadata(text, source_name or pdf_path)
        
        # 3. 切分
        chunks = self.split_text(text)
        
        if not chunks:
            raise ValueError("文本切分后没有有效内容")
        
        # 4. 构建文档结构
        documents = []
        for i, chunk in enumerate(chunks):
            doc_id = hashlib.md5(f"{source_name}_{i}_{chunk[:50]}".encode()).hexdigest()
            chunk_metadata = {
                "source": source_name or pdf_path,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "page_estimate": int(i * page_count / len(chunks)) + 1 if chunks else 1,
                "timestamp": str(datetime.now()),
                # 文档级元数据（每个 chunk 继承）
                **doc_metadata
            }
            documents.append({
                "id": doc_id,
                "text": chunk,
                "metadata": chunk_metadata
            })
        
        stats = {
            "total_chunks": len(documents),
            "total_chars": len(text),
            "page_count": page_count,
            "avg_chunk_size": sum(len(d["text"]) for d in documents) // len(documents) if documents else 0,
            "metadata": doc_metadata
        }
        
        return documents, stats
    
    def extract_metadata(self, text: str, source_name: str = "") -> Dict:
        """
        从文本中提取元数据
        - year: 四位数年份（如 2024）
        - author: 作者信息
        - language: zh / en / mixed
        - topic: 关键词推断主题
        - file_type: 文件类型标识
        """
        metadata = {
            "file_type": "pdf",
            "language": self._detect_language(text),
        }
        
        # 提取年份
        year_match = re.search(r'(?:19|20)\d{2}', text)
        if year_match:
            metadata["year"] = int(year_match.group())
        
        # 提取作者信息
        author = self._extract_author(text)
        if author:
            metadata["author"] = author
        
        # 推断主题（基于关键词密度）
        topic = self._infer_topic(text)
        if topic:
            metadata["topic"] = topic
        
        logger.info(f"元数据提取: {source_name} → {metadata}")
        return metadata
    
    def _detect_language(self, text: str) -> str:
        """检测文本语言：zh / en / mixed"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        total = chinese_chars + english_words
        if total == 0:
            return "unknown"
        if chinese_chars / total > 0.6:
            return "zh"
        elif english_words / total > 0.6:
            return "en"
        return "mixed"
    
    def _extract_author(self, text: str) -> Optional[str]:
        """提取作者信息"""
        # 常见中文作者模式
        patterns = [
            r'作者[：:]\s*(.+?)(?:\n|$)',
            r'Author[：:]\s*(.+?)(?:\n|$)',
            r'撰写人[：:]\s*(.+?)(?:\n|$)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                author = match.group(1).strip()
                if len(author) < 50 and author:
                    return author
        return None
    
    # 主题关键词映射
    _TOPIC_KEYWORDS = {
        "AI": ["人工智能", "AI", "机器学习", "深度学习", "神经网络", "大模型", "LLM"],
        "卡口系统": ["卡口", "车辆识别", "车牌", "交通", "监控"],
        "编程": ["Python", "Java", "代码", "函数", "API", "编程"],
        "数据库": ["数据库", "SQL", "Redis", "PostgreSQL", "MySQL"],
        "Docker": ["Docker", "容器", "Kubernetes", "K8s", "镜像"],
        "安全": ["安全", "加密", "认证", "权限", "防火墙"],
    }
    
    def _infer_topic(self, text: str) -> Optional[str]:
        """基于关键词密度推断主题"""
        text_lower = text.lower()
        best_topic = None
        best_score = 0
        for topic, keywords in self._TOPIC_KEYWORDS.items():
            score = sum(text_lower.count(kw.lower()) for kw in keywords)
            if score > best_score:
                best_score = score
                best_topic = topic
        return best_topic if best_score >= 2 else None

# 全局实例
document_processor = DocumentProcessor()