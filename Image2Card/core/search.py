"""
SearchEngine — 全文搜索与联想补全

在 KnowledgeBase 之上提供：
  1. 全文搜索（多字段加权评分）
  2. 前缀联想补全（用于 UI 搜索框）
  3. 相似卡片查找（用于去重 / 知识图谱推荐）
  4. 按图片 / 类别 / 熟悉度的组合过滤

SearchEngine 是只读的，不修改 KnowledgeBase 或 Repository。
在 AppContext 中持有单例，每次 UI 搜索时直接调用。

公共接口::

    engine = SearchEngine(kb)

    results = engine.search("carbonara")
    results = engine.search("pasta", category="食物", familiarity_max=3)

    suggestions = engine.suggest("Car")         # ["Carbonara", "Carpaccio", ...]

    similar = engine.find_similar("Carbonara")  # [(Card, score), ...]

    stats   = engine.stats()                    # 用于主页展示的统计摘要
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional

from dataclass.models import Card, KnowledgeBase

logger = logging.getLogger("image2card.search")


# ---------------------------------------------------------------------------
# 内部：文本标准化与评分
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """全部转小写，去掉标点，方便匹配"""
    return re.sub(r"[^\w\s]", " ", text.lower())


def _tokens(text: str) -> list[str]:
    return _normalize(text).split()


def _bigrams(text: str) -> set[str]:
    t = _normalize(text).replace(" ", "")
    return {t[i:i+2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def _jaccard(a: str, b: str) -> float:
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba and not bb:
        return 1.0
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def _score_card(query: str, card: Card) -> float:
    """
    多字段加权评分（满分 1.0）。

    字段权重：
      term        1.0   (精确前缀 +bonus)
      summary     0.6
      model_note  0.3
      user_note   0.3
      category    0.1
    """
    q = _normalize(query)
    if not q:
        return 1.0

    score = 0.0

    # --- term ---
    term_norm = _normalize(card.term)
    if term_norm.startswith(q):
        score += 1.0
    elif q in term_norm:
        score += 0.85
    else:
        sim = _jaccard(q, card.term)
        score += sim * 0.7

    # --- summary ---
    if card.summary:
        s = _normalize(card.summary)
        if q in s:
            score += 0.6
        else:
            # token 命中率
            q_tokens = _tokens(q)
            s_tokens = set(_tokens(s))
            hits = sum(1 for t in q_tokens if t in s_tokens)
            if q_tokens:
                score += 0.6 * (hits / len(q_tokens)) * 0.5

    # --- model_note + user_note ---
    combined_note = _normalize(card.model_note + " " + card.user_note)
    if q in combined_note:
        score += 0.3
    else:
        q_tokens = _tokens(q)
        n_tokens = set(_tokens(combined_note))
        hits = sum(1 for t in q_tokens if t in n_tokens)
        if q_tokens:
            score += 0.3 * (hits / len(q_tokens)) * 0.5

    # --- category ---
    if q in _normalize(card.category):
        score += 0.1

    return score


# ---------------------------------------------------------------------------
# SearchEngine
# ---------------------------------------------------------------------------

class SearchEngine:
    """
    只读搜索引擎，直接操作 KnowledgeBase 内存对象。
    KB 更新后搜索结果自动反映最新状态（无需重建索引）。
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self._kb = kb

    # ------------------------------------------------------------------
    # 主搜索
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        category: str = "",
        familiarity_min: int = 0,
        familiarity_max: int = 5,
        source_image_id: str = "",
        limit: int = 50,
        min_score: float = 0.0,
    ) -> list[Card]:
        """
        全文搜索，返回按相关度降序排列的卡片列表。

        query 为空时退化为纯过滤（按 updated_at 倒序）。
        """
        is_empty_query = not query.strip()
        scored: list[tuple[float, Card]] = []

        for card in self._kb.all_cards():
            # 过滤条件
            if category and card.category != category:
                continue
            if not (familiarity_min <= card.familiarity <= familiarity_max):
                continue
            if source_image_id and source_image_id not in card.source_image_ids:
                continue

            if is_empty_query:
                scored.append((0.0, card))
            else:
                s = _score_card(query, card)
                if s >= min_score:
                    scored.append((s, card))

        if is_empty_query:
            # 无查询时按更新时间倒序
            scored.sort(key=lambda x: x[1].updated_at, reverse=True)
        else:
            scored.sort(key=lambda x: x[0], reverse=True)
            # 过滤掉评分为 0 的项
            scored = [(s, c) for s, c in scored if s > 0]

        return [card for _, card in scored[:limit]]

    # ------------------------------------------------------------------
    # 联想补全
    # ------------------------------------------------------------------

    def suggest(
        self,
        prefix: str,
        *,
        category: str = "",
        limit: int = 8,
    ) -> list[str]:
        """
        前缀联想补全，返回词条名列表（不区分大小写）。

        优先级：
          1. 精确前缀匹配
          2. 任意位置包含
          3. 高 bigram 相似度
        """
        p = prefix.strip().lower()
        if not p:
            return []

        exact_prefix: list[str] = []
        contains:     list[str] = []
        similar:      list[tuple[float, str]] = []

        for card in self._kb.all_cards():
            if category and card.category != category:
                continue
            t = card.term.lower()
            if t.startswith(p):
                exact_prefix.append(card.term)
            elif p in t:
                contains.append(card.term)
            else:
                sim = _jaccard(p, card.term)
                if sim > 0.35:
                    similar.append((sim, card.term))

        similar.sort(key=lambda x: x[0], reverse=True)
        similar_terms = [term for _, term in similar]

        seen: set[str] = set()
        result: list[str] = []
        for term in exact_prefix + contains + similar_terms:
            if term not in seen:
                seen.add(term)
                result.append(term)
            if len(result) >= limit:
                break

        return result

    # ------------------------------------------------------------------
    # 相似卡片
    # ------------------------------------------------------------------

    def find_similar(
        self,
        term: str,
        threshold: float = 0.45,
        limit: int = 5,
        exclude_id: str = "",
    ) -> list[tuple[Card, float]]:
        """
        返回与 term 相似度超过 threshold 的卡片，按相似度降序。
        exclude_id 用于排除自身。
        """
        scored: list[tuple[float, Card]] = []
        for card in self._kb.all_cards():
            if card.id == exclude_id:
                continue
            score = _jaccard(term, card.term)
            if score >= threshold:
                scored.append((score, card))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [(card, score) for score, card in scored[:limit]]

    def related_by_category(self, card: Card, limit: int = 10) -> list[Card]:
        """返回同类别的其他卡片（排除自身），按熟悉度升序（优先推荐不熟悉的）"""
        if not card.category:
            return []
        result = [
            c for c in self._kb.all_cards()
            if c.category == card.category and c.id != card.id
        ]
        result.sort(key=lambda c: c.familiarity)
        return result[:limit]

    # ------------------------------------------------------------------
    # 统计摘要（供主页 Dashboard 使用）
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """
        返回知识库统计摘要::

            {
              "total":          100,
              "due_today":      15,      # next_due <= today 且 familiarity < 5
              "familiar":       30,      # familiarity == 5
              "new_this_week":  8,       # 本周创建的卡片
              "fam_dist":       [5, 12, 20, 30, 22, 11],  # 各熟悉度卡片数
              "category_count": 6,
              "image_count":    20,
            }
        """
        today = date.today()
        all_cards = self._kb.all_cards()

        fam_dist = [0] * 6
        due_today = 0
        new_this_week = 0
        now = datetime.now()

        for card in all_cards:
            f = max(0, min(5, card.familiarity))
            fam_dist[f] += 1

            if f < 5 and (card.next_due is None or card.next_due <= today):
                due_today += 1

            days_since_created = (now - card.created_at).days
            if days_since_created <= 7:
                new_this_week += 1

        return {
            "total":          len(all_cards),
            "due_today":      due_today,
            "familiar":       fam_dist[5],
            "new_this_week":  new_this_week,
            "fam_dist":       fam_dist,
            "category_count": len(self._kb.all_categories()),
            "image_count":    len(self._kb.all_images()),
        }
