"""
数据脱敏引擎 —— 正则匹配 + 智能掩码

规则来源: desensitize_rules 表（PG） / 内置 fallback
调用链: RAG 检索结果 → mask() → 发给公有 LLM
"""
import re
from typing import List, Dict

from app.logger import logger
from app.database import database_manager


class DataDesensitizer:
    """脱敏器 —— 单例，启动时加载规则"""

    _instance = None
    _rules_cache = None  # [(name, compiled_regex, desc), ...]

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.reload_rules()

    def reload_rules(self):
        """从 DB 重新加载规则（支持热更新）"""
        try:
            rules = database_manager.get_desensitize_rules(active_only=True)
        except Exception as e:
            logger.warning(f"脱敏规则 DB 加载失败，使用内置规则: {e}")
            rules = DataDesensitizer._default_rules()

        compiled = []
        for r in rules:
            try:
                compiled.append((r["name"], re.compile(r["regex"]), r.get("desc", "")))
            except re.error as e:
                logger.warning(f"脱敏规则编译失败 [{r['name']}]: {e}")

        DataDesensitizer._rules_cache = compiled
        logger.info(f"脱敏器已加载 {len(compiled)} 条规则")

    @staticmethod
    def _default_rules() -> List[Dict]:
        return [
            {"name": "phone", "regex": r'1[3-9]\d{9}', "desc": "手机号"},
            {"name": "id_card", "regex": r'\d{17}[\dXx]', "desc": "身份证"},
            {"name": "email", "regex": r'[\w.-]+@[\w.-]+\.\w+', "desc": "邮箱"},
            {"name": "amount", "regex": r'(¥|￥|CNY|USD)\s*\d+[\d,]*\.?\d*', "desc": "金额"},
            {"name": "bank_card", "regex": r'\d{16,19}', "desc": "银行卡号"},
        ]

    def mask(self, text: str) -> str:
        """对文本执行脱敏，返回掩码后的字符串"""
        if not text or not self._rules_cache:
            return text or ""

        result = text
        for name, pattern, _desc in self._rules_cache:
            result = pattern.sub(self._mask_match, result)

        return result

    @staticmethod
    def _mask_match(match: re.Match) -> str:
        """掩码策略：保留首尾，中间替换为 *"""
        s = match.group()
        length = len(s)
        if length <= 2:
            return s[0] + "*"
        elif length <= 4:
            return s[0] + "*" * (length - 2) + s[-1]
        else:
            keep = max(2, length // 4)
            return s[:keep] + "*" * (length - 2 * keep) + s[-keep:]

    def is_sensitive(self, text: str) -> bool:
        """检查文本是否包含敏感信息"""
        if not text or not self._rules_cache:
            return False
        for _name, pattern, _desc in self._rules_cache:
            if pattern.search(text):
                return True
        return False


# 全局单例
desensitizer = DataDesensitizer()
