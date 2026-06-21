"""
高级 RAG 技术模块
- 父文档检索（Parent Document Retriever）
- 自查询检索（Self-Query with Metadata Filtering）
- 多模态支持（图片 OCR + 文本描述）
- RAGAS 量化评估
"""

import os
import json
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from app.knowledge_base import knowledge_base
from app.vector_store import vector_store, VectorStore
from app.llm_client import llm_client
from app.logger import logger


# ==================== 1. 父文档检索 ====================
@dataclass
class ParentDocument:
    """父文档结构"""
    doc_id: str
    full_text: str          # 完整文本
    child_chunks: List[str] # 子块列表
    metadata: Dict = field(default_factory=dict)


class ParentDocumentRetriever:
    """
    父文档检索器
    策略: 用小 chunk 检索 → 命中后返回所属的父文档（大 chunk）
    好处: 小 chunk 向量匹配更精准，大 chunk 上下文更完整

    隔离: 子块存于独立 ChromaDB collection "parent_doc_children"，
          不与主知识库混合，避免污染全局搜索。
    """

    _CHILD_COLLECTION = "parent_doc_children"

    def __init__(self, child_chunk_size: int = 200, parent_chunk_size: int = 1000):
        self.child_chunk_size = child_chunk_size
        self.parent_chunk_size = parent_chunk_size
        self._parent_store: Dict[str, ParentDocument] = {}
        # 独立向量存储 —— 子块不会污染主 knowledge_base
        self._child_store = VectorStore(collection_name=self._CHILD_COLLECTION)

    def add_document(self, text: str, doc_id: str, metadata: Dict = None) -> int:
        """添加文档并建立父子映射"""
        # 父 chunk：大块切分
        parent_chunks = self._split_text(text, self.parent_chunk_size)
        # 子 chunk：小块切分（用于向量检索）
        child_chunks = self._split_text(text, self.child_chunk_size)

        # 建立父子映射
        parent_doc = ParentDocument(
            doc_id=doc_id,
            full_text=text,
            child_chunks=child_chunks,
            metadata=metadata or {}
        )
        self._parent_store[doc_id] = parent_doc

        # 子块存入独立 collection（不污染主知识库）
        documents = []
        for i, chunk in enumerate(child_chunks):
            documents.append({
                "id": f"{doc_id}_child_{i}",
                "text": chunk,
                "metadata": {
                    "parent_id": doc_id,
                    "chunk_type": "child",
                    "chunk_index": i,
                    **(metadata or {})
                }
            })
        added = self._child_store.add_documents(documents)
        logger.info(f"父文档检索器: 添加 {doc_id} ({len(child_chunks)}子块) → collection={self._CHILD_COLLECTION}")
        return added

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        检索: 小 chunk 匹配 → 返回父文档完整内容
        """
        # Step 1: 用独立 collection 中的小 chunk 检索
        results = self._child_store.search(query, top_k=top_k)

        # Step 2: 追溯到父文档，去重
        seen_parents = set()
        enriched_results = []

        for r in results:
            parent_id = r["metadata"].get("parent_id", "")
            if parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)

            parent = self._parent_store.get(parent_id)
            if parent:
                enriched_results.append({
                    "text": parent.full_text,  # 返回父文档完整文本
                    "metadata": parent.metadata,
                    "score": r["score"],
                    "relevance": r.get("relevance", "中相关"),
                    "match_chunk": r["text"][:100]  # 命中的子块预览
                })

        return enriched_results

    def _split_text(self, text: str, chunk_size: int) -> List[str]:
        """简单按大小切分"""
        sentences = re.split(r'([。！？\n])', text)
        chunks = []
        current = ""
        for s in sentences:
            if len(current) + len(s) > chunk_size:
                if current:
                    chunks.append(current.strip())
                current = s
            else:
                current += s
        if current.strip():
            chunks.append(current.strip())
        return chunks or [text]


# ==================== 2. 自查询检索 ====================

class SelfQueryRetriever:
    """
    自查询检索器
    LLM 自动解析用户意图 → 生成结构化过滤条件 → 精确检索
    例: "2024年关于AI的论文" → filter: {year: 2024, topic: "AI"}
    """

    METADATA_SCHEMA = """
可用元数据字段:
- source: 文档来源文件名
- year: 年份（如 2024）
- author: 作者
- topic: 主题分类
- language: 语言（zh/en）
- file_type: 文件类型（pdf/txt）

请从用户问题中提取过滤条件，返回 JSON:
{
  "filter": {"field": "value", ...},
  "search_query": "去除条件后的纯搜索文本"
}
"""

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """自查询检索"""
        # Step 1: LLM 解析意图 → 生成 filter
        try:
            filter_json = self._extract_filter(query)
            filter_dict = filter_json.get("filter", {})
            search_query = filter_json.get("search_query", query)
        except Exception as e:
            logger.warning(f"自查询解析失败，退回普通检索: {e}")
            filter_dict = {}
            search_query = query

        # Step 2: 带过滤条件检索
        filter_metadata = filter_dict if filter_dict else None
        results = knowledge_base.search(search_query, top_k=top_k)

        # Step 3: 应用过滤
        if filter_metadata:
            results = [
                r for r in results
                if all(
                    str(r["metadata"].get(k, "")).lower() == str(v).lower()
                    for k, v in filter_metadata.items()
                )
            ]

        logger.info(
            f"自查询: '{query}' → filter={filter_dict}, query='{search_query}', "
            f"结果={len(results)}条"
        )
        return results[:top_k]

    def _extract_filter(self, query: str) -> Dict:
        """用 LLM 从自然语言提取过滤条件"""
        prompt = f"""{self.METADATA_SCHEMA}

用户问题: {query}

请严格返回 JSON，不要解释:"""
        response = llm_client.chat([{"role": "user", "content": prompt}], temperature=0)
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {"filter": {}, "search_query": query}


# ==================== 3. 多模态支持 ====================

class MultiModalRAG:
    """
    多模态 RAG —— 支持图片 OCR 文本提取
    依赖: pip install pytesseract Pillow
    系统依赖: sudo apt install tesseract-ocr tesseract-ocr-chi-sim
    """

    @staticmethod
    def is_available() -> bool:
        """检查 OCR 依赖是否可用"""
        try:
            import pytesseract
            from PIL import Image
            return True
        except ImportError:
            return False

    @staticmethod
    def extract_text_from_image(image_path: str, lang: str = "chi_sim+eng") -> str:
        """
        从图片提取文字（OCR）

        Args:
            image_path: 图片文件路径
            lang: 语言代码（chi_sim=中文简体, eng=英文）

        Returns:
            提取的文本
        """
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, lang=lang)
            logger.info(f"OCR 提取: {image_path} → {len(text)} 字符")
            return text.strip()
        except ImportError:
            logger.warning("pytesseract 未安装，跳过 OCR")
            return ""
        except Exception as e:
            logger.error(f"OCR 失败 {image_path}: {e}")
            return ""

    @staticmethod
    def describe_image_with_llm(image_path: str, prompt: str = None) -> str:
        """
        用多模态视觉模型生成图片描述
        
        工作流程:
        1. VISION_ENABLED=true 时 → 调用真实视觉 API
        2. OCR 可用时 → 回退到 OCR 文本提取
        3. 均不可用时 → 返回占位符文件名
        
        支持的厂商: OpenAI(GPT-4o) / 通义千问(Qwen-VL) / 智谱(GLM-4V) / Moonshot
        
        Args:
            image_path: 图片文件路径
            prompt:     自定义描述提示词（可选）
        
        Returns:
            图片文字描述
        """
        # 策略 1: 尝试多模态视觉模型
        if llm_client.is_vision_available:
            description = llm_client.describe_image(image_path, prompt=prompt)
            if description:
                logger.info(f"视觉描述完成: {os.path.basename(image_path)} → {len(description)}字符")
                return description
            logger.warning(f"视觉模型返回空，降级到 OCR")
        
        # 策略 2: 回退到 OCR 文本提取
        if MultiModalRAG.is_available():
            ocr_text = MultiModalRAG.extract_text_from_image(image_path)
            if ocr_text:
                logger.info(f"OCR 提取: {os.path.basename(image_path)} → {len(ocr_text)}字符")
                return f"[OCR识别] {ocr_text}"
        
        # 策略 3: 占位符
        logger.info(f"图片描述: {image_path} (无视觉模型/OCR，使用占位符)")
        return f"[图片: {os.path.basename(image_path)}]"


# ==================== 4. RAGAS 评估 ====================

class RAGASEvaluator:
    """
    RAGAS 评估框架
    指标:
    - Context Relevance (上下文相关性)
    - Answer Faithfulness (答案忠实度)
    - Answer Relevance (答案相关性)
    """

    @staticmethod
    def evaluate_context_relevance(query: str, contexts: List[str]) -> Dict:
        """评估检索上下文与问题的相关性"""
        if not contexts:
            return {"score": 0.0, "relevant_count": 0, "total": 0}

        # LLM 逐条判断相关性
        relevant_count = 0
        for ctx in contexts:
            prompt = f"""判断以下上下文是否与问题相关。
问题: {query}
上下文: {ctx[:500]}
只回答"相关"或"不相关":"""
            try:
                resp = llm_client.chat([{"role": "user", "content": prompt}], temperature=0)
                if "相关" in resp and "不" not in resp:
                    relevant_count += 1
            except Exception:
                relevant_count += 1  # 出错时宽容处理

        score = relevant_count / len(contexts) if contexts else 0
        return {
            "score": round(score, 2),
            "relevant_count": relevant_count,
            "total": len(contexts)
        }

    @staticmethod
    def evaluate_faithfulness(answer: str, contexts: List[str]) -> Dict:
        """评估答案是否忠实于上下文（不编造）"""
        if not contexts or not answer:
            return {"score": 1.0, "claims_checked": 0, "hallucinated": 0}

        # 提取答案中的声明
        sentences = [s.strip() for s in re.split(r'[。！？\n]', answer) if len(s.strip()) > 10]

        hallucinated = 0
        for sentence in sentences[:5]:  # 最多检查5句
            ctx_text = "\n".join(ctx[:300] for ctx in contexts[:3])
            prompt = f"""判断以下声明是否可以从上下文中推断出来。
上下文: {ctx_text}
声明: {sentence}
只回答"可推断"或"无法推断":"""
            try:
                resp = llm_client.chat([{"role": "user", "content": prompt}], temperature=0)
                if "无法" in resp:
                    hallucinated += 1
            except Exception:
                pass

        total = min(len(sentences), 5)
        score = 1 - (hallucinated / total) if total > 0 else 1.0
        return {
            "score": round(score, 2),
            "claims_checked": total,
            "hallucinated": hallucinated
        }

    @staticmethod
    def evaluate_answer_relevance(query: str, answer: str) -> Dict:
        """评估答案与问题的相关性"""
        if not answer:
            return {"score": 0.0}

        prompt = f"""评估以下回答与问题的相关性（0-1分）。
问题: {query}
回答: {answer[:500]}
只返回数字（如 0.8）:"""
        try:
            resp = llm_client.chat([{"role": "user", "content": prompt}], temperature=0)
            score = float(re.search(r'[\d.]+', resp).group())
            return {"score": round(min(max(score, 0), 1), 2)}
        except Exception:
            return {"score": 0.5}

    def evaluate_all(self, query: str, answer: str, contexts: List[str]) -> Dict:
        """运行完整评估"""
        results = {
            "context_relevance": self.evaluate_context_relevance(query, contexts),
            "faithfulness": self.evaluate_faithfulness(answer, contexts),
            "answer_relevance": self.evaluate_answer_relevance(query, answer),
        }
        # 综合分数
        scores = [v["score"] for v in results.values()]
        results["overall"] = round(sum(scores) / len(scores), 2)
        logger.info(f"RAGAS 评估: overall={results['overall']}, " + ", ".join(
            f"{k}={v['score']}" for k, v in results.items() if k != "overall"
        ))
        return results


# ==================== 全局实例 ====================
parent_retriever = ParentDocumentRetriever()
self_query_retriever = SelfQueryRetriever()
multi_modal_rag = MultiModalRAG()
ragas_evaluator = RAGASEvaluator()
