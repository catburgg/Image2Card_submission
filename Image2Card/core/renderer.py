"""
ImageRenderer：图片标注可交互渲染器

组件结构：
    ImageRenderer (QWidget)
    ├── AnnotatedImageView (QGraphicsView)   左侧：带标注覆盖层的图片
    │   └── QGraphicsScene
    │       ├── QGraphicsPixmapItem          原始图片（scene 坐标 = 像素坐标）
    │       └── BBoxItem ×N                  每个词条的 bbox 覆盖层
    └── CardDetailPanel (QFrame)            右侧：点击后展示的卡片详情

    CardThumbnailPopup (QWidget/ToolTip)    悬停时浮出的缩略卡片

公共接口：
    renderer = ImageRenderer(parent=None)
    renderer.render(image_path: str, result: AnalyzeResult) -> None
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt5.QtCore import Qt, QRectF, QUrl, QPoint
from PyQt5.QtGui import (
    QBrush, QColor, QCursor, QDesktopServices, QFont, QPainter, QPen, QPixmap,
)
from PyQt5.QtWidgets import (
    QApplication, QFrame, QGraphicsItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from dataclass.models import AnalyzeResult, CandidateStatus, VLMCandidateCard, VLMResultItem


# ---------------------------------------------------------------------------
# 状态颜色 / 标签映射
# ---------------------------------------------------------------------------

_STATUS_COLOR: dict[CandidateStatus, QColor] = {
    CandidateStatus.NEW:       QColor(255, 140,   0),  # 橙
    CandidateStatus.EXISTING:  QColor( 30, 130, 255),  # 蓝
    CandidateStatus.FAMILIAR:  QColor(140, 140, 140),  # 灰
    CandidateStatus.UNCERTAIN: QColor(210, 180,   0),  # 黄
    CandidateStatus.SIMILAR:   QColor(  0, 180, 100),  # 绿
    CandidateStatus.IGNORED:   QColor(180, 180, 180),  # 浅灰
    CandidateStatus.CONFIRMED: QColor( 76, 175,  80),  # 已确认
}

_STATUS_LABEL: dict[CandidateStatus, str] = {
    CandidateStatus.NEW:       "新词条",
    CandidateStatus.EXISTING:  "已有卡片",
    CandidateStatus.FAMILIAR:  "已熟悉",
    CandidateStatus.UNCERTAIN: "待确认",
    CandidateStatus.SIMILAR:   "相似词条",
    CandidateStatus.IGNORED:   "已忽略",
    CandidateStatus.CONFIRMED: "已加入",
}


# ---------------------------------------------------------------------------
# CardThumbnailPopup — 悬停浮窗
# ---------------------------------------------------------------------------

class CardThumbnailPopup(QWidget):
    """
    鼠标悬停在 BBox 上时弹出的浮动卡片缩略图。
    显示词条名、状态徽章和一句话简介。
    """

    _WIDTH = 260

    def __init__(self) -> None:
        # Qt.ToolTip 使其浮于所有窗口之上；WA_ShowWithoutActivating 避免夺焦
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setFixedWidth(self._WIDTH)

        root = QWidget(self)
        root.setStyleSheet(
            "background:#2b2b2b; border-radius:8px;"
            "border: 1px solid #444;"
        )

        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(4)

        self._term_lbl = QLabel()
        self._term_lbl.setStyleSheet("color:#fff; font-size:14px; font-weight:bold;")
        self._term_lbl.setWordWrap(True)

        self._badge_lbl = QLabel()
        self._badge_lbl.setFixedHeight(20)

        self._summary_lbl = QLabel()
        self._summary_lbl.setStyleSheet("color:#ccc; font-size:12px;")
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setMaximumWidth(self._WIDTH - 24)

        vbox.addWidget(self._term_lbl)
        vbox.addWidget(self._badge_lbl)
        vbox.addWidget(self._summary_lbl)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

    def show_for(
        self,
        item: VLMResultItem,
        card: Optional[VLMCandidateCard],
        global_pos: QPoint,
    ) -> None:
        """填充内容并在 global_pos 附近显示（自动避免超出屏幕边缘）"""
        color = _STATUS_COLOR.get(item.status, QColor(160, 160, 160))
        badge = _STATUS_LABEL.get(item.status, item.status.value)

        self._term_lbl.setText(item.card)
        self._badge_lbl.setText(badge)
        self._badge_lbl.setStyleSheet(
            f"background:{color.name()}; color:white; padding:1px 6px;"
            f"border-radius:3px; font-size:11px;"
        )

        summary = ""
        if card:
            summary = card.card_summary
        elif item.card_id:
            summary = "(已有卡片，点击查看详情)"
        self._summary_lbl.setText(summary)
        self._summary_lbl.setVisible(bool(summary))

        self.adjustSize()

        screen = QApplication.primaryScreen().availableGeometry()
        x = min(global_pos.x() + 16, screen.right()  - self.width()  - 4)
        y = min(global_pos.y() + 16, screen.bottom() - self.height() - 4)
        self.move(x, y)
        self.show()


# ---------------------------------------------------------------------------
# BBoxItem — 单个词条的可交互覆盖层
# ---------------------------------------------------------------------------

class BBoxItem(QGraphicsRectItem):
    """
    图片上的一个可交互 bounding box。

    颜色随词条状态变化；
    hover → 显示 CardThumbnailPopup；
    click → 触发 on_click 回调，通知 ImageRenderer 展开详情面板。
    """

    def __init__(
        self,
        item: VLMResultItem,
        card: Optional[VLMCandidateCard],
        popup: CardThumbnailPopup,
        on_click: Callable[[VLMResultItem, Optional[VLMCandidateCard]], None],
    ) -> None:
        bbox = item.bbox  # 调用前已确认非 None
        w = bbox.x2 - bbox.x1
        h = bbox.y2 - bbox.y1
        super().__init__(bbox.x1, bbox.y1, w, h)

        self._item   = item
        self._card   = card
        self._popup  = popup
        self._on_click = on_click

        color = _STATUS_COLOR.get(item.status, QColor(160, 160, 160))

        self._pen_normal = QPen(color, 1.5)
        self._pen_hover  = QPen(color, 3)

        fill = QColor(color)
        fill.setAlpha(40)
        self.setPen(self._pen_normal)
        self.setBrush(QBrush(fill))

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        # 词条名小标签，贴在 bbox 左上角外侧
        lbl = QGraphicsTextItem(item.card, self)
        font = QFont("Arial", 8, QFont.Bold)
        lbl.setFont(font)
        lbl.setDefaultTextColor(color)
        lbl.setPos(0, -lbl.boundingRect().height())

    # --- 事件处理 ---

    def hoverEnterEvent(self, event) -> None:
        self.setPen(self._pen_hover)
        view       = self.scene().views()[0]
        view_pt    = view.mapFromScene(event.scenePos())
        global_pt  = view.mapToGlobal(view_pt)
        self._popup.show_for(self._item, self._card, global_pt)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.setPen(self._pen_normal)
        self._popup.hide()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._on_click(self._item, self._card)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# AnnotatedImageView — 标注图片视图
# ---------------------------------------------------------------------------

class AnnotatedImageView(QGraphicsView):
    """
    QGraphicsView 子类，加载图片并叠加所有 BBoxItem。

    设计：scene 坐标系 = 原图像素坐标系，view 的变换矩阵负责缩放。
    因此 VLM 返回的 bbox 像素坐标可直接用于 QGraphicsRectItem，无需换算。

    交互：
      - 拖拽平移（ScrollHandDrag）
      - Ctrl + 滚轮 缩放
      - 窗口 resize 时自动重新适配
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setBackgroundBrush(QBrush(QColor(24, 24, 24)))
        self._popup = CardThumbnailPopup()

    def load(
        self,
        image_path: str,
        result: AnalyzeResult,
        on_item_click: Callable[[VLMResultItem, Optional[VLMCandidateCard]], None],
    ) -> None:
        """加载图片并为每个有 bbox 的识别条目创建 BBoxItem。"""
        self._scene.clear()

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            raise FileNotFoundError(f"无法加载图片：{image_path}")
        self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))

        # 新词条的 term → VLMCandidateCard 映射
        card_map: dict[str, VLMCandidateCard] = {c.card: c for c in result.cards}

        for item in result.items:
            if item.bbox is None:
                continue
            card = card_map.get(item.card)
            self._scene.addItem(
                BBoxItem(item, card, self._popup, on_click=on_item_click)
            )

        self._fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def wheelEvent(self, event) -> None:
        """Ctrl + 滚轮 缩放；普通滚轮交给 QGraphicsView 处理（垂直滚动）。"""
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    def _fit(self) -> None:
        if self._scene.items():
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)


# ---------------------------------------------------------------------------
# CardDetailPanel — 右侧卡片详情面板
# ---------------------------------------------------------------------------

class CardDetailPanel(QFrame):
    """
    点击 BBoxItem 后在右侧展示的卡片详情。
    包含：词条名、状态徽章、类型、简介、详解、可点击链接、相关词条标签。
    内容区可滚动。
    """

    _WIDTH = 300

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(self._WIDTH)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background:#fafafa; border-left:1px solid #e0e0e0;")

        # 顶层布局：标题行 + 可滚动内容
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题行
        header = QLabel("卡片详情")
        header.setAlignment(Qt.AlignCenter)
        header.setFixedHeight(36)
        header.setStyleSheet(
            "background:#efefef; color:#555; font-size:12px;"
            "border-bottom:1px solid #ddd;"
        )
        layout.addWidget(header)

        # 可滚动区
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self._scroll)

        # 初始占位符
        self._show_placeholder()

    # --- 公共接口 ---

    def show_card(
        self,
        item: VLMResultItem,
        card: Optional[VLMCandidateCard],
    ) -> None:
        """根据点击的词条条目填充详情内容。"""
        content = QWidget()
        content.setStyleSheet("background:#fafafa;")
        vbox = QVBoxLayout(content)
        vbox.setContentsMargins(16, 16, 16, 20)
        vbox.setSpacing(10)
        vbox.setAlignment(Qt.AlignTop)

        color = _STATUS_COLOR.get(item.status, QColor(160, 160, 160))
        badge_text = _STATUS_LABEL.get(item.status, item.status.value)

        # 词条名
        term_lbl = QLabel(item.card)
        term_lbl.setStyleSheet("font-size:20px; font-weight:bold; color:#1a1a1a;")
        term_lbl.setWordWrap(True)
        vbox.addWidget(term_lbl)

        # 状态徽章 + 类型
        row = QHBoxLayout()
        row.setSpacing(6)
        badge = QLabel(badge_text)
        badge.setFixedHeight(22)
        badge.setStyleSheet(
            f"background:{color.name()}; color:white; padding:1px 8px;"
            f"border-radius:4px; font-size:11px;"
        )
        row.addWidget(badge)
        row.addStretch()
        vbox.addLayout(row)

        # 分割线
        vbox.addWidget(self._make_divider())

        # 简介
        if card and card.card_summary:
            self._add_section(vbox, "简介", card.card_summary, italic=True)

        # 详解
        if card and card.model_content:
            self._add_section(vbox, "详解", card.model_content)

        # 原始文本（仅当与词条名不同时显示）
        if item.original_text and item.original_text != item.card:
            self._add_section(vbox, "图片原文", item.original_text)

        # 链接
        if card and card.links:
            vbox.addWidget(self._make_section_header("外部链接"))
            for lnk in card.links:
                btn = QPushButton(f"↗  {lnk.title}")
                btn.setStyleSheet(
                    "QPushButton{text-align:left; color:#1a73e8; border:none;"
                    "font-size:12px; padding:4px 0; background:transparent;}"
                    "QPushButton:hover{text-decoration:underline;}"
                )
                url = lnk.url
                btn.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
                vbox.addWidget(btn)

        # 相关词条
        if card and card.related_terms:
            vbox.addWidget(self._make_section_header("相关词条"))
            tags_row = QHBoxLayout()
            tags_row.setSpacing(6)
            tags_row.setContentsMargins(0, 0, 0, 0)
            for term in card.related_terms:
                tag = QLabel(term)
                tag.setStyleSheet(
                    "background:#e8f0fe; color:#1a73e8; padding:3px 8px;"
                    "border-radius:4px; font-size:11px;"
                )
                tags_row.addWidget(tag)
            tags_row.addStretch()
            vbox.addLayout(tags_row)

        vbox.addStretch()
        self._scroll.setWidget(content)

    # --- 内部辅助 ---

    def _show_placeholder(self) -> None:
        ph = QLabel("← 点击图片上的词条\n查看卡片详情")
        ph.setAlignment(Qt.AlignCenter)
        ph.setStyleSheet("color:#bbb; font-size:13px;")
        self._scroll.setWidget(ph)

    @staticmethod
    def _make_section_header(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size:11px; font-weight:bold; color:#888;"
            "text-transform:uppercase; letter-spacing:1px;"
        )
        return lbl

    @staticmethod
    def _make_divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#e0e0e0;")
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _add_section(
        layout: QVBoxLayout,
        title: str,
        text: str,
        italic: bool = False,
    ) -> None:
        header = QLabel(title)
        header.setStyleSheet(
            "font-size:11px; font-weight:bold; color:#888;"
            "text-transform:uppercase; letter-spacing:1px;"
        )
        layout.addWidget(header)

        body = QLabel(text)
        body.setWordWrap(True)
        style = "font-size:13px; color:#333; line-height:1.5;"
        if italic:
            style += " font-style:italic;"
        body.setStyleSheet(style)
        layout.addWidget(body)


# ---------------------------------------------------------------------------
# ImageRenderer — 主组件（公共接口）
# ---------------------------------------------------------------------------

class ImageRenderer(QWidget):
    """
    图片标注可交互渲染器，分左右两栏：
      左：AnnotatedImageView（图片 + bbox 覆盖层）
      右：CardDetailPanel（点击后展示的卡片详情）

    用法::

        renderer = ImageRenderer()
        renderer.render(image_path, analyze_result)
        renderer.show()
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image_view   = AnnotatedImageView(self)
        self._detail_panel = CardDetailPanel(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._image_view, stretch=1)
        layout.addWidget(self._detail_panel)

    def render(self, image_path: str, result: AnalyzeResult) -> None:
        """加载图片并绘制所有识别词条的标注覆盖层。"""
        self._image_view.load(image_path, result, self._on_item_click)

    def _on_item_click(
        self,
        item: VLMResultItem,
        card: Optional[VLMCandidateCard],
    ) -> None:
        self._detail_panel.show_card(item, card)
