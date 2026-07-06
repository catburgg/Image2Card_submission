"""
CandidateManager — 候选卡片流程管理

职责：
  1. 接收 AnalyzeResult，与 KnowledgeBase 比对，生成带状态的 PendingCandidate 列表
  2. 维护内存中的候选队列（每次图片分析后重置）
  3. 提供 confirm / ignore / merge / confirm_all 操作
  4. 确认后创建 / 更新 Card，自动添加 APPEARS_WITH 关系，持久化到 Repository

公共接口::

    mgr = CandidateManager(kb, repo)
    candidates = mgr.process(analyze_result, image_id)   # -> list[PendingCandidate]
    card = mgr.confirm(candidate_id, edits={})           # 确认单张
    mgr.ignore(candidate_id)
    card = mgr.merge_into(candidate_id, target_card_id)
    cards = mgr.confirm_all_new()                         # 批量确认所有 NEW
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from dataclass.models import (
    AnalyzeResult,
    Card,
    CandidateStatus,
    KnowledgeBase,
    Link,
    RelationType,
    VLMCandidateCard,
    VLMResultItem,
)
from storage.repository import Repository
from core.recognition import is_high_confidence_recognition

logger = logging.getLogger("image2card.candidate")


# ---------------------------------------------------------------------------
# PendingCandidate — 内存中的候选卡片
# ---------------------------------------------------------------------------

@dataclass
class PendingCandidate:
    """
    内存中的候选卡片实体，贯穿整个确认流程。

    status        : 从 AnalyzeResult 推断或用户修改
    matched_card  : status 为 EXISTING / FAMILIAR / SIMILAR 时对应的已有 Card
    vlm_item      : 原始 VLMResultItem（含 bbox）
    vlm_card      : 原始 VLMCandidateCard（含详细内容），NEW / UNCERTAIN 才有
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    term: str = ""
    original_text: str = ""
    status: CandidateStatus = CandidateStatus.NEW

    # VLM 提供的详细内容（NEW / UNCERTAIN 时有效）
    card_summary: str = ""
    model_content: str = ""
    familiarity_suggestion: int = 0
    suggested_links: list[Link] = field(default_factory=list)
    related_terms: list[str] = field(default_factory=list)

    # bbox（像素坐标，来自 VLMResultItem.bbox）
    bbox: Optional[object] = None          # VLMBBox | None
    bbox_confidence: float = 0.0

    # 已有卡片引用（EXISTING / FAMILIAR / SIMILAR）
    matched_card: Optional[Card] = None

    # 所属图片
    image_id: str = ""


# ---------------------------------------------------------------------------
# CandidateManager
# ---------------------------------------------------------------------------

_FAMILIAR_THRESHOLD = 4   # familiarity >= 此值视为"已熟悉"
_SIMILAR_MIN_RATIO  = 0.6  # 词条字符重叠比例阈值（简单相似度）


def _normalize_term(term: str) -> str:
    """小写 + 去首尾空格，用于比对"""
    return term.strip().lower()


def _term_similarity(a: str, b: str) -> float:
    """
    简单的字符级 Jaccard 相似度（bigrams）。
    不依赖第三方库，满足基本去重需求。
    """
    def bigrams(s: str) -> set[str]:
        s = _normalize_term(s)
        return {s[i:i+2] for i in range(len(s) - 1)} if len(s) > 1 else {s}

    ba, bb = bigrams(a), bigrams(b)
    if not ba and not bb:
        return 1.0
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


class CandidateManager:
    """
    候选卡片生命周期管理器。

    典型用法::

        mgr = CandidateManager(kb, repo)
        pending = mgr.process(analyze_result, image_id)
        # UI 展示 pending 列表后……
        mgr.confirm(pending[0].id)
        mgr.ignore(pending[1].id)
        mgr.confirm_all_new()         # 批量确认剩余 NEW
    """

    def __init__(self, kb: KnowledgeBase, repo: Repository) -> None:
        self._kb   = kb
        self._repo = repo
        self._pending: dict[str, PendingCandidate] = {}   # id → PendingCandidate

    # ------------------------------------------------------------------
    # 主入口：从 AnalyzeResult 生成候选列表
    # ------------------------------------------------------------------

    def process(
        self,
        result: AnalyzeResult,
        image_id: str,
    ) -> list[PendingCandidate]:
        """
        将 AnalyzeResult.items 与 KnowledgeBase 比对，
        生成 PendingCandidate 列表（替换旧列表）。

        - NEW / UNCERTAIN → 从 result.cards 中查找详细内容
        - EXISTING / FAMILIAR → 关联已有 Card
        - 若 VLM 标注了 existing/familiar 但 KB 中找不到 → 降级为 NEW
        """
        self._pending.clear()

        # 构建 VLMCandidateCard 索引（term → VLMCandidateCard）
        card_detail: dict[str, VLMCandidateCard] = {
            c.card: c for c in result.cards
        }

        candidates: list[PendingCandidate] = []

        skipped_low_confidence = 0
        for item in result.items:
            if not is_high_confidence_recognition(item):
                skipped_low_confidence += 1
                continue
            pc = self._build_pending(item, card_detail, image_id)
            self._pending[pc.id] = pc
            candidates.append(pc)

        logger.info(
            "process: image=%s, 共 %d 个候选 (new=%d existing=%d familiar=%d similar=%d uncertain=%d skipped_low_confidence=%d)",
            image_id,
            len(candidates),
            sum(1 for c in candidates if c.status == CandidateStatus.NEW),
            sum(1 for c in candidates if c.status == CandidateStatus.EXISTING),
            sum(1 for c in candidates if c.status == CandidateStatus.FAMILIAR),
            sum(1 for c in candidates if c.status == CandidateStatus.SIMILAR),
            sum(1 for c in candidates if c.status == CandidateStatus.UNCERTAIN),
            skipped_low_confidence,
        )
        return candidates

    def _build_pending(
        self,
        item: VLMResultItem,
        card_detail: dict[str, VLMCandidateCard],
        image_id: str,
    ) -> PendingCandidate:
        """从单个 VLMResultItem 构建 PendingCandidate"""
        pc = PendingCandidate(
            term=item.card,
            original_text=item.original_text,
            image_id=image_id,
            bbox=item.bbox,
            bbox_confidence=item.bbox_confidence,
        )

        # 优先用 VLM 给出的 card_id 找已有卡片
        matched: Optional[Card] = None
        if item.card_id:
            matched = self._kb.get_card(item.card_id)
        if matched is None:
            matched = self._kb.find_by_term(item.card)

        if matched is not None:
            # 判断是否熟悉
            if matched.familiarity >= _FAMILIAR_THRESHOLD:
                pc.status = CandidateStatus.FAMILIAR
            else:
                pc.status = CandidateStatus.EXISTING
            pc.matched_card = matched
        else:
            # VLM 标注的状态 EXISTING/FAMILIAR 但 KB 中没找到 → 降级为 NEW
            if item.status in (CandidateStatus.EXISTING, CandidateStatus.FAMILIAR):
                logger.debug(
                    "VLM 标注 %s 为 %s，但 KB 中未找到，降级为 NEW",
                    item.card, item.status.value,
                )
                pc.status = CandidateStatus.NEW
            else:
                pc.status = item.status  # NEW / UNCERTAIN

            # 尝试找相似词条
            similar = self._find_similar_card(item.card)
            if similar is not None:
                pc.status = CandidateStatus.SIMILAR
                pc.matched_card = similar

        # 填充 VLMCandidateCard 详情（只对 NEW / UNCERTAIN / SIMILAR 有意义）
        detail = card_detail.get(item.card)
        if detail:
            pc.card_summary       = detail.card_summary
            pc.model_content      = detail.model_content
            pc.familiarity_suggestion = detail.familiarity_suggestion
            pc.suggested_links    = [lk.to_link() for lk in detail.links]
            pc.related_terms      = list(detail.related_terms)

        return pc

    def _find_similar_card(self, term: str) -> Optional[Card]:
        """在 KB 中查找与 term 相似度超过阈值的卡片（返回最相似的一张）"""
        best_card: Optional[Card] = None
        best_score = _SIMILAR_MIN_RATIO

        for card in self._kb.all_cards():
            score = _term_similarity(term, card.term)
            if score > best_score:
                best_score = score
                best_card = card

        return best_card

    # ------------------------------------------------------------------
    # 查询当前候选列表
    # ------------------------------------------------------------------

    def all_pending(self) -> list[PendingCandidate]:
        """返回所有待处理候选（已确认 / 已忽略的也在列表中，供 UI 展示）"""
        return list(self._pending.values())

    def get(self, candidate_id: str) -> Optional[PendingCandidate]:
        return self._pending.get(candidate_id)

    def pending_new(self) -> list[PendingCandidate]:
        """仅返回 NEW 状态的候选（等待确认的）"""
        return [c for c in self._pending.values() if c.status == CandidateStatus.NEW]

    # ------------------------------------------------------------------
    # 用户操作：确认
    # ------------------------------------------------------------------

    def confirm(
        self,
        candidate_id: str,
        edits: Optional[dict] = None,
    ) -> Card:
        """
        确认候选卡片，创建新 Card 并入库。

        edits 可以覆盖字段，例如::

            edits = {"term": "Carbonara", "familiarity": 2, "user_note": "..."}

        如果候选状态是 EXISTING，则更新已有 Card（追加 image_id）。
        """
        pc = self._pending.get(candidate_id)
        if pc is None:
            raise KeyError(f"候选 {candidate_id!r} 不存在")

        edits = edits or {}

        if pc.status == CandidateStatus.CONFIRMED and pc.matched_card is not None:
            return pc.matched_card

        if pc.status in (CandidateStatus.EXISTING, CandidateStatus.FAMILIAR) and pc.matched_card is not None:
            card = self._update_existing(pc, edits)
        else:
            card = self._create_new(pc, edits)

        pc.status = CandidateStatus.CONFIRMED
        pc.matched_card = card
        logger.info("confirm: %s → card.id=%s", pc.term, card.id)
        return card

    def _create_new(self, pc: PendingCandidate, edits: dict) -> Card:
        """从候选创建全新 Card"""
        card = Card(
            term           = edits.get("term", pc.term),
            category       = edits.get("category", ""),
            summary        = edits.get("summary", pc.card_summary),
            model_note     = edits.get("model_note", pc.model_content),
            user_note      = edits.get("user_note", ""),
            links          = edits.get("links", list(pc.suggested_links)),
            familiarity    = edits.get("familiarity", pc.familiarity_suggestion),
            source_image_ids = [pc.image_id] if pc.image_id else [],
        )

        self._kb.add_card(card)
        self._repo.save_card(card)

        # 追加到 SourceImage.card_ids
        self._bind_image(card.id, pc.image_id)

        return card

    def _update_existing(self, pc: PendingCandidate, edits: dict) -> Card:
        """更新已有 Card（主要是追加 image_id）"""
        card = pc.matched_card
        assert card is not None

        # 追加来源图片（去重）
        if pc.image_id and pc.image_id not in card.source_image_ids:
            card.source_image_ids.append(pc.image_id)

        # 应用用户手动编辑（不覆盖已有 user_note）
        if "user_note" in edits and edits["user_note"]:
            card.user_note = edits["user_note"]
        if "familiarity" in edits:
            card.familiarity = max(0, min(5, edits["familiarity"]))

        card.updated_at = datetime.now()
        self._repo.save_card(card)
        self._bind_image(card.id, pc.image_id)

        return card

    def _bind_image(self, card_id: str, image_id: str) -> None:
        """将 card_id 追加到 SourceImage.card_ids 并持久化"""
        if not image_id:
            return
        image = self._kb.get_image(image_id)
        if image and card_id not in image.card_ids:
            image.card_ids.append(card_id)
            self._repo.save_image(image)

    # ------------------------------------------------------------------
    # 用户操作：忽略
    # ------------------------------------------------------------------

    def ignore(self, candidate_id: str) -> None:
        """将候选标记为 IGNORED（不删除，UI 仍可展示但变灰）"""
        pc = self._pending.get(candidate_id)
        if pc is None:
            raise KeyError(f"候选 {candidate_id!r} 不存在")
        pc.status = CandidateStatus.IGNORED
        logger.debug("ignore: %s", pc.term)

    # ------------------------------------------------------------------
    # 用户操作：合并到已有卡片
    # ------------------------------------------------------------------

    def merge_into(
        self,
        candidate_id: str,
        target_card_id: str,
        edits: Optional[dict] = None,
    ) -> Card:
        """
        将候选卡片合并到已有 Card。
        - 追加 model_content 到 card.model_note（如果比原来更丰富）
        - 追加来源图片
        - 合并 links（去重）
        """
        pc = self._pending.get(candidate_id)
        if pc is None:
            raise KeyError(f"候选 {candidate_id!r} 不存在")

        card = self._kb.get_card(target_card_id)
        if card is None:
            raise KeyError(f"目标卡片 {target_card_id!r} 不存在")

        edits = edits or {}

        # 合并 model_note
        if pc.model_content and pc.model_content not in card.model_note:
            card.model_note = (card.model_note + "\n\n" + pc.model_content).strip()

        # 合并 links（去重）
        existing_urls = {lk.url for lk in card.links}
        for lk in pc.suggested_links:
            if lk.url not in existing_urls:
                card.links.append(lk)
                existing_urls.add(lk.url)

        # 追加来源图片
        if pc.image_id and pc.image_id not in card.source_image_ids:
            card.source_image_ids.append(pc.image_id)

        # 应用用户编辑
        if "user_note" in edits and edits["user_note"]:
            card.user_note = edits["user_note"]

        card.updated_at = datetime.now()
        self._repo.save_card(card)
        self._bind_image(card.id, pc.image_id)

        # 标记候选为已处理
        pc.status = CandidateStatus.CONFIRMED
        pc.matched_card = card

        logger.info("merge_into: %s → card.id=%s (%s)", pc.term, card.id, card.term)
        return card

    # ------------------------------------------------------------------
    # 批量操作
    # ------------------------------------------------------------------

    def confirm_all_new(self, edits_map: Optional[dict[str, dict]] = None) -> list[Card]:
        """
        批量确认所有 NEW 状态的候选（跳过 IGNORED / FAMILIAR）。
        edits_map: {candidate_id: edits_dict}，可以为 None（使用默认值）。
        """
        edits_map = edits_map or {}
        cards = []
        for pc in list(self._pending.values()):
            if pc.status != CandidateStatus.NEW:
                continue
            try:
                card = self.confirm(pc.id, edits_map.get(pc.id, {}))
                cards.append(card)
            except Exception as exc:
                logger.warning("confirm_all_new: 跳过 %s，错误：%s", pc.term, exc)
        logger.info("confirm_all_new: 共确认 %d 张卡片", len(cards))
        return cards

    def auto_link_confirmed(self, confirmed_card_ids: list[str]) -> int:
        """
        为本次分析中已确认的卡片自动建立 APPEARS_WITH 关系。
        返回新增边数。
        """
        count = 0
        ids = confirmed_card_ids
        for i, id_a in enumerate(ids):
            card_a = self._kb.get_card(id_a)
            if card_a is None:
                continue
            for id_b in ids[i + 1:]:
                card_b = self._kb.get_card(id_b)
                if card_b is None:
                    continue
                # 双向添加（add_edge 内部会去重）
                before = len(card_a.edges)
                card_a.add_edge(id_b, RelationType.APPEARS_WITH, weight=0.5, created_by="system")
                card_b.add_edge(id_a, RelationType.APPEARS_WITH, weight=0.5, created_by="system")
                if len(card_a.edges) > before:
                    count += 1
                    self._repo.save_card(card_a)
                    self._repo.save_card(card_b)

        logger.info("auto_link_confirmed: 新增 %d 条 APPEARS_WITH 边", count)
        return count
