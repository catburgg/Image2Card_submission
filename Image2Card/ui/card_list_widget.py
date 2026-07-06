"""
CardListView — 卡片列表视图控件

单列列表，每张卡片占多行显示详细信息：词条名 + 简介 + 元数据
用于细粒度浏览和理解卡片内容。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QListWidget, QListWidgetItem

from dataclass.models import Card


def _stars(value: int) -> str:
    value = max(0, min(5, value))
    return "★" * value + "☆" * (5 - value)


def _short(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _review_due_state(card: Card) -> str:
    if card.next_due is None:
        return "待复习"
    today = date.today()
    if card.next_due <= today:
        return "今日到期"
    days = (card.next_due - today).days
    return f"{days} 天后"


from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame

class _CardListItemWidget(QWidget):
    """自定义项小部件，提供正常的文字排版，无重叠，无截断。"""
    def __init__(self, card: Card):
        super().__init__()
        # 使用垂直布局，确保元素从上到下排列
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        # 1. 标题行：大号粗体白字
        self.title = QLabel(card.term or "(未命名)")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-weight: bold;
                background: transparent;
                border: none;
            }
        """)
        # 使用 QFont 相对大小实现缩放
        f = self.title.font()
        f.setPointSize(f.pointSize() + 2)
        self.title.setFont(f)
        layout.addWidget(self.title)

        # 2. 分类行：辅助色
        self.cate = QLabel(card.category or "未分类")
        self.cate.setStyleSheet("""
            QLabel {
                color: #9180f4;
                font-weight: 500;
                background: transparent;
                border: none;
            }
        """)
        layout.addWidget(self.cate)

        # 3. 简介行
        summary_text = card.summary or card.model_note or "暂无详细说明"
        self.content = QLabel(summary_text)
        self.content.setWordWrap(True)
        self.content.setStyleSheet("""
            QLabel {
                color: #a0a0b0;
                background: transparent;
                border: none;
            }
        """)
        layout.addWidget(self.content)

class CardListView(QListWidget):
    """细粒度卡片列表视图，采用标准文档流排版。"""

    card_selected = pyqtSignal(str)   # card_id
    card_double_clicked = pyqtSignal(str)  # card_id

    def __init__(self, parent: Optional[QListWidget] = None) -> None:
        super().__init__(parent)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        self._selected_card_id: Optional[str] = None
        
        # 优化列表基础样式，确保项之间有清晰边界且背景通透
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background: #1e1e2e;
                border-bottom: 1px solid #2d2d3f;
            }
            QListWidget::item:selected {
                background: #2d2d45;
            }
            QListWidget::item:hover {
                background: #252538;
            }
        """)

    def load_cards(self, cards: list[Card], selected_card_id: Optional[str] = None) -> None:
        """加载卡片，使用自适应高度。"""
        self._selected_card_id = None
        self.blockSignals(True)
        self.clear()

        # 按字母排序
        sorted_cards = sorted(cards, key=lambda c: (c.term or ""))

        for card in sorted_cards:
            widget = _CardListItemWidget(card)
            
            item = QListWidgetItem(self)
            item.setData(Qt.UserRole, card.id)
            
            # 关键：使用 widget 的 sizeHint 允许高度根据文字内容动态调整，防止重叠和截断
            item.setSizeHint(widget.sizeHint())
            
            self.addItem(item)
            self.setItemWidget(item, widget)

            if card.id == selected_card_id:
                item.setSelected(True)
                self.setCurrentItem(item)
                self._selected_card_id = card.id

        self.blockSignals(False)
        self._on_selection_changed()

    def select_card(self, card_id: Optional[str]) -> None:
        self.blockSignals(True)
        self._selected_card_id = card_id
        for row in range(self.count()):
            item = self.item(row)
            if item.data(Qt.UserRole) == card_id:
                item.setSelected(True)
                self.setCurrentItem(item)
                self.scrollToItem(item)
                break
        else:
            self.clearSelection()
            self._selected_card_id = None
        self.blockSignals(False)

    def _on_selection_changed(self) -> None:
        item = self.currentItem()
        if item:
            card_id = item.data(Qt.UserRole)
            if card_id and card_id != self._selected_card_id:
                self._selected_card_id = card_id
                self.card_selected.emit(card_id)
        else:
            self._selected_card_id = None

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        card_id = item.data(Qt.UserRole)
        if card_id:
            self.card_double_clicked.emit(card_id)

    def _on_selection_changed(self) -> None:
        item = self.currentItem()
        if item:
            card_id = item.data(Qt.UserRole)
            if card_id and card_id != self._selected_card_id:
                self._selected_card_id = card_id
                self.card_selected.emit(card_id)
        else:
            self._selected_card_id = None

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        card_id = item.data(Qt.UserRole)
        if card_id:
            self.card_double_clicked.emit(card_id)
