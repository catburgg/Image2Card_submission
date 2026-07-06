"""
UserPreferences — 用户选择历史管理

记录用户在候选词条中的决策（拒绝/熟悉），用于：
  1. 引导 LLM 不重复推荐被拒绝的词条
  2. 分析用户偏好，改进识别质量

不修改数据库，而是在 ~/.image2card/user_preferences.json 中维护。

使用::

    prefs = UserPreferences(config.data_dir)
    prefs.add_rejected_term("Carbona", reason="ignore")      # 用户忽略了
    prefs.add_rejected_term("Tiramisu", reason="familiar")   # 用户标记为已熟悉
    rejected = prefs.get_rejected_terms(limit=20)
    prefs.save()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("image2card.user_preferences")


@dataclass
class RejectedTerm:
    """被拒绝的词条记录"""
    term: str                           # 词条名
    reason: str                         # 原因：ignore | familiar
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    image_id: Optional[str] = None      # 来源图片 ID（可选）
    workspace: str = ""                 # 所属工作区（Category.name），空字符串表示全局


class UserPreferences:
    """用户偏好管理器"""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._prefs_file = self._data_dir / "user_preferences.json"
        
        # 复合键：(term, workspace) -> RejectedTerm
        self._rejected_terms: dict[tuple[str, str], RejectedTerm] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载用户偏好"""
        if not self._prefs_file.exists():
            return
        
        try:
            data = json.loads(self._prefs_file.read_text(encoding="utf-8"))
            rejected = data.get("rejected_terms", {})
            for term_key, item in rejected.items():
                # 兼容旧格式（没有 workspace 字段）
                if "workspace" not in item:
                    item["workspace"] = ""
                self._rejected_terms[term_key] = RejectedTerm(**item)
            logger.info(f"已加载 {len(self._rejected_terms)} 条拒绝记录")
        except Exception as e:
            logger.warning(f"加载用户偏好失败：{e}")

    def save(self) -> None:
        """将用户偏好保存到文件"""
        try:
            data = {
                "rejected_terms": {
                    f"{item.term}@{item.workspace}": asdict(item)
                    for item in self._rejected_terms.values()
                }
            }
            self._prefs_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.debug(f"已保存 {len(self._rejected_terms)} 条用户偏好")
        except Exception as e:
            logger.error(f"保存用户偏好失败：{e}")

    def add_rejected_term(
        self,
        term: str,
        reason: str = "ignore",
        image_id: Optional[str] = None,
        workspace: str = "",
    ) -> None:
        """
        添加或更新被拒绝的词条
        
        Args:
            term: 词条名
            reason: 拒绝原因 ("ignore" 或 "familiar")
            image_id: 来源图片 ID（可选）
            workspace: 所属工作区（Category.name），空字符串表示全局
        """
        if not term or not term.strip():
            return
        
        term = term.strip()
        reason = reason.lower()
        
        key = (term, workspace)
        self._rejected_terms[key] = RejectedTerm(
            term=term,
            reason=reason,
            image_id=image_id,
            workspace=workspace,
        )
        
        logger.debug(f"记录拒绝词条：{term} ({reason}) in workspace: {workspace or '(global)'}")

    def get_rejected_terms(
        self,
        limit: int = 50,
        reason: Optional[str] = None,
        workspace: str = "",
    ) -> list[str]:
        """
        获取拒绝词条列表（按时间倒序）
        
        Args:
            limit: 返回最多数量
            reason: 可选筛选 ("ignore" | "familiar" | None=全部)
            workspace: 按工作区过滤（空字符串表示全局）
        
        Returns:
            词条名列表
        """
        items = [t for t in self._rejected_terms.values() if t.workspace == workspace]
        
        # 筛选原因
        if reason:
            items = [t for t in items if t.reason == reason]
        
        # 按时间戳倒序（最近的优先）
        items.sort(key=lambda x: x.timestamp, reverse=True)
        
        return [t.term for t in items[:limit]]

    def get_rejected_summary(self, workspace: Optional[str] = "") -> dict[str, int]:
        """
        获取拒绝统计
        
        Args:
            workspace: 按工作区过滤（空字符串表示全局，None 表示所有工作区）
        
        Returns:
            包含 total/ignored/familiar 的统计字典
        """
        if workspace is None:
            items = list(self._rejected_terms.values())
        else:
            items = [t for t in self._rejected_terms.values() if t.workspace == workspace]
        ignore_count = sum(1 for t in items if t.reason == "ignore")
        familiar_count = sum(1 for t in items if t.reason == "familiar")
        return {
            "total": len(items),
            "ignored": ignore_count,
            "familiar": familiar_count
        }

    def is_rejected(self, term: str, workspace: str = "") -> bool:
        """
        检查词条在特定工作区是否被拒绝
        
        Args:
            term: 词条名
            workspace: 所属工作区（空字符串表示全局）
        
        Returns:
            是否被拒绝
        """
        key = (term.strip(), workspace)
        return key in self._rejected_terms
