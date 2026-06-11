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
            logger.error(f"PDF解析失败: {str(e)}")
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
        
        # 2. 切分
        chunks = self.split_text(text)
        
        if not chunks:
            raise ValueError("文本切分后没有有效内容")
        
        # 3. 构建文档结构
        documents = []
        for i, chunk in enumerate(chunks):
            doc_id = hashlib.md5(f"{source_name}_{i}_{chunk[:50]}".encode()).hexdigest()
            documents.append({
                "id": doc_id,
                "text": chunk,
                "metadata": {
                    "source": source_name or pdf_path,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "page_estimate": int(i * page_count / len(chunks)) + 1 if chunks else 1,
                    "timestamp": str(datetime.now())
                }
            })
        
        stats = {
            "total_chunks": len(documents),
            "total_chars": len(text),
            "page_count": page_count,
            "avg_chunk_size": sum(len(d["text"]) for d in documents) // len(documents) if documents else 0
        }
        
        return documents, stats

# 全局实例
document_processor = DocumentProcessor()