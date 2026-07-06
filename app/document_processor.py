import hashlib
import re
import os
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
    
    # ---- 多格式文本提取 ----
    def extract_text(self, file_path: str) -> str:
        """自动识别文件类型，提取纯文本"""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.pdf':
            text, _ = self.extract_text_from_pdf(file_path)
            return text
        elif ext == '.docx':
            return self._extract_docx(file_path)
        elif ext == '.xlsx':
            return self._extract_xlsx(file_path)
        elif ext == '.pptx':
            return self._extract_pptx(file_path)
        elif ext in ('.png', '.jpg', '.jpeg', '.bmp', '.tiff'):
            return self._extract_image_ocr(file_path)
        elif ext in ('.txt', '.md', '.csv', '.log'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        else:
            raise ValueError(f"不支持的文件格式: {ext}")

    def _extract_docx(self, file_path: str) -> str:
        """提取 docx 文档文本"""
        try:
            from docx import Document
            doc = Document(file_path)
            parts = []
            for para in doc.paragraphs:
                if para.text.strip():
                    parts.append(para.text)
            # 表格
            for table in doc.tables:
                parts.append("\n--- TABLE ---")
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    parts.append(" | ".join(cells))
            text = "\n".join(parts)
            logger.info(f"DOCX 解析完成: {len(doc.paragraphs)}段, {len(doc.tables)}表, {len(text)}字符")
            return text
        except Exception as e:
            raise ValueError(f"DOCX 解析失败: {e}")

    def _extract_xlsx(self, file_path: str) -> str:
        """提取 xlsx 表格数据"""
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file_path, data_only=True)
            parts = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                parts.append(f"\n### Sheet: {sheet_name}")
                for row in ws.iter_rows(values_only=True):
                    row_vals = [str(c) if c is not None else "" for c in row]
                    if any(row_vals):
                        parts.append(" | ".join(row_vals))
            text = "\n".join(parts)
            logger.info(f"XLSX 解析完成: {len(wb.sheetnames)}工作表, {len(text)}字符")
            return text
        except Exception as e:
            raise ValueError(f"XLSX 解析失败: {e}")

    def _extract_pptx(self, file_path: str) -> str:
        """提取 pptx 演示文稿文本"""
        try:
            from pptx import Presentation
            prs = Presentation(file_path)
            parts = []
            for i, slide in enumerate(prs.slides, 1):
                slide_text = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            if para.text.strip():
                                slide_text.append(para.text)
                if slide_text:
                    parts.append(f"\n### Slide {i}\n" + "\n".join(slide_text))
            text = "\n".join(parts)
            logger.info(f"PPTX 解析完成: {len(prs.slides)}页, {len(text)}字符")
            return text
        except Exception as e:
            raise ValueError(f"PPTX 解析失败: {e}")

    def _extract_image_ocr(self, file_path: str) -> str:
        """图片 OCR 提取文本"""
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(file_path)
            text = pytesseract.image_to_string(img, lang='chi_sim+eng')
            logger.info(f"图片 OCR 完成: {len(text)}字符")
            return text or f"[图片OCR无文本: {os.path.basename(file_path)}]"
        except ImportError:
            logger.warning("pytesseract/PIL 未安装，跳过图片OCR")
            return f"[图片: {os.path.basename(file_path)}]"
        except Exception as e:
            logger.error(f"图片 OCR 失败: {e}")
            return f"[图片OCR失败: {os.path.basename(file_path)}]"
    
    def process_pdf(self, pdf_path: str, source_name: str = None) -> tuple:
        """处理文件，返回(文档列表, 统计信息)"""
        # 1. 自动识别格式提取文本
        ext = os.path.splitext(pdf_path)[1].lower()
        if ext == '.pdf':
            text, page_count = self.extract_text_from_pdf(pdf_path)
        else:
            text = self.extract_text(pdf_path)
            page_count = 1
        
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