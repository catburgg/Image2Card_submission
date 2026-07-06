"""
CardManager — 卡片业务逻辑层

在 KnowledgeBase（内存）+ Repository（SQLite）之上提供统一的卡片 CRUD 接口，
以及关系管理、分类树管理等业务操作。

公共接口::

    mgr = CardManager(kb, repo)

    # CRUD
    card = mgr.create(term="Carbonara", ...)
    mgr.update(card)
    mgr.delete(card_id)

    # 查询
    cards = mgr.filter(category="食物", familiarity_max=3)
    cards = mgr.search(query="roma pasta")

    # 联想补全（供 UI 搜索框使用）
    suggestions = mgr.suggest(prefix="Car", limit=8)

    # 关系操作
    mgr.add_relation(from_id, to_id, RelationType.IS_A)
    mgr.remove_relation(from_id, to_id, RelationType.IS_A)
    mgr.auto_link_from_image(card_ids)   # APPEARS_WITH

    # 分类树
    tree = mgr.category_tree()           # {"食物": ["意大利菜", "中餐"], ...}
    mgr.add_category(path="食物/法餐")
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from dataclass.models import (
    Card,
    KnowledgeBase,
    Link,
    RelationType,
)
from storage.repository import Repository

logger = logging.getLogger("image2card.card_manager")


# ---------------------------------------------------------------------------
# 内部工具：模糊匹配评分（不依赖第三方库）
# ---------------------------------------------------------------------------

def _bigram_set(text: str) -> set[str]:
    t = text.strip().lower()
    return {t[i:i+2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def _jaccard(a: str, b: str) -> float:
    ba, bb = _bigram_set(a), _bigram_set(b)
    if not ba and not bb:
        return 1.0
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def _contains_score(query: str, card: Card) -> float:
    """
    多字段搜索评分（0.0–1.0）。
    优先词条名精确命中，其次摘要，最后全文。
    """
    q = query.strip().lower()
    if not q:
        return 1.0

    term_lower    = card.term.lower()
    summary_lower = card.summary.lower()
    note_lower    = (card.model_note + " " + card.user_note).lower()

    # 精确前缀或完整包含 → 高分
    if term_lower.startswith(q):
        return 1.0
    if q in term_lower:
        return 0.9
    if q in summary_lower:
        return 0.6
    if q in note_lower:
        return 0.3

    # bigram 相似度兜底
    sim = _jaccard(q, card.term)
    return sim if sim > 0.3 else 0.0


# ---------------------------------------------------------------------------
# CardManager
# ---------------------------------------------------------------------------

class CardManager:
    """
    卡片 CRUD + 关系 + 分类 业务管理器。

    所有写操作都会同时更新 KnowledgeBase（内存）和 Repository（SQLite），
    保持两者一致。
    """

    def __init__(self, kb: KnowledgeBase, repo: Repository) -> None:
        self._kb   = kb
        self._repo = repo

    @property
    def kb(self) -> KnowledgeBase:
        """暴露只读 KnowledgeBase，供 UI 层查询（不要直接写）"""
        return self._kb

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        term: str,
        *,
        category: str = "",
        summary: str = "",
        model_note: str = "",
        user_note: str = "",
        links: Optional[list[Link]] = None,
        familiarity: int = 0,
        source_image_ids: Optional[list[str]] = None,
    ) -> Card:
        """创建一张新卡片并入库。term 不能为空。"""
        if not term.strip():
            raise ValueError("词条名 term 不能为空")

        card = Card(
            term=term.strip(),
            category=category,
            summary=summary,
            model_note=model_note,
            user_note=user_note,
            links=links or [],
            familiarity=max(0, min(5, familiarity)),
            source_image_ids=source_image_ids or [],
        )

        self._kb.add_card(card)
        self._repo.save_card(card)
        logger.info("create: %s (id=%s)", card.term, card.id)
        return card

    def update(self, card: Card) -> None:
        """
        更新卡片（调用方就地修改 Card 字段后调用此方法持久化）。
        自动刷新 updated_at。
        """
        card.updated_at = datetime.now()
        # KnowledgeBase 持有同一对象引用，无需额外操作
        self._repo.save_card(card)
        logger.debug("update: %s (id=%s)", card.term, card.id)

    def delete(self, card_id: str) -> None:
        """从内存和数据库删除卡片，同时清理其他卡片中指向它的边"""
        card = self._kb.get_card(card_id)
        if card is None:
            logger.warning("delete: 卡片 %s 不存在", card_id)
            return

        # 清理其他卡片中指向此 card 的出边
        for other in self._kb.all_cards():
            if other.id == card_id:
                continue
            original_len = len(other.edges)
            other.edges = [e for e in other.edges if e.to_card_id != card_id]
            if len(other.edges) != original_len:
                self._repo.save_card(other)

        self._kb.remove_card(card_id)
        self._repo.delete_card(card_id)
        logger.info("delete: %s (id=%s)", card.term, card_id)

    def get(self, card_id: str) -> Optional[Card]:
        return self._kb.get_card(card_id)

    def get_by_term(self, term: str) -> Optional[Card]:
        return self._kb.find_by_term(term)

    def all_cards(self) -> list[Card]:
        return self._kb.all_cards()

    # ------------------------------------------------------------------
    # 过滤与搜索
    # ------------------------------------------------------------------

    def filter(
        self,
        *,
        category: str = "",
        familiarity_min: int = 0,
        familiarity_max: int = 5,
        source_image_id: str = "",
    ) -> list[Card]:
        """
        多维过滤。所有条件按 AND 组合，空字符串表示不限制。
        """
        result = []
        for card in self._kb.all_cards():
            if category and card.category != category:
                continue
            if not (familiarity_min <= card.familiarity <= familiarity_max):
                continue
            if source_image_id and source_image_id not in card.source_image_ids:
                continue
            result.append(card)
        return result

    def search(
        self,
        query: str,
        *,
        category: str = "",
        familiarity_max: int = 5,
        limit: int = 50,
    ) -> list[Card]:
        """
        全文搜索（term / summary / model_note / user_note）。
        返回按相关度降序排列的卡片列表。
        """
        if not query.strip():
            return self.filter(
                category=category,
                familiarity_max=familiarity_max,
            )[:limit]

        scored: list[tuple[float, Card]] = []
        for card in self._kb.all_cards():
            # 先过滤
            if category and card.category != category:
                continue
            if card.familiarity > familiarity_max:
                continue
            score = _contains_score(query, card)
            if score > 0.0:
                scored.append((score, card))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [card for _, card in scored[:limit]]

    def suggest(self, prefix: str, limit: int = 8) -> list[str]:
        """
        前缀匹配联想补全，返回词条名列表（不区分大小写）。
        先返回精确前缀匹配，再补充包含匹配。
        """
        p = prefix.strip().lower()
        if not p:
            return []

        exact_prefix: list[str] = []
        contains:     list[str] = []

        for card in self._kb.all_cards():
            t = card.term.lower()
            if t.startswith(p):
                exact_prefix.append(card.term)
            elif p in t:
                contains.append(card.term)

        seen: set[str] = set()
        result: list[str] = []
        for term in exact_prefix + contains:
            if term not in seen:
                seen.add(term)
                result.append(term)
            if len(result) >= limit:
                break

        return result

    def find_similar(
        self,
        term: str,
        threshold: float = 0.5,
        limit: int = 5,
    ) -> list[tuple[Card, float]]:
        """
        返回与 term 相似度超过 threshold 的卡片，按相似度降序。
        用于 CandidateManager 去重和 UI 合并提示。
        """
        scored: list[tuple[float, Card]] = []
        for card in self._kb.all_cards():
            score = _jaccard(term, card.term)
            if score >= threshold:
                scored.append((score, card))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(card, score) for score, card in scored[:limit]]

    # ------------------------------------------------------------------
    # 关系管理
    # ------------------------------------------------------------------

    def add_relation(
        self,
        from_card_id: str,
        to_card_id: str,
        relation_type: RelationType = RelationType.RELATED_TO,
        weight: float = 1.0,
        created_by: str = "user",
    ) -> None:
        """为两张卡片添加有向边，并持久化"""
        card = self._kb.get_card(from_card_id)
        if card is None:
            raise KeyError(f"卡片 {from_card_id!r} 不存在")
        if self._kb.get_card(to_card_id) is None:
            raise KeyError(f"卡片 {to_card_id!r} 不存在")

        card.add_edge(to_card_id, relation_type, weight, created_by)
        self._repo.save_card(card)
        logger.debug(
            "add_relation: %s -[%s]-> %s",
            from_card_id, relation_type.value, to_card_id,
        )

    def remove_relation(
        self,
        from_card_id: str,
        to_card_id: str,
        relation_type: Optional[RelationType] = None,
    ) -> None:
        """
        删除从 from_card_id 到 to_card_id 的边。
        relation_type 为 None 时删除所有类型的边。
        """
        card = self._kb.get_card(from_card_id)
        if card is None:
            return
        original_len = len(card.edges)
        if relation_type is None:
            card.edges = [e for e in card.edges if e.to_card_id != to_card_id]
        else:
            card.edges = [
                e for e in card.edges
                if not (e.to_card_id == to_card_id and e.relation_type == relation_type)
            ]
        if len(card.edges) != original_len:
            self._repo.save_card(card)

    def auto_link_from_image(self, card_ids: list[str]) -> int:
        """
        对同一张图片中出现的所有卡片两两建立 APPEARS_WITH 双向边。
        返回新建边数（单向计数）。
        """
        count = 0
        for i, id_a in enumerate(card_ids):
            card_a = self._kb.get_card(id_a)
            if card_a is None:
                continue
            for id_b in card_ids[i + 1:]:
                card_b = self._kb.get_card(id_b)
                if card_b is None:
                    continue
                before = len(card_a.edges)
                card_a.add_edge(id_b, RelationType.APPEARS_WITH, weight=0.5, created_by="system")
                card_b.add_edge(id_a, RelationType.APPEARS_WITH, weight=0.5, created_by="system")
                if len(card_a.edges) > before:
                    count += 1
                    self._repo.save_card(card_a)
                    self._repo.save_card(card_b)
        logger.info("auto_link_from_image: 新增 %d 条 APPEARS_WITH 边", count)
        return count

    def get_related_cards(self, card_id: str) -> list[tuple[Card, Card.Edge]]:
        """
        返回与 card_id 相关的所有卡片及其边信息（出边 + 入边合并）。
        """
        card = self._kb.get_card(card_id)
        if card is None:
            return []

        result: list[tuple[Card, Card.Edge]] = []
        seen: set[str] = set()

        # 出边
        for edge in card.edges:
            neighbor = self._kb.get_card(edge.to_card_id)
            if neighbor and neighbor.id not in seen:
                result.append((neighbor, edge))
                seen.add(neighbor.id)

        # 入边
        for from_id, edge in self._kb.in_edges(card_id):
            neighbor = self._kb.get_card(from_id)
            if neighbor and neighbor.id not in seen:
                result.append((neighbor, edge))
                seen.add(neighbor.id)

        return result

    # ------------------------------------------------------------------
    # 工作区（Category）管理
    # ------------------------------------------------------------------

    def create_category(
        self,
        name: str,
        description: str = "",
        color: str = "",
        icon: str = "📁",
    ) -> "Category":
        """
        创建并持久化一个新的 Category（工作区）。
        name 必须唯一；重复调用（相同 name）会抛出 ValueError。
        """
        from dataclass.models import Category, CATEGORY_COLORS  # 延迟导入避免循环
        if self._kb.get_category(name):
            raise ValueError(f"Category 已存在: {name!r}")
        if not color:
            # 按已有类别数量轮转调色盘
            color = CATEGORY_COLORS[len(self._kb.all_categories()) % len(CATEGORY_COLORS)]
        cat = Category(name=name, description=description, color=color, icon=icon)
        self._kb.add_category(cat)
        self._repo.save_category(cat)
        logger.info("create_category: %r", name)
        return cat

    def delete_category(self, name: str, *, reassign_to: str = "") -> None:
        """
        删除 Category。其下的卡片和图片的 category 字段被重置为
        reassign_to（默认 ""，即未分类）。
        """
        for card in self._kb.cards_by_category(name):
            card.category = reassign_to
            self._repo.save_card(card)
        for image in self._kb.images_by_category(name):
            image.category = reassign_to
            self._repo.save_image(image)
        self._kb.remove_category(name)
        self._repo.delete_category(name)
        logger.info("delete_category: %r (reassign_to=%r)", name, reassign_to)

    def rename_category(self, old_name: str, new_name: str) -> None:
        """
        重命名 Category，同步更新 KnowledgeBase 和数据库中所有引用。
        """
        if not self._kb.get_category(old_name):
            raise ValueError(f"Category 不存在: {old_name!r}")
        if self._kb.get_category(new_name):
            raise ValueError(f"Category 已存在: {new_name!r}")
        self._kb.rename_category(old_name, new_name)
        self._repo.rename_category(old_name, new_name)
        logger.info("rename_category: %r -> %r", old_name, new_name)

    def get_workspace(self, category_name: str) -> dict:
        """
        返回指定 Category 的工作区快照：

        ::

            {
              "category":   Category,
              "cards":      list[Card],
              "images":     list[SourceImage],
              "graph_data": GraphData,          # 由 GraphEngine 生成
            }
        """
        from core.graph import GraphEngine  # 延迟导入
        cat = self._kb.get_category(category_name)
        cards = self._kb.cards_by_category(category_name)
        images = self._kb.images_by_category(category_name)
        graph_data = GraphEngine().build(cards) if cards else None
        return {
            "category":   cat,
            "cards":      cards,
            "images":     images,
            "graph_data": graph_data,
        }

    def category_tree(self) -> dict:
        """
        返回所有 Category 的字典映射：{name: Category}。
        UI 可直接遍历并显示名称、颜色、图标等。
        """
        return {cat.name: cat for cat in self._kb.all_categories()}

    def cards_by_category_prefix(self, prefix: str) -> list[Card]:
        """
        返回类别名称以 prefix 开头的所有卡片（兼容旧路径风格）。
        """
        return [
            c for c in self._kb.all_cards()
            if c.category == prefix or c.category.startswith(prefix + "/")
        ]
