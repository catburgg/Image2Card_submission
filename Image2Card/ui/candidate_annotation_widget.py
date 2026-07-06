from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from core.candidate import PendingCandidate
from dataclass.models import CandidateStatus
from core.recognition import RECOGNITION_CONFIDENCE_THRESHOLD


_STATUS_COLOR: dict[CandidateStatus, QColor] = {
    CandidateStatus.NEW: QColor("#ff9800"),
    CandidateStatus.EXISTING: QColor("#4a90d9"),
    CandidateStatus.FAMILIAR: QColor("#8f8fa3"),
    CandidateStatus.SIMILAR: QColor("#1abc9c"),
    CandidateStatus.IGNORED: QColor("#6f6f80"),
    CandidateStatus.UNCERTAIN: QColor("#f1c40f"),
    CandidateStatus.CONFIRMED: QColor("#4caf50"),
}

MIN_BBOX_CONFIDENCE = RECOGNITION_CONFIDENCE_THRESHOLD


class _CandidateMarkerItem(QGraphicsRectItem):
    def __init__(
        self,
        candidate: PendingCandidate,
        number: int,
        on_hover,
        on_click,
    ) -> None:
        bbox = candidate.bbox
        x1 = float(bbox.x1)
        y1 = float(bbox.y1)
        x2 = float(bbox.x2)
        y2 = float(bbox.y2)
        super().__init__(x1, y1, max(1.0, x2 - x1), max(1.0, y2 - y1))

        self.candidate_id = candidate.id
        self._candidate = candidate
        self._on_hover = on_hover
        self._on_click = on_click
        self._color = _STATUS_COLOR.get(candidate.status, QColor("#ff9800"))

        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self._normal_pen = QPen(self._color, 2)
        self._active_pen = QPen(QColor("#ffffff"), 3)
        fill = QColor(self._color)
        fill.setAlpha(34)
        self._normal_brush = QBrush(fill)
        active_fill = QColor(self._color)
        active_fill.setAlpha(86)
        self._active_brush = QBrush(active_fill)

        self.setPen(self._normal_pen)
        self.setBrush(self._normal_brush)

        badge_size = 26
        self._badge = QGraphicsEllipseItem(0, 0, badge_size, badge_size, self)
        self._badge.setPos(-badge_size * 0.45, -badge_size * 0.45)
        self._badge.setPen(QPen(QColor("#ffffff"), 1.4))
        self._badge.setBrush(QBrush(self._color))

        self._label = QGraphicsSimpleTextItem(str(number), self._badge)
        font = QFont("Arial", 10, QFont.Bold)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor("#ffffff")))
        rect = self._label.boundingRect()
        self._label.setPos(
            (badge_size - rect.width()) / 2,
            (badge_size - rect.height()) / 2 - 1,
        )

    def set_highlighted(self, active: bool) -> None:
        self.setPen(self._active_pen if active else self._normal_pen)
        self.setBrush(self._active_brush if active else self._normal_brush)
        self.setZValue(10 if active else 0)
        self._badge.setScale(1.12 if active else 1.0)

    def hoverEnterEvent(self, event) -> None:
        self.set_highlighted(True)
        self._on_hover(self.candidate_id, True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.set_highlighted(False)
        self._on_hover(self.candidate_id, False)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._on_click(self.candidate_id)
        super().mousePressEvent(event)


class CandidateAnnotationView(QGraphicsView):
    candidate_hovered = pyqtSignal(str, bool)
    candidate_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#181824")))
        self._markers: dict[str, _CandidateMarkerItem] = {}
        self._image_path = ""

    def load_candidates(
        self,
        image_path: str,
        candidates: list[PendingCandidate],
    ) -> None:
        self._image_path = image_path
        self._markers.clear()
        self._scene.clear()

        if not image_path:
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            return

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            return

        self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))

        marker_number = 1
        for candidate in candidates:
            confidence = getattr(candidate, "bbox_confidence", 0.0)
            if candidate.bbox is None or confidence < MIN_BBOX_CONFIDENCE:
                continue
            marker = _CandidateMarkerItem(
                candidate,
                marker_number,
                self._on_marker_hovered,
                self._on_marker_clicked,
            )
            self._markers[candidate.id] = marker
            self._scene.addItem(marker)
            marker_number += 1

        self._fit()

    def highlight_candidate(self, candidate_id: str) -> None:
        for marker_id, marker in self._markers.items():
            marker.set_highlighted(marker_id == candidate_id)

    def clear_highlight(self) -> None:
        for marker in self._markers.values():
            marker.set_highlighted(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    def _fit(self) -> None:
        if not self._scene.items():
            return
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _on_marker_hovered(self, candidate_id: str, active: bool) -> None:
        if active:
            self.highlight_candidate(candidate_id)
        self.candidate_hovered.emit(candidate_id, active)

    def _on_marker_clicked(self, candidate_id: str) -> None:
        self.highlight_candidate(candidate_id)
        self.candidate_clicked.emit(candidate_id)
