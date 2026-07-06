"""
ReviewEngine — FSRS 间隔重复复习引擎

基于 FSRS（Free Spaced Repetition Scheduler, Ye et al. 2023）的简化实现。
Card 上已有 stability / difficulty / next_due / review_count / lapses 字段，
ReviewEngine 负责根据用户评级更新这些字段并返回更新后的 Card。

公共接口：
    engine = ReviewEngine()
    cards  = engine.get_due_cards(kb, category="", limit=20)
    log    = engine.process_rating(card, rating, repo)   # 就地修改 card 并持久化
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Optional

from dataclass.models import Card, KnowledgeBase, ReviewLog, ReviewRating

logger = logging.getLogger("image2card.review")


# ---------------------------------------------------------------------------
# FSRS 参数（预训练默认值，来自 open-spaced-repetition/fsrs4anki）
# ---------------------------------------------------------------------------

_W = [
    0.4072, 1.1829, 3.1262, 15.4722,
    7.2102, 0.5316, 1.0651, 0.0589,
    1.5330, 0.1544, 1.0036, 1.9893,
    0.1100, 0.2900, 2.2700, 0.1500,
    2.9898, 0.5100, 0.3400,
]

_DECAY      = -0.5
_FACTOR     = 0.9 ** (1.0 / _DECAY) - 1   # ≈ 19/81


# ---------------------------------------------------------------------------
# 核心公式
# ---------------------------------------------------------------------------

def _forgetting_curve(t: float, s: float) -> float:
    """可提取性 R(t, S) = (1 + t / (9·S))^{-1}"""
    if s <= 0:
        return 0.0
    return (1 + _FACTOR * t / s) ** _DECAY


def _new_stability_after_recall(d: float, s: float, r: float, rating: int) -> float:
    """
    稳定性更新（Good / Easy 路径）。
    S_r' = S · (e^(w17) · (11-d) · S^(-w18) · (e^(w19·(1-r)) - 1) + 1)
    简化版：使用预设 w 参数。
    """
    w = _W
    return s * (
        math.exp(w[17])
        * (11 - d)
        * (s ** -w[18])
        * (math.exp(w[19] * (1 - r)) - 1)
        + 1
    )


def _new_stability_after_forget(d: float, s: float, r: float) -> float:
    """稳定性更新（Again 路径，遗忘后重新记忆）。"""
    w = _W
    return (
        w[11]
        * (d ** -w[12])
        * ((s + 1) ** w[13] - 1)
        * math.exp((1 - r) * w[14])
    )


def _new_difficulty(d: float, rating: int) -> float:
    """
    难度更新（平均向 5 回归）。
    D'(r) = D - w[6] · (r - 3)，然后均值回归。
    范围约束在 [1, 10]。
    """
    w = _W
    d_prime = d - w[6] * (rating - 3)
    # 线性均值回归到 w[4]
    d_prime = d_prime + w[7] * (w[4] - d_prime)
    return max(1.0, min(10.0, d_prime))


def _initial_stability(rating: int) -> float:
    """首次学习时的初始稳定性，基于评级"""
    return max(0.1, _W[rating - 1])  # w[0..3] 对应 Again/Hard/Good/Easy


def _initial_difficulty(rating: int) -> float:
    """首次学习时的初始难度"""
    w = _W
    return max(1.0, min(10.0, w[4] - math.exp(w[5] * (rating - 1)) + 1))


# ---------------------------------------------------------------------------
# ReviewEngine
# ---------------------------------------------------------------------------

class ReviewEngine:
    """
    FSRS 复习调度器。

    典型用法::

        engine = ReviewEngine()
        due    = engine.get_due_cards(kb, category="数学", limit=20)
        for card in due:
            # 展示卡片给用户 …
            log = engine.process_rating(card, ReviewRating.GOOD, repo)
    """

    def get_due_cards(
        self,
        kb: KnowledgeBase,
        category: str = "",
        limit: int = 20,
    ) -> list[Card]:
        """
        返回今日需要复习的卡片列表，按可提取性升序排列（最容易遗忘的优先）。

        - next_due 为 None 的卡片（从未复习）也纳入复习队列。
        - familiarity >= 5 的卡片跳过。
        - category 为空字符串时返回所有类别的卡片。
        """
        today = date.today()
        cards = kb.cards_by_category(category) if category else kb.all_cards()

        due: list[tuple[float, Card]] = []
        for card in cards:
            if card.familiarity >= 5:
                continue
            if card.next_due is None or card.next_due <= today:
                # 计算可提取性（用于排序）
                if card.last_reviewed_at:
                    days = (datetime.now() - card.last_reviewed_at).days
                    r = _forgetting_curve(days, card.stability)
                else:
                    r = 0.0  # 从未复习，最优先
                due.append((r, card))

        due.sort(key=lambda x: x[0])  # 可提取性低的优先
        result = [c for _, c in due[:limit]]
        logger.info(
            "get_due_cards: 类别=%r, 共 %d 张到期, 返回 %d 张",
            category or "全部",
            len(due),
            len(result),
        )
        return result

    def process_rating(
        self,
        card: Card,
        rating: ReviewRating,
        repo=None,  # type: Optional[Repository]
    ) -> ReviewLog:
        """
        根据用户评级更新 Card 的 FSRS 参数（就地修改），
        生成 ReviewLog 并（可选）通过 repo 持久化。

        返回生成的 ReviewLog 对象。
        """
        now = datetime.now()
        r_int = rating.value  # 1=Again 2=Hard 3=Good 4=Easy

        # 当前可提取性（用于日志记录）
        if card.last_reviewed_at:
            days_since = (now - card.last_reviewed_at).total_seconds() / 86400
        else:
            days_since = 0.0
        r_before = _forgetting_curve(days_since, card.stability)

        stability_before = card.stability

        if card.review_count == 0:
            # 首次复习：使用初始公式
            card.stability  = _initial_stability(r_int)
            card.difficulty = _initial_difficulty(r_int)
        else:
            d = card.difficulty
            s = card.stability
            r = _forgetting_curve(days_since, s)

            if r_int == ReviewRating.AGAIN.value:
                # 遗忘路径
                card.stability  = _new_stability_after_forget(d, s, r)
                card.lapses    += 1
            else:
                # 回忆路径（Hard / Good / Easy）
                card.stability  = _new_stability_after_recall(d, s, r, r_int)

            card.difficulty = _new_difficulty(d, r_int)

        # 计算下次复习日期
        interval = max(1, round(card.stability))  # 天数
        if rating == ReviewRating.EASY:
            interval = max(interval, 4)
        elif rating == ReviewRating.AGAIN:
            interval = 1

        card.next_due        = date.today() + timedelta(days=interval)
        card.last_reviewed_at = now
        card.updated_at       = now
        card.review_count    += 1

        # 熟悉度：随复习次数和评级自动更新
        if rating in (ReviewRating.GOOD, ReviewRating.EASY):
            card.familiarity = min(5, card.familiarity + 1)
        elif rating == ReviewRating.AGAIN:
            card.familiarity = max(0, card.familiarity - 1)

        log = ReviewLog(
            card_id=card.id,
            timestamp=now,
            rating=rating,
            stability_before=stability_before,
            stability_after=card.stability,
            retrievability_at_review=r_before,
        )

        if repo is not None:
            repo.save_card(card)
            repo.save_review_log(log)

        logger.info(
            "process_rating: card=%s rating=%s stability %.2f→%.2f next_due=%s",
            card.term, rating.name, stability_before, card.stability, card.next_due,
        )
        return log

    def stats(self, kb: KnowledgeBase) -> dict:
        """
        返回复习统计摘要，供主页展示。
        """
        today = date.today()
        all_cards = kb.all_cards()
        due_count = sum(
            1 for c in all_cards
            if c.familiarity < 5 and (c.next_due is None or c.next_due <= today)
        )
        fam_dist = [0] * 6
        for c in all_cards:
            fam_dist[max(0, min(5, c.familiarity))] += 1

        return {
            "total":         len(all_cards),
            "due_today":     due_count,
            "familiar":      fam_dist[5],  # familiarity == 5
            "fam_dist":      fam_dist,
        }
