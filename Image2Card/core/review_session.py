"""
ReviewSession — 百词斩式复习会话

一次复习会话包含 N 道选择题：
  1. 显示卡片摘要，其中词条名被匿名化（替换为 "_____"）
  2. 从同一工作区随机选择 3 个干扰项 + 1 个正确答案，共 4 个选项
  3. 用户选择后即时反馈对错
  4. 答对 → 熟悉度 +1；答错 → 不变
  5. 会话结束后展示总结

使用::

    cards = kb.cards_by_category("意大利语")
    session = ReviewSession(cards, num_questions=10, difficulty=2)
    q = session.current_question
    # UI 展示 q.anonymized_summary 和 q.options
    session.answer(2)  # 用户选了第3个选项
    # ... 循环直到 session.is_finished
    summary = session.summary()
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from typing import Optional

from dataclass.models import Card

logger = logging.getLogger("image2card.review_session")


# ---------------------------------------------------------------------------
# 内部工具：摘要匿名化
# ---------------------------------------------------------------------------

def _anonymize_term(text: str, term: str) -> str:
    """将文本中的词条名替换为 '_____'，大小写不敏感，保留原标点上下文。"""
    if not term or not text:
        return text
    # 使用正则，忽略大小写，匹配完整单词/短语
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    result = pattern.sub("_____", text)
    # 如果 term 本身包含空格（多词短语），也尝试替换首词
    # 为简洁起见，直接全词替换
    return result


def _pick_distractors(
    correct_card: Card,
    all_cards: list[Card],
    num_distractors: int = 3,
) -> list[str]:
    """
    从卡片池中选择干扰项（与正确答案不同的词条名）。
    
    优先级：
      1. 同一工作区内的卡片
      2. 如果同工作区不够，从全库补充
    
    返回词条名列表（不含正确答案）。
    """
    same_workspace = [c for c in all_cards if c.id != correct_card.id and c.category == correct_card.category]
    other_workspace = [c for c in all_cards if c.id != correct_card.id and c.category != correct_card.category]
    
    candidates = same_workspace.copy()
    if len(candidates) < num_distractors:
        # 不足时从其他工作区补充
        random.shuffle(other_workspace)
        candidates.extend(other_workspace[:num_distractors - len(candidates)])
    
    # 去重（按词条名）
    seen_terms = {correct_card.term.lower()}
    unique_candidates = []
    for c in candidates:
        if c.term.lower() not in seen_terms:
            seen_terms.add(c.term.lower())
            unique_candidates.append(c)
    
    if len(unique_candidates) < num_distractors:
        logger.warning(
            "干扰项不足：需要 %d 个，只找到 %d 个（词条 %s）",
            num_distractors, len(unique_candidates), correct_card.term,
        )
    
    selected = unique_candidates[:num_distractors]
    return [c.term for c in selected]


# ---------------------------------------------------------------------------
# ReviewQuestion
# ---------------------------------------------------------------------------

@dataclass
class ReviewQuestion:
    """一道复习题"""
    card: Card                              # 目标卡片
    anonymized_summary: str                 # 词条名被匿名化的摘要
    options: list[str]                      # 4 个选项（已打乱）
    correct_index: int                      # 正确答案在 options 中的索引
    user_answer_index: Optional[int] = None # 用户选择的索引（None 表示尚未作答）
    is_correct: Optional[bool] = None       # 用户是否答对

    @property
    def correct_term(self) -> str:
        return self.card.term

    @property
    def is_answered(self) -> bool:
        return self.user_answer_index is not None


# ---------------------------------------------------------------------------
# ReviewSession
# ---------------------------------------------------------------------------

class ReviewSession:
    """
    一次复习会话。

    典型用法::

        cards = kb.cards_by_category("意大利语")
        session = ReviewSession(cards, num_questions=10)
        while not session.is_finished:
            q = session.current_question
            # UI 展示 ...
            session.answer(user_choice_index)
        print(session.summary())
    """

    def __init__(
        self,
        cards: list[Card],
        num_questions: int = 10,
        difficulty: int = 2,
        skip_familiar: bool = True,
        random_seed: Optional[int] = None,
    ) -> None:
        """
        Args:
            cards: 候选卡片池（通常来自同一工作区）
            num_questions: 本次会话的题目数（1 ≤ num_questions ≤ len(cards)）
            difficulty: 难度档位 1-3
                1 (简单): 优先选熟悉度高的卡片，摘要保留较多上下文
                2 (中等): 随机选择卡片
                3 (困难): 优先选熟悉度低的卡片，摘要保留较少上下文
            skip_familiar: 是否跳过熟悉度已达上限（5分）的卡片
            random_seed: 可选的随机种子（用于测试复现）
        """
        if random_seed is not None:
            random.seed(random_seed)

        self._difficulty = max(1, min(3, difficulty))
        self._skip_familiar = skip_familiar
        self._questions: list[ReviewQuestion] = []
        self._current_index: int = 0
        self._all_cards = list(cards)

        # 按难度选择卡片
        selected_cards = self._select_cards(cards, num_questions)
        
        # 为每张选中卡片生成题目
        for card in selected_cards:
            question = self._generate_question(card, cards)
            if question is not None:
                self._questions.append(question)

        if not self._questions:
            logger.warning("ReviewSession: 未能生成任何题目，卡片池大小=%d", len(cards))

        logger.info(
            "ReviewSession 已创建：%d 题，难度 %d",
            len(self._questions), self._difficulty,
        )

    # ------------------------------------------------------------------
    # 卡片选择
    # ------------------------------------------------------------------

    def _select_cards(
        self, cards: list[Card], num_questions: int
    ) -> list[Card]:
        """按难度策略从卡片池中选择指定数量的卡片。"""
        if not cards:
            return []

        # 跳过熟悉度已达上限（5分）的卡片
        pool = cards
        if self._skip_familiar:
            pool = [c for c in cards if c.familiarity < 5]
            if not pool:
                logger.info("所有卡片均已达到 5 分熟悉度，跳过过滤")
                pool = cards

        available = [c for c in pool if c.summary.strip() or c.model_note.strip()]
        if not available:
            available = list(cards)

        num = max(1, min(num_questions, len(available)))
        shuffled = available.copy()
        random.shuffle(shuffled)

        if self._difficulty == 1:
            # 简单：优先熟悉度高的
            shuffled.sort(key=lambda c: c.familiarity, reverse=True)
            return shuffled[:num]
        elif self._difficulty == 3:
            # 困难：优先熟悉度低的
            shuffled.sort(key=lambda c: c.familiarity)
            return shuffled[:num]
        else:
            # 中等：随机
            return shuffled[:num]

    # ------------------------------------------------------------------
    # 题目生成
    # ------------------------------------------------------------------

    def _generate_question(
        self, card: Card, all_cards: list[Card]
    ) -> Optional[ReviewQuestion]:
        """为一张卡片生成一道选择题。"""
        # 获取摘要文本
        summary = card.summary or card.model_note or card.term
        if not summary.strip():
            return None

        # 匿名化：将词条名替换为 "_____"
        anonymized = _anonymize_term(summary, card.term)
        
        # 如果匿名化后和原文一样（term 不在 summary 中），尝试用 model_note
        if anonymized == summary and card.model_note and card.model_note != summary:
            anonymized = _anonymize_term(card.model_note, card.term)
        
        # 如果仍然没有变化，说明 term 不在任何文本中，跳过
        if anonymized == summary and anonymized == (card.model_note or ""):
            # 生成一个通用描述
            anonymized = f"请选择与以下描述对应的词条：\n\n{summary}"

        # 选择干扰项
        distractors = _pick_distractors(card, all_cards, num_distractors=3)
        if len(distractors) < 1:
            return None  # 干扰项不足，跳过

        # 构建选项列表并打乱
        options = distractors + [card.term]
        random.shuffle(options)
        correct_index = options.index(card.term)

        return ReviewQuestion(
            card=card,
            anonymized_summary=anonymized,
            options=options,
            correct_index=correct_index,
        )

    # ------------------------------------------------------------------
    # 公共属性
    # ------------------------------------------------------------------

    @property
    def current_question(self) -> Optional[ReviewQuestion]:
        """当前题目，全部答完后返回 None"""
        if self._current_index < len(self._questions):
            return self._questions[self._current_index]
        return None

    @property
    def is_finished(self) -> bool:
        return self._current_index >= len(self._questions)

    @property
    def total_questions(self) -> int:
        return len(self._questions)

    @property
    def current_index(self) -> int:
        """当前题目序号（0-based）"""
        return self._current_index

    @property
    def progress(self) -> tuple[int, int]:
        """(已答题数, 总题数)"""
        return (self._current_index, len(self._questions))

    @property
    def correct_count(self) -> int:
        return sum(1 for q in self._questions if q.is_correct is True)

    @property
    def wrong_count(self) -> int:
        return sum(1 for q in self._questions if q.is_correct is False)

    @property
    def unanswered_count(self) -> int:
        return sum(1 for q in self._questions if not q.is_answered)

    # ------------------------------------------------------------------
    # 答题
    # ------------------------------------------------------------------

    def answer(self, option_index: int) -> bool:
        """
        回答当前题目。

        Args:
            option_index: 用户选择的选项索引 (0-3)

        Returns:
            True 表示回答正确

        Raises:
            RuntimeError: 会话已结束
        """
        if self.is_finished:
            raise RuntimeError("复习会话已结束")

        q = self._questions[self._current_index]
        q.user_answer_index = option_index
        q.is_correct = (option_index == q.correct_index)

        # 更新熟悉度
        if q.is_correct:
            q.card.familiarity = min(5, q.card.familiarity + 1)

        self._current_index += 1

        logger.debug(
            "答题: %s → 选 %d (正确 %d) → %s",
            q.card.term, option_index, q.correct_index,
            "✓" if q.is_correct else "✗",
        )
        return q.is_correct

    # ------------------------------------------------------------------
    # 结果汇总
    # ------------------------------------------------------------------

    def get_results(self) -> list[dict]:
        """返回所有题目的答题结果列表，供 UI 展示。"""
        results = []
        for i, q in enumerate(self._questions):
            results.append({
                "index": i + 1,
                "term": q.card.term,
                "summary": q.card.summary or q.card.model_note or "",
                "user_answer": q.options[q.user_answer_index] if q.user_answer_index is not None else "未作答",
                "correct_answer": q.correct_term,
                "is_correct": q.is_correct,
                "familiarity_after": q.card.familiarity,
            })
        return results

    def summary(self) -> str:
        """生成会话总结文本。"""
        total = self.total_questions
        correct = self.correct_count
        wrong = self.wrong_count
        unanswered = self.unanswered_count

        if total == 0:
            return "本次复习没有题目。"

        accuracy = correct / total * 100 if total > 0 else 0

        lines = [
            f"📊 复习会话总结",
            f"━━━━━━━━━━━━━━━━",
            f"总题数：{total}",
            f"正确：{correct} 题",
            f"错误：{wrong} 题",
            f"正确率：{accuracy:.0f}%",
        ]

        if unanswered > 0:
            lines.append(f"未作答：{unanswered} 题")

        # 按熟悉度变化汇总
        improved = sum(
            1 for q in self._questions
            if q.is_correct and q.card.familiarity > 0
        )
        if improved > 0:
            lines.append(f"熟悉度提升：{improved} 个词条")

        # 列出答错的词条
        wrong_terms = [q.card.term for q in self._questions if q.is_correct is False]
        if wrong_terms:
            lines.append(f"\n📝 需要加强的词条：")
            for term in wrong_terms:
                lines.append(f"  · {term}")

        # 评价等级
        if accuracy >= 90:
            lines.append(f"\n🌟 太棒了！你掌握得很好！")
        elif accuracy >= 70:
            lines.append(f"\n👍 不错，继续加油！")
        elif accuracy >= 50:
            lines.append(f"\n💪 还有提升空间，再练一次吧！")
        else:
            lines.append(f"\n📚 多加练习，你会越来越好的！")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 持久化：将熟悉度变更写回数据库
    # ------------------------------------------------------------------

    def persist_results(self, card_manager) -> None:
        """
        将所有卡片更新后的熟悉度写回数据库。

        Args:
            card_manager: CardManager 实例
        """
        for q in self._questions:
            if q.is_correct:
                card_manager.update(q.card)
        logger.info(
            "ReviewSession: 已持久化 %d 张卡片（%d 正确）",
            len(self._questions), self.correct_count,
        )

    # ------------------------------------------------------------------
    # 难度说明
    # ------------------------------------------------------------------

    @staticmethod
    def difficulty_description(difficulty: int) -> str:
        descriptions = {
            1: "简单 — 优先熟悉的词条，摘要详细",
            2: "中等 — 随机选择词条",
            3: "困难 — 优先陌生的词条，摘要精简",
        }
        return descriptions.get(difficulty, "未知难度")
