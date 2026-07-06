"""
CardGridView — 卡片网格视图控件

按复习日期分组显示卡片，日期之间用分隔线隔开。
每组内部卡片流式排列，仅显示词条名。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dataclass.models import Card


class _CardTile(QFrame):
    """极简卡片瓷砖，仅显示词条名。"""

    clicked = pyqtSignal(str)

    def __init__(self, card: Card, is_selected: bool = False) -> None:
        super().__init__()
        self._card_id = card.id
        self.setObjectName("cardTile")
        self._update_style(is_selected)

        label = QLabel(card.term or "(未命名)")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.addWidget(label)

        # 固定大小防止选中时 border/font-weight 变化导致排版跳动
        self.setFixedSize(184, 64)
        self.setCursor(Qt.PointingHandCursor)

    def _update_style(self, is_selected: bool) -> None:
        if is_selected:
            self.setStyleSheet(
                "QFrame#cardTile { background: #7c6df0; border-radius: 8px; border: 1px solid #9180f4; }"
                "QLabel { color: white; font-weight: bold; background: transparent; }"
            )
        else:
            self.setStyleSheet(
                "QFrame#cardTile { background: #2e2e45; border-radius: 8px; border: 1px solid #44445a; }"
                "QFrame#cardTile:hover { background: #383855; border-color: #57558a; }"
                "QLabel { color: #e8e8f0; background: transparent; }"
            )

    def sizeHint(self) -> QSize:
        # 基于文字内容建议大小
        hint = super().sizeHint()
        return QSize(max(hint.width(), 160), max(hint.height(), 60))

    def set_selected(self, selected: bool) -> None:
        self._update_style(selected)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._card_id)


class CardGridView(QWidget):
    """简洁的卡片列表网格，不再展示复习进度。"""

    card_selected = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._selected_card_id: Optional[str] = None
        self._tiles: dict[str, _CardTile] = {}

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._content.setObjectName("gridContent")
        self._content.setStyleSheet("QWidget#gridContent { background: transparent; }")
        
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(20, 20, 20, 20)
        self._grid.setSpacing(12)
        self._grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._scroll.setWidget(self._content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._scroll)

    def load_cards(self, cards: list[Card], selected_card_id: Optional[str] = None) -> None:
        # 清理
        for tile in self._tiles.values():
            try: tile.clicked.disconnect()
            except: pass
        self._tiles.clear()

        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 按字母顺序排列，移除日期分组
        sorted_cards = sorted(cards, key=lambda c: c.term or "")

        cols = 4 # 根据新的宽度调整列数
        for idx, card in enumerate(sorted_cards):
            is_selected = card.id == selected_card_id
            tile = _CardTile(card, is_selected)
            tile.clicked.connect(self._on_tile_clicked)
            self._grid.addWidget(tile, idx // cols, idx % cols)
            self._tiles[card.id] = tile

        self._selected_card_id = selected_card_id

    def select_card(self, card_id: Optional[str]) -> None:
        if self._selected_card_id and self._selected_card_id in self._tiles:
            self._tiles[self._selected_card_id].set_selected(False)
        if card_id and card_id in self._tiles:
            self._selected_card_id = card_id
            self._tiles[card_id].set_selected(True)
        else:
            self._selected_card_id = None

    def _on_tile_clicked(self, card_id: str) -> None:
        self.select_card(card_id)
        self.card_selected.emit(card_id)

        self._main_layout.addStretch(1)
        self._selected_card_id = selected_card_id

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def select_card(self, card_id: Optional[str]) -> None:
        if self._selected_card_id and self._selected_card_id in self._tiles:
            self._tiles[self._selected_card_id].set_selected(False)
        if card_id and card_id in self._tiles:
            self._selected_card_id = card_id
            self._tiles[card_id].set_selected(True)
        else:
            self._selected_card_id = None

    def _on_tile_clicked(self, card_id: str) -> None:
        self.select_card(card_id)
        self.card_selected.emit(card_id)

    def select_card(self, card_id: Optional[str]) -> None:
        if self._selected_card_id and self._selected_card_id in self._tiles:
            self._tiles[self._selected_card_id].set_selected(False)
        if card_id and card_id in self._tiles:
            self._selected_card_id = card_id
            self._tiles[card_id].set_selected(True)
        else:
            self._selected_card_id = None

    def _on_tile_clicked(self, card_id: str) -> None:
        self.select_card(card_id)
        self.card_selected.emit(card_id)
