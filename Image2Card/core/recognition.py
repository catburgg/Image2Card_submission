from __future__ import annotations

from dataclass.models import AnalyzeResult, CandidateStatus, VLMResultItem

RECOGNITION_CONFIDENCE_THRESHOLD = 0.95


def is_high_confidence_recognition(item: VLMResultItem) -> bool:
    return (
        item.bbox is not None
        and item.bbox_confidence >= RECOGNITION_CONFIDENCE_THRESHOLD
    )


def filter_high_confidence_result(result: AnalyzeResult) -> AnalyzeResult:
    """Drop low-confidence recognitions before they enter UI or persistence."""
    items = [item for item in result.items if is_high_confidence_recognition(item)]
    card_names = {
        item.card
        for item in items
        if item.status in (CandidateStatus.NEW, CandidateStatus.UNCERTAIN)
    }

    result.items = items
    result.cards = [card for card in result.cards if card.card in card_names]
    return result
