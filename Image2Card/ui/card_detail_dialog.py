"""
CardDetailDialog — 卡片详情编辑对话框

允许用户查看和编辑一张 Card 的所有字段。
全部内容在单个可滚动区域内，次要字段用可折叠区块收纳。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFont, QPixmap
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dataclass.models import Card, KnowledgeBase, Link, SourceImage
from core.card_manager import CardManager
from ui.styles import (
    ACCENT, BG_CARD, BG_INPUT, BG_PANEL, BORDER,
    DANGER, FAM_COLORS, TEXT_PRI, TEXT_SEC,
)

logger = logging.getLogger("image2card.ui.card_detail")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _auto_resize_te(te: QTextEdit) -> None:
    """根据 QTextEdit 文档内容自动调整高度。"""
    doc = te.document()
    doc.setTextWidth(te.viewport().width())
    h = doc.size().height() + te.contentsMargins().top() + te.contentsMargins().bottom() + 8
    te.setFixedHeight(max(40, min(int(h), 500)))


# ---------------------------------------------------------------------------
# 可折叠区块（类似 <details><summary>）
# ---------------------------------------------------------------------------
class CollapsibleSection(QWidget):
    """带标题栏的可折叠区块，点击箭头切换展开/收起。"""

    ARROW_DOWN = "▾"
    ARROW_RIGHT = "▸"

    def __init__(
        self,
        title: str,
        content: QWidget,
        collapsed: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._content = content
        self._collapsed = collapsed
        self._title_value = title

        self.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 可点击的标题栏
        self._header = QPushButton()
        self._header.setFlat(True)
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setStyleSheet(
            f"QPushButton {{ color:{TEXT_SEC}; font-weight:bold; font-size:10pt; "
            f"text-align:left; padding:6px 0; background:transparent; border:none; }}"
            f"QPushButton:hover {{ color:{TEXT_PRI}; }}"
        )
        self._header.clicked.connect(self._toggle)
        root.addWidget(self._header)

        # 内容区
        self._content.setParent(self)
        root.addWidget(self._content)

        self._update_display()

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._update_display()

    def _update_display(self) -> None:
        arrow = self.ARROW_RIGHT if self._collapsed else self.ARROW_DOWN
        self._header.setText(f"{arrow} {self._title_value}")
        self._content.setVisible(not self._collapsed)

    def set_title(self, title: str) -> None:
        self._title_value = title
        self._update_display()


class CardDetailDialog(QDialog):
    """
    卡片详情编辑对话框（模态）。

    用法::

        dlg = CardDetailDialog(card, ctx.card_mgr, parent=self)
        dlg.exec_()   # 保存由 dialog 内部自动完成
    """

    card_saved = pyqtSignal(object)  # 发射修改后的 Card

    def __init__(
        self,
        card: Card,
        card_mgr: CardManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._card     = card
        self._card_mgr = card_mgr
        self._kb       = card_mgr.kb

        self.setWindowTitle(f"卡片详情 — {card.term}")
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background:{BG_PANEL}; }}"
        )
        # 初始大小较大，后续 showEvent 会最大化
        self.resize(800, 700)

        self._build_ui()
        self._populate()

    # ──────────────────────────────────────────────────────────────────
    # 构建 UI：单个可滚动区域 + 底部按钮
    # ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 滚动区（装全部内容）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background:{BG_PANEL}; border:none; }}")

        content = QWidget()
        self._lay = QVBoxLayout(content)
        self._lay.setContentsMargins(28, 20, 28, 20)
        self._lay.setSpacing(14)
        scroll.setWidget(content)

        root.addWidget(scroll, 1)

        # 底部按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.setStyleSheet(
            f"QDialogButtonBox {{ background:{BG_CARD}; padding:8px 20px; "
            f"border-top:1px solid {BORDER}; }}"
        )
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    def showEvent(self, event) -> None:
        """打开时最大化。"""
        super().showEvent(event)
        self.showMaximized()

    # ──────────────────────────────────────────────────────────────────
    # 填充内容
    # ──────────────────────────────────────────────────────────────────

    def _populate(self) -> None:
        lay = self._lay
        card = self._card

        # ── 标题行 ──
        title_row = QHBoxLayout()
        self._term_edit = QLineEdit(card.term)
        self._term_edit.setFont(QFont("Arial", 18, QFont.Bold))
        self._term_edit.setStyleSheet(
            f"background:transparent; border:none; color:{TEXT_PRI};"
        )
        title_row.addWidget(self._term_edit, 1)

        self._fam_label_header = QLabel()
        title_row.addWidget(self._fam_label_header)
        lay.addLayout(title_row)

        self._fam_val = card.familiarity
        self._update_fam_header(self._fam_val)

        # ── 分隔线 ──
        lay.addWidget(self._make_sep())

        # ── 工作区 + 熟悉度（同行） ──
        meta_row = QHBoxLayout()
        meta_row.setSpacing(20)

        # 工作区
        cat_col = QVBoxLayout()
        cat_col.setSpacing(4)
        cat_col.addWidget(self._section_label("工作区"))
        self._cat_combo = QComboBox()
        self._refresh_categories(card.category)
        cat_col.addWidget(self._cat_combo)
        meta_row.addLayout(cat_col)

        # 熟悉度
        fam_col = QVBoxLayout()
        fam_col.setSpacing(4)
        fam_col.addWidget(self._section_label("熟悉度"))
        fam_btn_row = QHBoxLayout()
        self._fam_spin = QSpinBox()
        self._fam_spin.setRange(0, 5)
        self._fam_spin.setValue(self._fam_val)
        self._fam_spin.setFixedWidth(80)
        self._fam_spin.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        self._fam_spin.valueChanged.connect(self._on_fam_spin)
        self._fam_val_lbl = QLabel(self._fam_text(card.familiarity))
        fam_btn_row.addWidget(self._fam_spin)
        fam_btn_row.addWidget(self._fam_val_lbl)
        fam_btn_row.addStretch()
        fam_col.addLayout(fam_btn_row)
        meta_row.addLayout(fam_col, 1)
        meta_row.addStretch()
        lay.addLayout(meta_row)

        # ── 分隔线 ──
        lay.addWidget(self._make_sep())

        # ── 折叠：模型简介（默认展开） ──
        sum_w = QWidget()
        sum_l = QVBoxLayout(sum_w)
        sum_l.setContentsMargins(0, 0, 0, 0)
        self._summary_edit = self._make_expanding_text_edit(card.summary)
        self._summary_edit.setPlaceholderText("由 VLM 自动生成的一句话简介")
        sum_l.addWidget(self._summary_edit)
        lay.addWidget(CollapsibleSection("模型简介", sum_w, collapsed=False))

        # ── 折叠：模型解释（默认展开） ──
        note_w = QWidget()
        nl = QVBoxLayout(note_w)
        nl.setContentsMargins(0, 0, 0, 0)
        self._model_note_edit = self._make_expanding_text_edit(card.model_note)
        nl.addWidget(self._model_note_edit)
        lay.addWidget(CollapsibleSection("模型解释", note_w, collapsed=False))

        # ── 折叠：用户笔记（默认展开） ──
        user_w = QWidget()
        ul = QVBoxLayout(user_w)
        ul.setContentsMargins(0, 0, 0, 0)
        self._user_note_edit = self._make_expanding_text_edit(card.user_note)
        self._user_note_edit.setPlaceholderText("记录自己的理解、记忆方法或课堂备注…")
        ul.addWidget(self._user_note_edit)
        lay.addWidget(CollapsibleSection("我的笔记", user_w, collapsed=False))

        # ── 分隔线 ──
        lay.addWidget(self._make_sep())

        # ── 折叠：复习统计 ──
        review_content = QWidget()
        rl = QVBoxLayout(review_content)
        rl.setContentsMargins(0, 4, 0, 0)
        rl.setSpacing(6)
        rl.addWidget(QLabel(f"已复习 {card.review_count} 次 · 遗忘 {card.lapses} 次"))
        rl.addWidget(QLabel(
            f"稳定性 {card.stability:.1f} 天 · 难度 {card.difficulty:.1f}"
        ))
        if card.last_reviewed_at:
            rl.addWidget(QLabel(f"上次复习 {card.last_reviewed_at.strftime('%Y-%m-%d %H:%M')}"))
        else:
            rl.addWidget(QLabel("从未复习"))
        if card.next_due:
            rl.addWidget(QLabel(f"下次到期 {card.next_due.isoformat()}"))
        else:
            rl.addWidget(QLabel("尚未安排复习"))
        rs = CollapsibleSection("复习统计", review_content, collapsed=True)
        lay.addWidget(rs)

        # ── 折叠：外部链接 ──
        links_content = QWidget()
        ll = QVBoxLayout(links_content)
        ll.setContentsMargins(0, 4, 0, 0)
        ll.setSpacing(6)
        self._links_list = QListWidget()
        self._links_list.setMaximumHeight(120)
        for lk in card.links:
            self._links_list.addItem(f"{lk.title}  |  {lk.url}")
        link_btn_row = QHBoxLayout()
        add_link_btn = QPushButton("＋ 添加链接")
        del_link_btn = QPushButton("删除选中")
        del_link_btn.setStyleSheet(f"color:{DANGER};")
        add_link_btn.clicked.connect(self._add_link)
        del_link_btn.clicked.connect(self._del_link)
        link_btn_row.addWidget(add_link_btn)
        link_btn_row.addWidget(del_link_btn)
        link_btn_row.addStretch()
        ll.addWidget(self._links_list)
        ll.addLayout(link_btn_row)
        ls = CollapsibleSection("外部链接", links_content, collapsed=True)
        lay.addWidget(ls)

        # ── 折叠：来源图片 ──
        sources_content = QWidget()
        sl = QVBoxLayout(sources_content)
        sl.setContentsMargins(0, 4, 0, 0)
        sl.setSpacing(8)
        
        for img_id in card.source_image_ids:
            img: Optional[SourceImage] = self._kb.get_image(img_id)
            if img is None:
                continue
            img_frame = QFrame()
            img_frame.setObjectName("card_frame")
            img_frame.setCursor(Qt.PointingHandCursor)
            img_frame.mousePressEvent = lambda event, path=img.file_path: self._open_image(path)
            img_frame.setStyleSheet(
                f"QFrame#card_frame {{ background:{BG_CARD}; border:1px solid {BORDER}; "
                f"border-radius:6px; padding:6px; }}"
            )
            ilay = QVBoxLayout(img_frame)
            ilay.setContentsMargins(8, 8, 8, 8)
            ilay.setSpacing(4)

            thumb = QLabel()
            pix = QPixmap(img.file_path)
            if not pix.isNull():
                thumb.setPixmap(pix.scaled(260, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                thumb.setText("[图片不可用]")
                thumb.setStyleSheet(f"color:{TEXT_SEC};")
            thumb.setToolTip(f"点击打开原图\n{img.file_path}")
            ilay.addWidget(thumb)

            name_lbl = QLabel(img.title or img.file_path.split("/")[-1].split("\\")[-1])
            name_lbl.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
            name_lbl.setWordWrap(True)
            name_lbl.setToolTip(f"点击打开原图\n{img.file_path}")
            ilay.addWidget(name_lbl)
            sl.addWidget(img_frame)

        if not card.source_image_ids:
            sl.addWidget(QLabel("暂无来源图片"))

        # 相关卡片（也折叠在来源图片下面）
        sl.addWidget(self._section_label("相关卡片"))
        for edge in card.edges:
            related = self._kb.get_card(edge.to_card_id)
            if related is None:
                continue
            chip = QLabel(f"  {related.term}  ")
            chip.setStyleSheet(
                f"background:{BG_INPUT}; color:{ACCENT}; padding:4px 10px;"
                f"border-radius:12px; font-size:12px;"
            )
            chip.setCursor(Qt.PointingHandCursor)
            sl.addWidget(chip)
        if not card.edges:
            sl.addWidget(QLabel("暂无关联卡片"))

        ss = CollapsibleSection("来源图片与关联", sources_content, collapsed=True)
        lay.addWidget(ss)

        # 底部弹簧
        lay.addStretch()

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def _on_fam_spin(self, val: int) -> None:
        self._fam_val = val
        self._fam_val_lbl.setText(self._fam_text(val))
        self._update_fam_header(val)

    def _open_image(self, path: str) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", f"无法打开图片：{path}")

    def _update_fam_header(self, val: int) -> None:
        stars = "★" * val + "☆" * (5 - val)
        color = FAM_COLORS[val]
        self._fam_label_header.setText(stars)
        self._fam_label_header.setStyleSheet(f"color:{color}; font-size:16px;")

    def _add_link(self) -> None:
        from PyQt5.QtWidgets import QInputDialog
        title, ok1 = QInputDialog.getText(self, "添加链接", "链接标题：")
        if not ok1 or not title.strip():
            return
        url, ok2 = QInputDialog.getText(self, "添加链接", "链接 URL：")
        if not ok2 or not url.strip():
            return
        self._links_list.addItem(f"{title.strip()}  |  {url.strip()}")

    def _del_link(self) -> None:
        for item in self._links_list.selectedItems():
            self._links_list.takeItem(self._links_list.row(item))

    def _on_save(self) -> None:
        card = self._card
        card.term        = self._term_edit.text().strip() or card.term
        card.category    = self._selected_category()
        card.familiarity = self._fam_val
        card.summary     = self._summary_edit.toPlainText().strip()
        card.model_note  = self._model_note_edit.toPlainText().strip()
        card.user_note   = self._user_note_edit.toPlainText().strip()
        card.updated_at  = datetime.now()

        # 链接
        links = []
        for i in range(self._links_list.count()):
            text = self._links_list.item(i).text()
            if "|" in text:
                parts = text.split("|", 1)
                links.append(Link(title=parts[0].strip(), url=parts[1].strip()))
        card.links = links

        # 通过 CardManager 同步更新内存 + 数据库
        self._card_mgr.update(card)
        self.card_saved.emit(card)
        self.accept()

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _make_expanding_text_edit(text: str = "") -> QTextEdit:
        """无内部滚动条、随内容自动撑高的 QTextEdit。"""
        te = QTextEdit(text)
        te.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        te.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        te.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        te.document().contentsChanged.connect(lambda: _auto_resize_te(te))
        return te

    @staticmethod
    def _make_sep() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{BORDER}; max-height:1px;")
        return sep

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{TEXT_SEC}; font-size:11px; font-weight:bold;"
            "text-transform:uppercase; letter-spacing:1px;"
        )
        return lbl

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{TEXT_SEC}; font-size:12px;")
        return lbl

    def _refresh_categories(self, current: str) -> None:
        self._cat_combo.clear()
        self._cat_combo.addItem("未分类", "")
        names = self._kb.category_names()
        for name in names:
            self._cat_combo.addItem(name, name)
        if current and current not in names:
            self._cat_combo.addItem(current, current)
        idx = self._cat_combo.findData(current)
        self._cat_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _selected_category(self) -> str:
        data = self._cat_combo.currentData()
        return str(data or "").strip()

    @staticmethod
    def _fam_text(val: int) -> str:
        labels = ["完全陌生", "很陌生", "模糊", "大致了解", "熟悉", "完全掌握"]
        return f"{val}/5  {labels[val]}"
