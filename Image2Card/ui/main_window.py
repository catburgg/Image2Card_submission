from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QThread, QSize, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.candidate import PendingCandidate
from core.card_chat import ChatTurn
from dataclass.models import CandidateStatus, Card, Link
from ui.app_context import AppContext
from ui.card_detail_dialog import CardDetailDialog, CollapsibleSection
from ui.card_graph_widget import CardGraphWidget
from ui.card_list_widget import CardListView
from ui.card_table_widget import CardGridView
from ui.candidate_annotation_widget import CandidateAnnotationView, MIN_BBOX_CONFIDENCE
from ui.library_page import LibraryPage
from ui.review_session_page import ReviewSessionPage

logger = logging.getLogger("image2card.ui.main_window")


def _short(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _auto_resize_text_edit(te: QTextEdit) -> None:
    """根据 QTextEdit 文档内容自动调整高度，禁用内部滚动。"""
    doc = te.document()
    doc.setTextWidth(te.viewport().width())
    height = doc.size().height() + te.contentsMargins().top() + te.contentsMargins().bottom() + 8
    te.setFixedHeight(max(40, min(int(height), 400)))


def _stars(value: int) -> str:
    value = max(0, min(5, value))
    return "★" * value + "☆" * (5 - value)


def _make_section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def _review_due_state(card: Card) -> str:
    if card.next_due is None:
        return "待复习"
    today = date.today()
    if card.next_due <= today:
        return "今日到期"
    days = (card.next_due - today).days
    return f"{days} 天后"


def _format_review_state(card: Card) -> str:
    next_due = card.next_due.isoformat() if card.next_due else "未安排"
    last_reviewed = (
        card.last_reviewed_at.strftime("%Y-%m-%d %H:%M")
        if card.last_reviewed_at
        else "从未复习"
    )
    return (
        f"{_review_due_state(card)} · 下次 {next_due}\n"
        f"复习 {card.review_count} 次 · 遗忘 {card.lapses} 次\n"
        f"稳定性 {card.stability:.1f} 天 · 难度 {card.difficulty:.1f}\n"
        f"上次 {last_reviewed}"
    )


_STATUS_LABELS = {
    CandidateStatus.NEW: "新词条",
    CandidateStatus.EXISTING: "已有卡片",
    CandidateStatus.FAMILIAR: "已熟悉",
    CandidateStatus.SIMILAR: "疑似重复",
    CandidateStatus.IGNORED: "已忽略",
    CandidateStatus.UNCERTAIN: "待确认",
    CandidateStatus.CONFIRMED: "已加入",
}

_ACTIONABLE_CANDIDATE_STATUSES = {
    CandidateStatus.NEW,
    CandidateStatus.UNCERTAIN,
    CandidateStatus.SIMILAR,
}


class CardPropertyPanel(QFrame):
    card_saved = pyqtSignal(str)
    card_deleted = pyqtSignal(str)

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._card: Optional[Card] = None
        self.setMinimumWidth(300)
        self.setObjectName("sidebar")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._title = QLabel("卡片详情")
        self._title.setObjectName("title")
        root.addWidget(self._title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)

        content = QWidget()
        self._form = QVBoxLayout(content)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setSpacing(10)
        scroll.setWidget(content)

        self._term = QLineEdit()
        self._category = QComboBox()
        self._category.setEditable(False)
        self._fam_value: int = 0
        self._fam_spin = QSpinBox()
        self._fam_spin.setRange(0, 5)
        self._fam_spin.setFixedWidth(80)
        self._fam_spin.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        self._fam_spin.valueChanged.connect(self._on_fam_spin)
        self._fam_label = QLabel()

        # ── 折叠区块需引用的子控件 ──
        self._review_state = QLabel()
        self._review_state.setObjectName("hint")
        self._review_state.setWordWrap(True)

        # 所有文本编辑区共用外部 ScrollArea，禁用内部滚动条
        self._summary = self._make_expanding_text_edit()
        self._model_note = self._make_expanding_text_edit()
        self._user_note = self._make_expanding_text_edit()

        self._links = QTextEdit()
        self._links.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._links.setFixedHeight(78)
        self._sources = QListWidget()
        self._sources.setMaximumHeight(96)
        self._sources.itemDoubleClicked.connect(self._on_source_open)
        self._related = QListWidget()
        self._related.setMaximumHeight(96)

        # ── 始终展开的基础字段 ──
        self._add_field("词条名", self._term)
        self._add_field("工作区", self._category)
        self._form.addWidget(_make_section("熟悉度"))
        fam_row = QHBoxLayout()
        fam_row.addWidget(self._fam_spin)
        fam_row.addWidget(self._fam_label)
        fam_row.addStretch()
        self._form.addLayout(fam_row)

        # ── 可折叠的重要内容（默认展开） ──

        summary_w = QWidget()
        swl = QVBoxLayout(summary_w)
        swl.setContentsMargins(0, 0, 0, 0)
        swl.addWidget(self._summary)
        self._form.addWidget(CollapsibleSection("模型简介", summary_w, collapsed=False))

        note_w = QWidget()
        nwl = QVBoxLayout(note_w)
        nwl.setContentsMargins(0, 0, 0, 0)
        nwl.addWidget(self._model_note)
        self._form.addWidget(CollapsibleSection("模型解释", note_w, collapsed=False))

        user_w = QWidget()
        uwl = QVBoxLayout(user_w)
        uwl.setContentsMargins(0, 0, 0, 0)
        uwl.addWidget(self._user_note)
        self._form.addWidget(CollapsibleSection("用户笔记", user_w, collapsed=False))

        # ── 折叠区块：复习状态 ──
        review_w = QWidget()
        rl = QVBoxLayout(review_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._review_state)
        self._review_section = CollapsibleSection("复习状态", review_w, collapsed=True)
        self._form.addWidget(self._review_section)

        # ── 折叠区块：外部链接 ──
        self._links.setPlaceholderText("每行一个链接：标题 | URL")
        links_w = QWidget()
        ll = QVBoxLayout(links_w)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self._links)
        self._links_section = CollapsibleSection("外部链接", links_w, collapsed=True)
        self._form.addWidget(self._links_section)

        # ── 折叠区块：来源图片 ──
        sources_w = QWidget()
        sl = QVBoxLayout(sources_w)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self._sources)
        self._sources_section = CollapsibleSection("来源图片", sources_w, collapsed=True)
        self._form.addWidget(self._sources_section)

        # ── 折叠区块：相关卡片 ──
        related_w = QWidget()
        rwl = QVBoxLayout(related_w)
        rwl.setContentsMargins(0, 0, 0, 0)
        rwl.addWidget(self._related)
        self._related_section = CollapsibleSection("相关卡片", related_w, collapsed=True)
        self._form.addWidget(self._related_section)

        self._form.addStretch()

        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("保存")
        self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self._on_save)
        self._detail_btn = QPushButton("完整编辑")
        self._detail_btn.clicked.connect(self._on_open_full_detail)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._detail_btn)
        root.addLayout(btn_row)

        self._delete_btn = QPushButton("删除卡片")
        self._delete_btn.setObjectName("danger")
        self._delete_btn.clicked.connect(self._on_delete)
        root.addWidget(self._delete_btn)

        self._editable_widgets = [
            self._term,
            self._category,
            self._fam_spin,
            self._summary,
            self._model_note,
            self._user_note,
            self._links,
            self._save_btn,
            self._detail_btn,
            self._delete_btn,
        ]
        self.show_card(None)

    def _add_field(self, label: str, widget: QWidget) -> None:
        self._form.addWidget(_make_section(label))
        self._form.addWidget(widget)

    @staticmethod
    def _make_expanding_text_edit() -> QTextEdit:
        """创建一个无内部滚动条、随内容自动撑高的 QTextEdit。"""
        te = QTextEdit()
        te.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        te.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        te.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # 当内容变更时调整高度
        te.document().contentsChanged.connect(lambda: _auto_resize_text_edit(te))
        return te

    def show_card(self, card: Optional[Card]) -> None:
        self._card = card
        self._refresh_categories(card.category if card else "")

        enabled = card is not None
        for widget in self._editable_widgets:
            widget.setEnabled(enabled)

        self._sources.clear()
        self._related.clear()

        if card is None:
            self._title.setText("卡片详情")
            self._term.clear()
            self._set_category("")
            self._fam_value = 0
            self._update_fam_display()
            self._review_state.setText("从卡片库选择一张卡片")
            self._summary.clear()
            self._model_note.clear()
            self._user_note.clear()
            self._links.clear()
            self._sources.addItem("从卡片库选择一张卡片")
            self._related.addItem("暂无卡片")
            return

        self._title.setText("卡片详情")
        self._term.setText(card.term)
        self._set_category(card.category)
        self._fam_value = card.familiarity
        self._update_fam_display()
        self._review_state.setText(_format_review_state(card))
        self._summary.setPlainText(card.summary)
        self._model_note.setPlainText(card.model_note)
        self._user_note.setPlainText(card.user_note)
        self._links.setPlainText("\n".join(f"{lk.title} | {lk.url}" for lk in card.links))

        for image_id in card.source_image_ids:
            image = self._ctx.kb.get_image(image_id)
            if image:
                item = QListWidgetItem(f"{image.title or Path(image.file_path).name} · {image.category or '未分类'}")
                item.setData(Qt.UserRole, image.file_path)
                item.setToolTip(f"双击打开原图\n{image.file_path}")
                self._sources.addItem(item)
        if self._sources.count() == 0:
            self._sources.addItem("暂无来源图片")

        for related, edge in self._ctx.card_mgr.get_related_cards(card.id):
            self._related.addItem(f"{related.term} · {edge.relation_type.value}")
        if self._related.count() == 0:
            self._related.addItem("暂无相关卡片")

    def _refresh_categories(self, current: str) -> None:
        self._category.blockSignals(True)
        self._category.clear()
        self._category.addItem("未分类", "")
        names = self._ctx.kb.category_names()
        for name in names:
            self._category.addItem(name, name)
        if current and current not in names:
            self._category.addItem(current, current)
        self._set_category(current)
        self._category.blockSignals(False)

    def _set_category(self, category: str) -> None:
        idx = self._category.findData(category)
        self._category.setCurrentIndex(idx if idx >= 0 else 0)

    def _selected_category(self) -> str:
        data = self._category.currentData()
        return str(data or "").strip()

    def _update_fam_display(self) -> None:
        labels = ["完全陌生", "很陌生", "模糊", "大致了解", "熟悉", "完全掌握"]
        v = self._fam_value
        self._fam_label.setText(f"{v}/5  {_stars(v)}  {labels[v]}")
        self._fam_spin.blockSignals(True)
        self._fam_spin.setValue(v)
        self._fam_spin.blockSignals(False)

    def _on_fam_spin(self, val: int) -> None:
        self._fam_value = val
        self._update_fam_display()

    def _on_source_open(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if not path:
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "提示", f"无法打开图片：{path}")

    def _parse_links(self) -> list[Link]:
        links: list[Link] = []
        for raw in self._links.toPlainText().splitlines():
            line = raw.strip()
            if not line:
                continue
            if "|" in line:
                title, url = line.split("|", 1)
            else:
                title, url = line, line
            title = title.strip()
            url = url.strip()
            if title and url:
                links.append(Link(title=title, url=url))
        return links

    def _on_save(self) -> None:
        if self._card is None:
            return

        term = self._term.text().strip()
        if not term:
            QMessageBox.warning(self, "提示", "词条名不能为空")
            return

        category = self._selected_category()
        try:
            if category and self._ctx.kb.get_category(category) is None:
                self._ctx.card_mgr.create_category(category)

            self._card.term = term
            self._card.category = category
            self._card.familiarity = self._fam_value
            self._card.summary = self._summary.toPlainText().strip()
            self._card.model_note = self._model_note.toPlainText().strip()
            self._card.user_note = self._user_note.toPlainText().strip()
            self._card.links = self._parse_links()
            self._ctx.card_mgr.update(self._card)
            self.card_saved.emit(self._card.id)
        except Exception as exc:
            logger.exception("保存卡片失败")
            QMessageBox.critical(self, "保存失败", str(exc))

    def _on_open_full_detail(self) -> None:
        if self._card is None:
            return
        dlg = CardDetailDialog(self._card, self._ctx.card_mgr, self)
        if dlg.exec_():
            self.show_card(self._card)
            self.card_saved.emit(self._card.id)

    def _on_delete(self) -> None:
        if self._card is None:
            return
        card_id = self._card.id
        if QMessageBox.question(
            self,
            "删除卡片",
            f"确定删除「{self._card.term}」吗？",
        ) != QMessageBox.Yes:
            return
        self._ctx.card_mgr.delete(card_id)
        self.show_card(None)
        self.card_deleted.emit(card_id)


class CandidatePropertyPanel(QFrame):
    candidate_changed = pyqtSignal()
    card_created = pyqtSignal(str)

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._candidate: Optional[PendingCandidate] = None
        self.setMinimumWidth(300)
        self.setObjectName("sidebar")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._title = QLabel("候选卡片")
        self._title.setObjectName("title")
        root.addWidget(self._title)

        self._status = QLabel()
        self._status.setObjectName("hint")
        root.addWidget(self._status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)          # stretch=1，滚动区占满剩余高度

        content = QWidget()
        self._form = QVBoxLayout(content)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setSpacing(10)
        scroll.setWidget(content)

        self._term = QLineEdit()
        self._original = QLineEdit()
        self._original.setReadOnly(True)
        self._category = QComboBox()
        self._category.setEditable(False)
        self._fam_value: int = 0                    # 内部熟悉度 0-5
        self._fam_dec = QPushButton("−")
        self._fam_dec.setFixedWidth(32)
        self._fam_dec.clicked.connect(self._on_fam_dec)
        self._fam_inc = QPushButton("+")
        self._fam_inc.setFixedWidth(32)
        self._fam_inc.clicked.connect(self._on_fam_inc)
        self._fam_label = QLabel()
        self._summary = QTextEdit()
        self._summary.setFixedHeight(80)
        self._model_note = QTextEdit()
        self._model_note.setMaximumHeight(180)       # 紧凑上限
        self._user_note = QTextEdit()                 # 可扩展，在 scroll 外
        self._links = QTextEdit()
        self._links.setFixedHeight(80)
        self._links.setPlaceholderText("每行一个链接：标题 | URL")
        self._related_terms = QTextEdit()
        self._related_terms.setFixedHeight(64)
        self._merge_target = QComboBox()

        # ── scroll area 内：紧凑的元数据字段 ────────────────────────────
        self._add_field("词条名", self._term)
        self._add_field("工作区", self._category)
        self._form.addWidget(_make_section("熟悉度"))
        fam_row = QHBoxLayout()
        fam_row.addWidget(self._fam_dec)
        fam_row.addWidget(self._fam_label)
        fam_row.addWidget(self._fam_inc)
        fam_row.addStretch()
        self._form.addLayout(fam_row)
        self._add_field("图片原文", self._original)
        self._add_field("模型简介", self._summary)
        self._add_field("模型解释", self._model_note)
        self._add_field("外部链接", self._links)
        self._add_field("相关词条", self._related_terms)
        self._add_field("合并到已有卡片", self._merge_target)
        self._add_field("用户笔记", self._user_note)
        self._form.addStretch()

        action_row = QHBoxLayout()
        self._confirm_btn = QPushButton("加入卡片库")
        self._confirm_btn.setObjectName("primary")
        self._confirm_btn.clicked.connect(self._on_confirm)
        self._familiar_btn = QPushButton("标记熟悉")
        self._familiar_btn.clicked.connect(self._on_mark_familiar)
        action_row.addWidget(self._confirm_btn)
        action_row.addWidget(self._familiar_btn)
        root.addLayout(action_row)

        merge_row = QHBoxLayout()
        self._merge_btn = QPushButton("合并")
        self._merge_btn.clicked.connect(self._on_merge)
        self._ignore_btn = QPushButton("忽略")
        self._ignore_btn.setObjectName("danger")
        self._ignore_btn.clicked.connect(self._on_ignore)
        merge_row.addWidget(self._merge_btn)
        merge_row.addWidget(self._ignore_btn)
        root.addLayout(merge_row)

        self._editable_widgets = [
            self._term,
            self._category,
            self._fam_dec,
            self._fam_inc,
            self._summary,
            self._model_note,
            self._user_note,
            self._links,
            self._related_terms,
            self._merge_target,
            self._confirm_btn,
            self._familiar_btn,
            self._merge_btn,
            self._ignore_btn,
        ]
        self.show_candidate(None)

    def _add_field(self, label: str, widget: QWidget) -> None:
        self._form.addWidget(_make_section(label))
        self._form.addWidget(widget)

    def show_candidate(self, candidate: Optional[PendingCandidate]) -> None:
        self._candidate = candidate
        self._refresh_categories(self._default_category(candidate))
        self._refresh_merge_targets(candidate)

        enabled = candidate is not None
        for widget in self._editable_widgets:
            widget.setEnabled(enabled)

        if candidate is None:
            self._title.setText("候选卡片")
            self._status.setText("分析图片后，从候选列表选择一项")
            self._term.clear()
            self._original.clear()
            self._set_category("")
            self._fam_value = 0
            self._update_fam_display()
            self._summary.clear()
            self._model_note.clear()
            self._user_note.clear()
            self._links.clear()
            self._related_terms.clear()
            return

        label = _STATUS_LABELS.get(candidate.status, candidate.status.value)
        self._title.setText(candidate.term or "候选卡片")
        self._status.setText(f"{label} · 来源图片 {candidate.image_id[:8] if candidate.image_id else '无'}")
        self._term.setText(candidate.term)
        self._original.setText(candidate.original_text)
        self._set_category(self._default_category(candidate))
        self._fam_value = candidate.familiarity_suggestion
        self._update_fam_display()
        self._summary.setPlainText(candidate.card_summary)
        self._model_note.setPlainText(candidate.model_content)
        self._user_note.clear()
        self._links.setPlainText("\n".join(f"{lk.title} | {lk.url}" for lk in candidate.suggested_links))
        self._related_terms.setPlainText("\n".join(candidate.related_terms))

        is_done = candidate.status in (CandidateStatus.CONFIRMED, CandidateStatus.IGNORED)
        self._confirm_btn.setEnabled(not is_done)
        self._familiar_btn.setEnabled(not is_done)
        self._ignore_btn.setEnabled(not is_done)
        self._merge_btn.setEnabled(not is_done and self._merge_target.count() > 0)

    def _default_category(self, candidate: Optional[PendingCandidate]) -> str:
        if candidate and candidate.image_id:
            image = self._ctx.kb.get_image(candidate.image_id)
            if image:
                return image.category
        return ""

    def _refresh_categories(self, current: str) -> None:
        self._category.blockSignals(True)
        self._category.clear()
        self._category.addItem("未分类", "")
        names = self._ctx.kb.category_names()
        for name in names:
            self._category.addItem(name, name)
        if current and current not in names:
            self._category.addItem(current, current)
        self._set_category(current)
        self._category.blockSignals(False)

    def _set_category(self, category: str) -> None:
        idx = self._category.findData(category)
        self._category.setCurrentIndex(idx if idx >= 0 else 0)

    def _selected_category(self) -> str:
        data = self._category.currentData()
        return str(data or "").strip()

    def _refresh_merge_targets(self, candidate: Optional[PendingCandidate]) -> None:
        current_id = candidate.matched_card.id if candidate and candidate.matched_card else ""
        self._merge_target.blockSignals(True)
        self._merge_target.clear()
        for card in sorted(self._ctx.kb.all_cards(), key=lambda c: c.term.lower()):
            self._merge_target.addItem(f"{card.term}  ({card.category or '未分类'})", card.id)
            if card.id == current_id:
                self._merge_target.setCurrentIndex(self._merge_target.count() - 1)
        self._merge_target.blockSignals(False)

    def _update_fam_display(self) -> None:
        labels = ["完全陌生", "很陌生", "模糊", "大致了解", "熟悉", "完全掌握"]
        v = self._fam_value
        self._fam_label.setText(f"{v}/5  {_stars(v)}  {labels[v]}")
        self._fam_dec.setEnabled(v > 0)
        self._fam_inc.setEnabled(v < 5)

    def _on_fam_dec(self) -> None:
        self._fam_value = max(0, self._fam_value - 1)
        self._update_fam_display()

    def _on_fam_inc(self) -> None:
        self._fam_value = min(5, self._fam_value + 1)
        self._update_fam_display()

    def _parse_links(self) -> list[Link]:
        links: list[Link] = []
        for raw in self._links.toPlainText().splitlines():
            line = raw.strip()
            if not line:
                continue
            if "|" in line:
                title, url = line.split("|", 1)
            else:
                title, url = line, line
            title = title.strip()
            url = url.strip()
            if title and url:
                links.append(Link(title=title, url=url))
        return links

    def _sync_candidate_from_form(self) -> PendingCandidate:
        if self._candidate is None:
            raise RuntimeError("没有选中的候选")
        term = self._term.text().strip()
        if not term:
            raise ValueError("词条名不能为空")
        self._candidate.term = term
        self._candidate.card_summary = self._summary.toPlainText().strip()
        self._candidate.model_content = self._model_note.toPlainText().strip()
        self._candidate.familiarity_suggestion = self._fam_value
        self._candidate.suggested_links = self._parse_links()
        self._candidate.related_terms = [
            line.strip()
            for line in self._related_terms.toPlainText().splitlines()
            if line.strip()
        ]
        return self._candidate

    def _edits(self) -> dict:
        category = self._selected_category()
        if category and self._ctx.kb.get_category(category) is None:
            self._ctx.card_mgr.create_category(category)
        return {
            "term": self._term.text().strip(),
            "category": category,
            "summary": self._summary.toPlainText().strip(),
            "model_note": self._model_note.toPlainText().strip(),
            "user_note": self._user_note.toPlainText().strip(),
            "links": self._parse_links(),
            "familiarity": self._fam_value,
        }

    def _auto_link_image_cards(self, image_id: str) -> None:
        image = self._ctx.kb.get_image(image_id)
        if image and len(image.card_ids) > 1:
            self._ctx.card_mgr.auto_link_from_image(list(image.card_ids))

    def _on_confirm(self) -> None:
        try:
            candidate = self._sync_candidate_from_form()
            card = self._ctx.image_svc.require_candidate_manager().confirm(candidate.id, self._edits())
            self._auto_link_image_cards(candidate.image_id)
            self.show_candidate(candidate)
            self.card_created.emit(card.id)
        except Exception as exc:
            logger.exception("确认候选失败")
            QMessageBox.critical(self, "确认失败", str(exc))

    def _on_mark_familiar(self) -> None:
        if self._candidate:
            # 获取图片的所属工作区
            image = self._ctx.image_svc.get_image(self._candidate.image_id)
            workspace = image.category if image else ""
            
            # 记录用户拒绝的词条
            self._ctx.user_prefs.add_rejected_term(
                term=self._candidate.term,
                reason="familiar",
                image_id=self._candidate.image_id,
                workspace=workspace,
            )
            self._ctx.user_prefs.save()
        self._fam_value = 5
        self._update_fam_display()
        self._on_confirm()

    def _on_ignore(self) -> None:
        if self._candidate is None:
            return
        try:
            # 获取图片的所属工作区
            image = self._ctx.image_svc.get_image(self._candidate.image_id)
            workspace = image.category if image else ""
            
            # 记录用户拒绝的词条
            self._ctx.user_prefs.add_rejected_term(
                term=self._candidate.term,
                reason="ignore",
                image_id=self._candidate.image_id,
                workspace=workspace,
            )
            self._ctx.user_prefs.save()
            
            self._ctx.image_svc.require_candidate_manager().ignore(self._candidate.id)
            self.show_candidate(self._candidate)
            self.candidate_changed.emit()
        except Exception as exc:
            logger.exception("忽略候选失败")
            QMessageBox.critical(self, "忽略失败", str(exc))

    def _on_merge(self) -> None:
        if self._candidate is None:
            return
        target_id = self._merge_target.currentData()
        if not target_id:
            QMessageBox.information(self, "提示", "没有可合并的已有卡片")
            return
        try:
            candidate = self._sync_candidate_from_form()
            card = self._ctx.image_svc.require_candidate_manager().merge_into(
                candidate.id,
                str(target_id),
                {"user_note": self._user_note.toPlainText().strip()},
            )
            self._auto_link_image_cards(candidate.image_id)
            self.show_candidate(candidate)
            self.card_created.emit(card.id)
        except Exception as exc:
            logger.exception("合并候选失败")
            QMessageBox.critical(self, "合并失败", str(exc))


class WorkspaceSelector(QWidget):
    """工作区选择器：QComboBox 下拉列表 + 新建按钮，与全局顶栏风格一致"""

    workspace_changed = pyqtSignal(str)

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._confirmed_workspace = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(120)
        self._combo.currentTextChanged.connect(self._on_combo_changed)
        layout.addWidget(self._combo, 1)

        self._new_btn = QPushButton("新建工作区")
        self._new_btn.clicked.connect(self._on_new_workspace)
        layout.addWidget(self._new_btn)

    def current_workspace(self) -> str:
        """返回当前选中的工作区名称"""
        return self._combo.currentText().strip()

    def refresh(self, current: str = "") -> None:
        """刷新下拉列表并恢复选中项"""
        self._combo.blockSignals(True)
        self._combo.clear()
        names = self._ctx.kb.category_names()
        self._combo.addItems(names)
        if current and current in names:
            self._combo.setCurrentText(current)
        self._combo.blockSignals(False)

    def _on_combo_changed(self, text: str) -> None:
        text = text.strip()
        self._confirmed_workspace = text
        if text:
            self.workspace_changed.emit(text)

    def _on_new_workspace(self) -> None:
        name, ok = QInputDialog.getText(
            self, "新建工作区", "请输入工作区名称：",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if self._ctx.kb.get_category(name):
            QMessageBox.information(self, "提示", f"工作区「{name}」已存在")
            return
        try:
            self._ctx.card_mgr.create_category(name)
            self.refresh(current=name)
            self.workspace_changed.emit(name)
        except Exception as exc:
            logger.exception("创建工作区失败")
            QMessageBox.critical(self, "创建失败", str(exc))


class AnalyzePage(QWidget):
    changed = pyqtSignal()
    candidate_selected = pyqtSignal(str)

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._selected_path = ""
        self._last_image_id = ""
        self._last_candidates: list[PendingCandidate] = []
        self._analysis_visible = False
        self._default_workspace_confirmed = False  # 是否已确认使用"默认"工作区

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self._intro_top_spacer = QWidget()
        self._intro_top_spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        root.addWidget(self._intro_top_spacer, 1)

        entry_panel = QWidget()
        entry_panel.setMaximumWidth(1040)
        entry_layout = QVBoxLayout(entry_panel)
        entry_layout.setContentsMargins(0, 0, 0, 0)
        entry_layout.setSpacing(14)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("工作区"))
        self._workspace_selector = WorkspaceSelector(ctx, self)
        row1.addWidget(self._workspace_selector, 1)
        entry_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("请选择图片")
        row2.addWidget(self._path_edit, 1)

        btn_choose = QPushButton("选择图片")
        btn_choose.clicked.connect(self._on_choose)
        row2.addWidget(btn_choose)

        btn_analyze = QPushButton("开始分析")
        btn_analyze.setObjectName("primary")
        btn_analyze.clicked.connect(self._on_analyze)
        row2.addWidget(btn_analyze)
        entry_layout.addLayout(row2)

        entry_outer = QHBoxLayout()
        entry_outer.addStretch(1)
        entry_outer.addWidget(entry_panel, 4)
        entry_outer.addStretch(1)
        root.addLayout(entry_outer)

        self._intro_bottom_spacer = QWidget()
        self._intro_bottom_spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        root.addWidget(self._intro_bottom_spacer, 1)

        self._analysis_panel = QWidget()
        analysis_layout = QVBoxLayout(self._analysis_panel)
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.setSpacing(10)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("分析日志与结果会显示在这里")
        self._log.setMaximumHeight(112)
        analysis_layout.addWidget(self._log)

        candidate_header = QHBoxLayout()
        candidate_title = QLabel("候选确认队列")
        candidate_title.setObjectName("title")
        candidate_header.addWidget(candidate_title)
        self._candidate_count = QLabel("已识别 0 · 已添加 0")
        self._candidate_count.setObjectName("hint")
        self._candidate_count.setToolTip(
            "已识别=当前图片中有高置信定位、能在图上编号的词条；"
            "已添加=已确认加入词库的词条。"
        )
        candidate_header.addWidget(self._candidate_count)
        candidate_header.addStretch()

        btn_confirm_all = QPushButton("全部加入当前列表")
        btn_confirm_all.setObjectName("primary")
        btn_confirm_all.clicked.connect(self._on_confirm_all)
        candidate_header.addWidget(btn_confirm_all)

        btn_refresh = QPushButton("刷新候选")
        btn_refresh.clicked.connect(self.refresh_candidates)
        candidate_header.addWidget(btn_refresh)
        analysis_layout.addLayout(candidate_header)

        self._show_all_items = QCheckBox("显示全部识别项")
        self._show_all_items.setChecked(True)
        self._show_all_items.setToolTip("默认显示所有高置信识别项；取消勾选后只显示需要处理的新词/疑似项")
        self._show_all_items.stateChanged.connect(self.refresh_candidates)
        analysis_layout.addWidget(self._show_all_items)

        candidate_split = QSplitter(Qt.Horizontal)
        self._annotation_view = CandidateAnnotationView()
        self._annotation_view.candidate_hovered.connect(self._on_annotation_hovered)
        self._annotation_view.candidate_clicked.connect(self._on_annotation_clicked)
        candidate_split.addWidget(self._annotation_view)

        self._candidate_list = QListWidget()
        self._candidate_list.itemSelectionChanged.connect(self._on_candidate_selection_changed)
        candidate_split.addWidget(self._candidate_list)
        self._candidate_editor = CandidatePropertyPanel(ctx, self)
        self._candidate_editor.candidate_changed.connect(self._on_inline_candidate_changed)
        self._candidate_editor.card_created.connect(self._on_inline_candidate_card_created)
        candidate_split.addWidget(self._candidate_editor)
        candidate_split.setSizes([620, 300, 360])
        analysis_layout.addWidget(candidate_split, 1)
        root.addWidget(self._analysis_panel, 1)

        self.refresh_categories()
        self._set_analysis_visible(False)
        self._candidate_editor.show_candidate(None)
        self.refresh_candidates()

    def _set_analysis_visible(self, visible: bool) -> None:
        self._analysis_visible = visible
        self._analysis_panel.setVisible(visible)
        self._intro_top_spacer.setVisible(not visible)
        self._intro_bottom_spacer.setVisible(not visible)

    def refresh_categories(self) -> None:
        current = self._workspace_selector.current_workspace()
        self._workspace_selector.refresh(current)

    def _on_choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            str(Path.home()),
            "Images (*.jpg *.jpeg *.png *.bmp *.webp)",
        )
        if not path:
            return
        self._selected_path = path
        self._last_image_id = ""
        self._last_candidates = []
        self._path_edit.setText(path)
        self._log.clear()
        self._set_analysis_visible(False)
        self.refresh_candidates()
        self.changed.emit()

    def _ensure_category(self, name: str) -> None:
        name = name.strip()
        if name and self._ctx.kb.get_category(name) is None:
            self._ctx.card_mgr.create_category(name)
            self.refresh_categories()

    def _check_default_workspace(self, category: str) -> bool:
        """检查是否使用"默认"工作区，首次需要用户确认。返回 True 表示可以继续"""
        if category != "默认" or self._default_workspace_confirmed:
            return True
        reply = QMessageBox.question(
            self,
            "确认使用默认工作区",
            "你选择的是「默认」工作区。\n\n"
            "默认工作区用于存放未分类或临时内容，\n"
            "建议为不同类型的知识创建独立的工作区（如「意大利语学习」）。\n\n"
            "确定要存入默认工作区吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._default_workspace_confirmed = True
            return True
        return False

    def _on_register(self) -> None:
        if not self._selected_path:
            QMessageBox.warning(self, "提示", "请先选择图片")
            return

        category = self._workspace_selector.current_workspace()
        if not self._check_default_workspace(category):
            return

        try:
            self._ensure_category(category)
            image = self._ctx.image_svc.add_image(
                file_path=self._selected_path,
                category=category,
            )
            self._last_image_id = image.id
            self._log.append(f"已保存图片: {image.title} (id={image.id})")
            self.changed.emit()
        except Exception as exc:
            logger.exception("保存图片失败")
            QMessageBox.critical(self, "保存失败", str(exc))

    def _on_analyze(self) -> None:
        # MVP 强制顺序：若当前图片还有未处理候选，提示用户先完成
        category = self._workspace_selector.current_workspace()
        if not self._check_default_workspace(category):
            return

        mgr = self._ctx.image_svc.candidate_manager
        if mgr:
            pending = [
                c for c in mgr.all_pending()
                if c.status in _ACTIONABLE_CANDIDATE_STATUSES
            ]
            if pending:
                reply = QMessageBox.question(
                    self,
                    "仍有未处理候选",
                    f"当前图片还有 {len(pending)} 个候选词条尚未处理。\n"
                    "继续分析新图片后，这些候选仍可在列表中查看，但建议先处理完再继续。\n\n"
                    "是否继续？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return

        try:
            self._set_analysis_visible(True)
            self._log.append("开始分析图片...")

            if not self._last_image_id:
                self._on_register()
                if not self._last_image_id:
                    self._set_analysis_visible(False)
                    return

            # 获取当前图片的工作区，然后按该工作区获取拒绝的词条
            image = self._ctx.image_svc.get_image(self._last_image_id)
            workspace = image.category if image else ""
            rejected_terms = self._ctx.user_prefs.get_rejected_terms(limit=30, workspace=workspace)
            
            result, candidates = self._ctx.image_svc.analyze(
                self._last_image_id,
                rejected_terms=rejected_terms
            )
            self._log.append(
                f"分析完成: scene={result.scene_type}, items={len(result.items)}, candidates={len(candidates)}"
            )
            self._last_candidates = candidates
            self.refresh_candidates()
            if candidates:
                self._candidate_list.setCurrentRow(0)
            self.changed.emit()
        except Exception as exc:
            logger.exception("分析失败")
            QMessageBox.critical(self, "分析失败", str(exc))

    def selected_candidate_id(self) -> str:
        item = self._candidate_list.currentItem()
        return item.data(Qt.UserRole) if item else ""

    def refresh_candidates(self) -> None:
        current_id = self.selected_candidate_id()
        mgr = self._ctx.image_svc.candidate_manager
        candidates = mgr.all_pending() if mgr else self._last_candidates
        self._last_candidates = candidates
        display_candidates = self._display_candidates(candidates)

        self._candidate_list.blockSignals(True)
        self._candidate_list.clear()
        for idx, candidate in enumerate(display_candidates, start=1):
            item = QListWidgetItem(self._candidate_text(candidate, idx))
            item.setData(Qt.UserRole, candidate.id)
            item.setToolTip(candidate.model_content or candidate.card_summary or candidate.term)
            item.setSizeHint(QSize(0, 88))
            self._candidate_list.addItem(item)
            if candidate.id == current_id:
                item.setSelected(True)
                self._candidate_list.setCurrentItem(item)
        self._candidate_list.blockSignals(False)

        counts: dict[CandidateStatus, int] = {}
        for candidate in candidates:
            counts[candidate.status] = counts.get(candidate.status, 0) + 1
        recognized_count = len(self._recognized_candidates(candidates))
        done_count = counts.get(CandidateStatus.CONFIRMED, 0)
        self._candidate_count.setText(
            f"已识别 {recognized_count} · 已添加 {done_count}"
        )

        image_path = ""
        if self._last_image_id:
            image = self._ctx.kb.get_image(self._last_image_id)
            image_path = image.file_path if image else ""
        self._annotation_view.load_candidates(image_path, display_candidates)

        if self._candidate_list.currentItem() is None and self._candidate_list.count() > 0:
            self._candidate_list.setCurrentRow(0)
        else:
            self._on_candidate_selection_changed()

    def _candidate_text(self, candidate: PendingCandidate, number: int) -> str:
        status = _STATUS_LABELS.get(candidate.status, candidate.status.value)
        matched = f" → {candidate.matched_card.term}" if candidate.matched_card else ""
        summary = _short(candidate.card_summary or candidate.model_content or "暂无简介", 96)
        original = f"原文: {candidate.original_text}" if candidate.original_text else "原文: 无"
        confidence = getattr(candidate, "bbox_confidence", 0.0)
        grounding = f"定位 {confidence:.0%}" if candidate.bbox and confidence >= MIN_BBOX_CONFIDENCE else "未定位/低置信度"
        return f"{number}. {candidate.term}    [{status}{matched}]    {grounding}\n{summary}\n{original}"

    def _is_drawable_candidate(self, candidate: PendingCandidate) -> bool:
        confidence = getattr(candidate, "bbox_confidence", 0.0)
        return candidate.bbox is not None and confidence >= MIN_BBOX_CONFIDENCE

    def _recognized_candidates(self, candidates: list[PendingCandidate]) -> list[PendingCandidate]:
        return [
            candidate
            for candidate in candidates
            if self._is_drawable_candidate(candidate)
        ]

    def _display_candidates(self, candidates: list[PendingCandidate]) -> list[PendingCandidate]:
        recognized_candidates = self._recognized_candidates(candidates)
        if self._show_all_items.isChecked():
            return recognized_candidates
        return [
            candidate
            for candidate in recognized_candidates
            if candidate.status in _ACTIONABLE_CANDIDATE_STATUSES
        ]

    def _candidate_by_id(self, candidate_id: str) -> Optional[PendingCandidate]:
        mgr = self._ctx.image_svc.candidate_manager
        if mgr:
            return mgr.get(candidate_id)
        for candidate in self._last_candidates:
            if candidate.id == candidate_id:
                return candidate
        return None

    def _select_candidate_by_id(self, candidate_id: str) -> None:
        for row in range(self._candidate_list.count()):
            item = self._candidate_list.item(row)
            if item.data(Qt.UserRole) == candidate_id:
                self._candidate_list.setCurrentItem(item)
                self._candidate_list.scrollToItem(item)
                return

    def _on_candidate_selection_changed(self) -> None:
        candidate_id = self.selected_candidate_id()
        if candidate_id:
            self._annotation_view.highlight_candidate(candidate_id)
            self._candidate_editor.show_candidate(self._candidate_by_id(candidate_id))
            self.candidate_selected.emit(candidate_id)
        else:
            self._candidate_editor.show_candidate(None)

    def _on_annotation_hovered(self, candidate_id: str, active: bool) -> None:
        if active:
            self._select_candidate_by_id(candidate_id)

    def _on_annotation_clicked(self, candidate_id: str) -> None:
        self._select_candidate_by_id(candidate_id)

    def _on_confirm_all(self) -> None:
        mgr = self._ctx.image_svc.candidate_manager
        if mgr is None:
            QMessageBox.information(self, "提示", "请先分析图片生成候选")
            return

        category = self._workspace_selector.current_workspace()
        try:
            self._ensure_category(category)
            confirmed_cards: list[Card] = []
            for candidate in self._display_candidates(mgr.all_pending()):
                if candidate.status not in (
                    CandidateStatus.NEW,
                    CandidateStatus.UNCERTAIN,
                    CandidateStatus.EXISTING,
                ):
                    continue
                edits = {"category": category} if candidate.status != CandidateStatus.EXISTING else {}
                confirmed_cards.append(mgr.confirm(candidate.id, edits))

            if self._last_image_id:
                image = self._ctx.kb.get_image(self._last_image_id)
                if image and len(image.card_ids) > 1:
                    self._ctx.card_mgr.auto_link_from_image(list(image.card_ids))

            self._log.append(f"已批量加入 {len(confirmed_cards)} 张卡片")
            self.refresh_candidates()
            self.changed.emit()
        except Exception as exc:
            logger.exception("批量确认候选失败")
            QMessageBox.critical(self, "批量确认失败", str(exc))

    def _on_inline_candidate_changed(self) -> None:
        self.refresh_candidates()
        self.changed.emit()

    def _on_inline_candidate_card_created(self, card_id: str) -> None:
        self.refresh_candidates()
        self.changed.emit()


_VIEW_OPTIONS = ["图谱", "列表", "表格"]


class CardMapPage(QWidget):
    card_selected = pyqtSignal(str)

    def __init__(self, ctx: AppContext, workspace_getter, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._workspace_getter = workspace_getter
        self._selected_card_id: Optional[str] = None
        self._query = ""
        self._cards: list[Card] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── 顶栏：状态 + 视图切换 + 刷新 ────────────────────────────────
        header = QHBoxLayout()
        self._status = QLabel()
        self._status.setObjectName("title")
        header.addWidget(self._status)
        header.addStretch()

        view_label = QLabel("视图")
        header.addWidget(view_label)
        self._view_selector = QComboBox()
        self._view_selector.addItems(_VIEW_OPTIONS)
        self._view_selector.setCurrentIndex(0)  # 默认图谱
        self._view_selector.currentIndexChanged.connect(self._on_view_changed)
        header.addWidget(self._view_selector)

        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh_cards)
        header.addWidget(btn_refresh)
        root.addLayout(header)

        # ── 视图栈：图谱 / 列表 / 表格 ──────────────────────────────────
        self._view_stack = QStackedWidget()

        # 图谱视图
        self._graph_widget = CardGraphWidget()
        self._graph_widget.node_clicked.connect(self._on_node_clicked)
        self._view_stack.addWidget(self._graph_widget)

        # 列表视图
        self._list_widget = CardListView()
        self._list_widget.card_selected.connect(self._on_list_selected)
        self._view_stack.addWidget(self._list_widget)

        # 网格视图（紧凑卡片网格）
        self._grid_widget = CardGridView()
        self._grid_widget.card_selected.connect(self._on_grid_selected)
        self._view_stack.addWidget(self._grid_widget)

        root.addWidget(self._view_stack, 1)

        self.refresh_cards()

    # ── 视图切换 ────────────────────────────────────────────────────────

    def _on_view_changed(self, index: int) -> None:
        self._view_stack.setCurrentIndex(index)
        self._sync_view_selection()

    @property
    def _current_view_index(self) -> int:
        return self._view_stack.currentIndex()

    # ── 搜索 ────────────────────────────────────────────────────────────

    def set_search_query(self, query: str) -> None:
        self._query = query.strip()
        self.refresh_cards()

    # ── 数据刷新 ────────────────────────────────────────────────────────

    def refresh_cards(self) -> None:
        workspace = self._workspace_getter()
        if self._query:
            self._cards = self._ctx.search.search(
                self._query,
                category=workspace,
                familiarity_max=5,
                limit=500,
            )
        else:
            self._cards = (
                self._ctx.kb.cards_by_category(workspace)
                if workspace
                else self._ctx.kb.all_cards()
            )

        graph = self._ctx.graph.build(self._cards)
        node_ids = {node.id for node in graph.nodes}
        if self._selected_card_id not in node_ids:
            self._selected_card_id = None

        query_hint = f" · 搜索「{self._query}」" if self._query else ""
        self._status.setText(f"卡片 {len(self._cards)}{query_hint}")

        # 更新图谱
        self._graph_widget.render(graph, self._selected_card_id)

        # 更新列表
        self._list_widget.load_cards(self._cards, self._selected_card_id)

        # 更新网格
        self._grid_widget.load_cards(self._cards, self._selected_card_id)

    # ── 选中同步 ────────────────────────────────────────────────────────

    def select_card(self, card_id: str) -> None:
        self._selected_card_id = card_id or None
        self._graph_widget.set_selected_node(self._selected_card_id)
        self._list_widget.select_card(self._selected_card_id)
        self._grid_widget.select_card(self._selected_card_id)

    def _sync_view_selection(self) -> None:
        """切换视图后同步选中状态。"""
        if self._current_view_index == 0:
            self._graph_widget.set_selected_node(self._selected_card_id)
        elif self._current_view_index == 1:
            self._list_widget.select_card(self._selected_card_id)
        elif self._current_view_index == 2:
            self._grid_widget.select_card(self._selected_card_id)

    # ── 交互回调 ────────────────────────────────────────────────────────

    def _on_node_clicked(self, card_id: str) -> None:
        self.select_card(card_id)
        self.card_selected.emit(card_id)

    def _on_list_selected(self, card_id: str) -> None:
        self._selected_card_id = card_id
        self._graph_widget.set_selected_node(card_id)
        self._grid_widget.select_card(card_id)
        self.card_selected.emit(card_id)

    def _on_grid_selected(self, card_id: str) -> None:
        self._selected_card_id = card_id
        self._graph_widget.set_selected_node(card_id)
        self._list_widget.select_card(card_id)
        self.card_selected.emit(card_id)




class SettingsPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("设置")
        title.setObjectName("title")
        root.addWidget(title)

        self._provider = QLineEdit(self._ctx.config.vlm_provider)
        self._endpoint = QLineEdit(self._ctx.config.vlm_api_endpoint)
        self._api_key = QLineEdit(self._ctx.config.vlm_api_key)
        self._api_key.setEchoMode(QLineEdit.Password)
        self._model = QLineEdit(self._ctx.config.vlm_model_name)
        self._wire_api = QComboBox()
        self._wire_api.addItems(["chat", "responses"])
        self._wire_api.setCurrentText(self._ctx.config.vlm_wire_api)
        self._timeout = QLineEdit(str(self._ctx.config.vlm_timeout_seconds))
        self._mock = QCheckBox("VLM mock 模式")
        self._mock.setChecked(self._ctx.config.vlm_mock_mode)
        self._trust_env = QCheckBox("信任系统代理环境变量")
        self._trust_env.setChecked(self._ctx.config.vlm_trust_env)

        for label, widget in [
            ("Provider", self._provider),
            ("Base URL", self._endpoint),
            ("API Key", self._api_key),
            ("Model", self._model),
            ("Wire API", self._wire_api),
            ("Timeout seconds", self._timeout),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(widget, 1)
            root.addLayout(row)

        root.addWidget(self._mock)
        root.addWidget(self._trust_env)

        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._on_save)
        root.addWidget(save_btn)

        hint = QLabel("配置会保存到 ~/.image2card/user_config.json。")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)
        root.addStretch()

    def _on_save(self) -> None:
        try:
            timeout = max(1, int(self._timeout.text().strip() or "60"))
        except ValueError:
            QMessageBox.warning(self, "提示", "Timeout 必须是整数")
            return

        self._ctx.config.vlm_provider = self._provider.text().strip() or self._ctx.config.vlm_provider
        self._ctx.config.vlm_api_endpoint = self._endpoint.text().strip()
        self._ctx.config.vlm_api_key = self._api_key.text().strip()
        self._ctx.config.vlm_model_name = self._model.text().strip() or self._ctx.config.vlm_model_name
        self._ctx.config.vlm_wire_api = self._wire_api.currentText()
        self._ctx.config.vlm_timeout_seconds = timeout
        self._ctx.config.vlm_mock_mode = self._mock.isChecked()
        self._ctx.config.vlm_trust_env = self._trust_env.isChecked()
        self._ctx.save_config()
        self.changed.emit()
        QMessageBox.information(self, "完成", "设置已保存")


class _CardChatWorker(QThread):
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        ctx: AppContext,
        cards: list[Card],
        prompt: str,
        history: list[ChatTurn],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._cards = cards
        self._prompt = prompt
        self._history = history

    def run(self) -> None:
        try:
            text = self._ctx.card_chat.explain(
                cards=self._cards,
                prompt=self._prompt,
                history=self._history,
            )
            self.succeeded.emit(text)
        except Exception as exc:
            logger.exception("卡片聊天失败")
            self.failed.emit(str(exc))


class ChatMessageBubble(QFrame):
    def __init__(self, role: str, content: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._role = role
        self.setObjectName("chatBubble")

        is_user = role == "user"
        self._is_user = is_user
        self.setMaximumWidth(860 if not is_user else 640)
        self.setMinimumWidth(620 if not is_user else 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setStyleSheet(
            "QFrame#chatBubble {"
            f"background:{'#34334f' if is_user else '#26263a'};"
            f"border:1px solid {'#575575' if is_user else '#3e3d58'};"
            "border-radius:8px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8 if is_user else 10, 14, 8 if is_user else 12)
        layout.setSpacing(0)

        self._body = QTextBrowser()
        self._body.setOpenExternalLinks(True)
        self._body.setFrameShape(QFrame.NoFrame)
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setViewportMargins(0, 0, 0, 0)
        self._body.document().setDocumentMargin(0)
        self._body.document().setDefaultStyleSheet(
            "p { margin-top: 0; margin-bottom: 0; }"
            "ul, ol { margin-top: 4px; margin-bottom: 4px; }"
            "h1, h2, h3 { margin-top: 8px; margin-bottom: 4px; }"
        )
        self._body.setStyleSheet(
            "QTextBrowser {"
            "background:transparent; border:none; color:#f2f0ff;"
            "font-size:14px; line-height:1.45;"
            "}"
        )
        if is_user:
            self._body.setPlainText(content or "")
        else:
            self._body.setMarkdown(content or "")
        self._body.document().contentsChanged.connect(self._resize_body)
        layout.addWidget(self._body)
        self._resize_body()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_body()

    def _resize_body(self) -> None:
        width = max(220, self.width() - 32, self._body.viewport().width())
        self._body.document().setTextWidth(width)
        extra = 4 if self._is_user else 10
        height = int(self._body.document().size().height()) + extra
        self._body.setFixedHeight(max(22, height))


class CardChatPage(QWidget):
    def __init__(self, ctx: AppContext, workspace_getter, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._workspace_getter = workspace_getter
        self._cards: list[Card] = []
        self._selected_ids: set[str] = set()
        self._history: list[ChatTurn] = []
        self._worker: Optional[_CardChatWorker] = None

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(10)

        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("筛选要讲解的卡片")
        self._search.textChanged.connect(self.refresh_cards)
        search_row.addWidget(self._search, 1)
        left_lay.addLayout(search_row)

        action_row = QHBoxLayout()
        self._selected_label = QLabel("已选择 0")
        self._selected_label.setObjectName("hint")
        action_row.addWidget(self._selected_label)
        action_row.addStretch()
        select_all = QPushButton("全选当前")
        select_all.clicked.connect(self._select_all_visible)
        action_row.addWidget(select_all)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_selection)
        action_row.addWidget(clear_btn)
        left_lay.addLayout(action_row)

        self._card_list = QListWidget()
        self._card_list.itemChanged.connect(self._on_card_item_changed)
        left_lay.addWidget(self._card_list, 1)
        split.addWidget(left)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(10)

        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setFrameShape(QFrame.NoFrame)
        self._chat_content = QWidget()
        self._chat_content.setStyleSheet("background:transparent;")
        self._chat_layout = QVBoxLayout(self._chat_content)
        self._chat_layout.setContentsMargins(0, 0, 0, 0)
        self._chat_layout.setSpacing(12)

        self._empty_chat = QLabel("选择卡片后，输入你的问题或直接生成讲解。")
        self._empty_chat.setObjectName("hint")
        self._empty_chat.setAlignment(Qt.AlignCenter)
        self._chat_layout.addWidget(self._empty_chat, 1)
        self._chat_layout.addStretch(1)
        self._chat_scroll.setWidget(self._chat_content)
        right_lay.addWidget(self._chat_scroll, 1)

        self._prompt = QTextEdit()
        self._prompt.setPlaceholderText(
            "输入你的问题，例如：帮我比较这些卡片的区别，或者用适合初学者的方式讲解。"
        )
        self._prompt.setFixedHeight(96)
        right_lay.addWidget(self._prompt)

        send_row = QHBoxLayout()
        self._status = QLabel()
        self._status.setObjectName("hint")
        send_row.addWidget(self._status, 1)

        clear_chat = QPushButton("清空对话")
        clear_chat.clicked.connect(self._clear_chat)
        send_row.addWidget(clear_chat)

        self._send_btn = QPushButton("讲解选中卡片")
        self._send_btn.setObjectName("primary")
        self._send_btn.clicked.connect(self._on_send)
        send_row.addWidget(self._send_btn)
        right_lay.addLayout(send_row)
        split.addWidget(right)
        split.setSizes([360, 900])

        self.refresh_cards()

    def refresh_cards(self) -> None:
        workspace = self._workspace_getter()
        query = self._search.text().strip()
        if query:
            cards = self._ctx.search.search(
                query,
                category=workspace,
                familiarity_max=5,
                limit=500,
            )
        else:
            cards = self._ctx.kb.cards_by_category(workspace) if workspace else self._ctx.kb.all_cards()
        self._cards = sorted(cards, key=lambda c: (c.term or "").lower())
        self._reload_card_list()

    def _reload_card_list(self) -> None:
        self._card_list.blockSignals(True)
        self._card_list.clear()
        for card in self._cards:
            item = QListWidgetItem(self._card_item_text(card))
            item.setData(Qt.UserRole, card.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if card.id in self._selected_ids else Qt.Unchecked)
            item.setToolTip(card.model_note or card.summary or card.term)
            item.setSizeHint(QSize(0, 74))
            self._card_list.addItem(item)
        self._card_list.blockSignals(False)
        self._update_selected_label()

    @staticmethod
    def _card_item_text(card: Card) -> str:
        summary = _short(card.summary or card.model_note or "暂无简介", 72)
        meta = f"{card.category or '未分类'} · 熟悉度 {card.familiarity}/5"
        return f"{card.term or '(未命名)'}\n{summary}\n{meta}"

    def _on_card_item_changed(self, item: QListWidgetItem) -> None:
        card_id = item.data(Qt.UserRole)
        if not card_id:
            return
        if item.checkState() == Qt.Checked:
            self._selected_ids.add(card_id)
        else:
            self._selected_ids.discard(card_id)
        self._update_selected_label()

    def _select_all_visible(self) -> None:
        self._selected_ids.update(card.id for card in self._cards)
        self._reload_card_list()

    def _clear_selection(self) -> None:
        self._selected_ids.clear()
        self._reload_card_list()

    def _selected_cards(self) -> list[Card]:
        cards: list[Card] = []
        stale_ids: set[str] = set()
        for card_id in self._selected_ids:
            card = self._ctx.card_mgr.get(card_id)
            if card is None:
                stale_ids.add(card_id)
                continue
            cards.append(card)
        self._selected_ids -= stale_ids
        return sorted(cards, key=lambda c: (c.term or "").lower())

    def _update_selected_label(self) -> None:
        self._selected_label.setText(f"已选择 {len(self._selected_ids)}")

    def _on_send(self) -> None:
        if self._worker is not None:
            return
        cards = self._selected_cards()
        if not cards:
            QMessageBox.information(self, "提示", "请先选择至少一张卡片")
            return

        prompt = self._prompt.toPlainText().strip() or (
            "请讲解我选中的这些卡片，并说明它们之间的关系。"
        )
        history = list(self._history)
        self._append_turn("user", prompt)
        self._prompt.clear()
        self._set_busy(True)

        self._worker = _CardChatWorker(self._ctx, cards, prompt, history, self)
        self._worker.succeeded.connect(self._on_chat_succeeded)
        self._worker.failed.connect(self._on_chat_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_chat_succeeded(self, text: str) -> None:
        self._append_turn("assistant", text)
        self._status.setText("生成完成")

    def _on_chat_failed(self, message: str) -> None:
        self._status.setText("生成失败")
        QMessageBox.critical(self, "聊天失败", message)

    def _on_worker_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._send_btn.setEnabled(not busy)
        self._status.setText("正在生成..." if busy else self._status.text())

    def _append_turn(self, role: str, content: str) -> None:
        turn = ChatTurn(role=role, content=content.strip())
        self._history.append(turn)
        self._render_history()

    def _render_history(self) -> None:
        self._clear_chat_widgets()
        if not self._history:
            self._empty_chat = QLabel("选择卡片后，输入你的问题或直接生成讲解。")
            self._empty_chat.setObjectName("hint")
            self._empty_chat.setAlignment(Qt.AlignCenter)
            self._chat_layout.addWidget(self._empty_chat, 1)
            self._chat_layout.addStretch(1)
            return

        for turn in self._history:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            if turn.role == "user":
                row.addStretch(1)
                row.addWidget(ChatMessageBubble(turn.role, turn.content, self._chat_content))
            else:
                row.addWidget(ChatMessageBubble(turn.role, turn.content, self._chat_content))
                row.addStretch(1)
            self._chat_layout.addLayout(row)
        self._chat_layout.addStretch(1)
        QApplication.processEvents()
        self._chat_scroll.verticalScrollBar().setValue(self._chat_scroll.verticalScrollBar().maximum())

    def _clear_chat_widgets(self) -> None:
        while self._chat_layout.count():
            item = self._chat_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    child_widget = child_item.widget()
                    if child_widget is not None:
                        child_widget.deleteLater()

    def _clear_chat(self) -> None:
        if self._worker is not None:
            return
        self._history.clear()
        self._render_history()
        self._status.clear()


class HomePage(QWidget):
    navigate_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("homePage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#homePage { background:#1f1f31; }"
            "QWidget#homeActions { background:transparent; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(48, 48, 48, 48)
        root.setSpacing(28)
        root.addStretch(1)

        title = QLabel("Image2Card")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-family:'Snell Roundhand','Apple Chancery','Brush Script MT',serif;"
            "font-size:64px; font-weight:600; color:#f5f3ff;"
        )
        root.addWidget(title)

        actions = QWidget()
        actions.setObjectName("homeActions")
        actions_lay = QVBoxLayout(actions)
        actions_lay.setContentsMargins(0, 0, 0, 0)
        actions_lay.setSpacing(14)

        for row_items in [
            [("import", "导入图片"), ("cards", "卡片库")],
            [("library", "图库"), ("review", "复习")],
            [("chat", "聊天")],
        ]:
            row = QHBoxLayout()
            row.setSpacing(14)
            row.addStretch(1)
            for key, label in row_items:
                btn = self._home_button(label)
                btn.clicked.connect(lambda _, k=key: self.navigate_requested.emit(k))
                row.addWidget(btn)
            row.addStretch(1)
            actions_lay.addLayout(row)

        root.addWidget(actions)
        root.addStretch(2)

    @staticmethod
    def _home_button(label: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setMinimumSize(QSize(180, 72))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton {"
            "background:#34334f; color:#f4f2ff; border:1px solid #575575;"
            "border-radius:8px; font-size:18px; font-weight:600;"
            "}"
            "QPushButton:hover { background:#45436a; border-color:#7c6df0; }"
            "QPushButton:pressed { background:#7c6df0; }"
        )
        return btn


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._nav_buttons: dict[str, QPushButton] = {}

        self.setWindowTitle("Image2Card")
        self.resize(1360, 820)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._topbar = self._build_topbar()
        root.addWidget(self._topbar)

        body = QSplitter(Qt.Horizontal)
        self._body = body

        self._pages = QStackedWidget()
        self._home_page = HomePage(self)
        self._analyze_page = AnalyzePage(ctx, self)
        self._card_map_page = CardMapPage(ctx, self.current_workspace, self)
        self._chat_page = CardChatPage(ctx, self.current_workspace, self)
        self._library_page = LibraryPage(ctx, self)
        self._review_page = ReviewSessionPage(ctx, self.current_workspace, self)
        self._settings_page = SettingsPage(ctx, self)

        self._page_order = ["home", "import", "cards", "chat", "review", "library", "settings"]
        for page in [
            self._home_page,
            self._analyze_page,
            self._card_map_page,
            self._chat_page,
            self._review_page,
            self._library_page,
            self._settings_page,
        ]:
            self._pages.addWidget(page)
        body.addWidget(self._pages)

        self._inspector_stack = QStackedWidget()
        self._card_inspector = CardPropertyPanel(ctx, self)
        self._candidate_inspector = CandidatePropertyPanel(ctx, self)
        self._inspector_stack.addWidget(self._card_inspector)
        self._inspector_stack.addWidget(self._candidate_inspector)
        body.addWidget(self._inspector_stack)
        body.setSizes([920, 380])
        root.addWidget(body, 1)

        self.setCentralWidget(central)

        self._home_page.navigate_requested.connect(self._switch_page)
        self._analyze_page.changed.connect(self._on_data_changed)
        self._analyze_page.candidate_selected.connect(self._show_candidate)
        self._card_map_page.card_selected.connect(self._show_card)
        self._library_page.changed.connect(self._on_data_changed)
        self._review_page.session_finished.connect(self._on_data_changed)
        self._review_page.card_selected.connect(self._show_card)
        self._settings_page.changed.connect(self._on_data_changed)
        self._card_inspector.card_saved.connect(self._on_card_saved)
        self._card_inspector.card_deleted.connect(lambda _: self._on_data_changed())
        self._candidate_inspector.candidate_changed.connect(self._on_candidate_changed)
        self._candidate_inspector.card_created.connect(self._on_candidate_card_created)
        self._search_edit.textChanged.connect(self._on_search_changed)

        self.refresh_workspace_combo()
        self._switch_page("home")
        self.refresh_status()

        # ── 字体缩放快捷键 ───────────────────────────────────────────────
        # 在任何缩放之前记录原始字号，作为所有缩放计算的 base
        app = QApplication.instance()
        raw_size = app.font().pointSize() if app else 9
        self._base_font_pt: int = raw_size if raw_size > 0 else 9
        self._apply_font_scale(self._ctx.config.font_scale)
        # Ctrl++ 和 Ctrl+= 用于放大
        QShortcut(Qt.CTRL | Qt.Key_Plus, self).activated.connect(self._on_font_increase)
        QShortcut(Qt.CTRL | Qt.Key_Equal, self).activated.connect(self._on_font_increase)
        # Ctrl+- 用于缩小
        QShortcut(Qt.CTRL | Qt.Key_Minus, self).activated.connect(self._on_font_decrease)
        # Ctrl+0 用于重置
        QShortcut(Qt.CTRL | Qt.Key_0, self).activated.connect(self._on_font_reset)

    def wheelEvent(self, event) -> None:
        """处理 Ctrl+Scroll 缩放字体"""
        if event.modifiers() & Qt.ControlModifier:
            angle = event.angleDelta().y()
            if angle > 0:
                # 向上滚动（放大）
                self._on_font_increase()
                event.accept()
                return
            elif angle < 0:
                # 向下滚动（缩小）
                self._on_font_decrease()
                event.accept()
                return
        super().wheelEvent(event)

    def _apply_font_scale(self, scale: float) -> None:
        """应用字体缩放到全局应用和所有 widgets"""
        scale = max(0.8, min(2.0, scale))  # 限制在 0.8x ~ 2.0x
        app = QApplication.instance()
        if app:
            # 始终以启动时记录的原始字号为 base，避免多次缩放的累积误差
            new_size = max(1, round(self._base_font_pt * scale))
            default_font = app.font()
            default_font.setPointSize(new_size)
            
            # 应用到全局应用
            app.setFont(default_font)
            
            # 递归应用到所有已创建的 widgets
            def apply_font_recursively(widget: QWidget, font: QFont) -> None:
                """递归遍历 widget 树，对每个 widget 应用字体"""
                widget.setFont(font)
                for child in widget.children():
                    if isinstance(child, QWidget):
                        apply_font_recursively(child, font)
            
            # 遍历所有顶级 widgets（包括主窗口及其所有子 widget）
            for widget in app.topLevelWidgets():
                apply_font_recursively(widget, default_font)
            
            logger.info(f"字体缩放: {scale:.1f}x ({new_size}pt)")
        
        self._ctx.config.font_scale = scale
        self._ctx.save_config()

    def _on_font_increase(self) -> None:
        """Ctrl+ 增大字体"""
        new_scale = min(2.0, self._ctx.config.font_scale + 0.1)
        self._apply_font_scale(new_scale)

    def _on_font_decrease(self) -> None:
        """Ctrl- 减小字体"""
        new_scale = max(0.8, self._ctx.config.font_scale - 0.1)
        self._apply_font_scale(new_scale)

    def _on_font_reset(self) -> None:
        """Ctrl+0 重置字体"""
        self._apply_font_scale(1.0)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        for key, label in [
            ("import", "导入图片"),
            ("cards", "卡片库"),
            ("chat", "聊天"),
            ("library", "图库"),
            ("review", "复习"),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, k=key: self._switch_page(k))
            self._nav_buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # 全局共享工作区选择
        layout.addWidget(QLabel("工作区"))
        self._workspace_combo = QComboBox()
        self._workspace_combo.setMinimumWidth(120)
        self._workspace_combo.currentIndexChanged.connect(self._on_workspace_changed)
        layout.addWidget(self._workspace_combo)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索卡片")
        self._search_edit.setFixedWidth(300)
        layout.addWidget(self._search_edit)

        settings_btn = QPushButton("设置")
        settings_btn.setCheckable(True)
        settings_btn.clicked.connect(lambda: self._switch_page("settings"))
        self._nav_buttons["settings"] = settings_btn
        layout.addWidget(settings_btn)
        return bar

    def _switch_page(self, key: str) -> None:
        if key not in self._page_order:
            return
        self._pages.setCurrentIndex(self._page_order.index(key))
        is_home = key == "home"
        shows_inspector = key not in {"home", "import", "library", "chat"}
        self._topbar.setVisible(not is_home)
        self._inspector_stack.setVisible(shows_inspector)
        self.statusBar().setVisible(False)
        for name, btn in self._nav_buttons.items():
            btn.setChecked(name == key)
        if is_home:
            return
        if shows_inspector and self._inspector_stack.currentWidget() is self._candidate_inspector:
            self._inspector_stack.setCurrentWidget(self._card_inspector)
        if key == "cards":
            self._card_map_page.refresh_cards()
        elif key == "chat":
            self._chat_page.refresh_cards()
        elif key == "library":
            self._library_page.refresh()
        elif key == "review":
            self._review_page.refresh()

    # ── 全局共享工作区 ──────────────────────────────────────────────────

    def current_workspace(self) -> str:
        """返回当前全局选中的工作区名称，"全部" 返回空字符串"""
        text = self._workspace_combo.currentText()
        return "" if text == "全部" else text

    def refresh_workspace_combo(self) -> None:
        """刷新全局工作区下拉列表（保留当前选中项）"""
        current = self._workspace_combo.currentText()
        cats = ["全部"] + self._ctx.kb.category_names()
        self._workspace_combo.blockSignals(True)
        self._workspace_combo.clear()
        self._workspace_combo.addItems(cats)
        if current in cats:
            self._workspace_combo.setCurrentText(current)
        self._workspace_combo.blockSignals(False)

    def _on_workspace_changed(self) -> None:
        """全局工作区切换时，刷新当前页面"""
        key = self._page_order[self._pages.currentIndex()]
        if key == "cards":
            self._card_map_page.refresh_cards()
        elif key == "chat":
            self._chat_page.refresh_cards()
        elif key == "library":
            self._library_page.refresh()
        elif key == "review":
            self._review_page.refresh()

    def _on_search_changed(self, text: str) -> None:
        self._card_map_page.set_search_query(text)
        if text.strip() and self._pages.currentIndex() != self._page_order.index("cards"):
            self._switch_page("cards")

    def _show_card(self, card_id: str) -> None:
        card = self._ctx.card_mgr.get(card_id)
        self._inspector_stack.setCurrentWidget(self._card_inspector)
        self._card_inspector.show_card(card)
        if card:
            self._card_map_page.select_card(card.id)

    def _show_candidate(self, candidate_id: str) -> None:
        mgr = self._ctx.image_svc.candidate_manager
        candidate = mgr.get(candidate_id) if mgr else None
        self._inspector_stack.setCurrentWidget(self._candidate_inspector)
        self._candidate_inspector.show_candidate(candidate)

    def _on_card_saved(self, card_id: str) -> None:
        self._on_data_changed()
        self._card_map_page.select_card(card_id)
        self._show_card(card_id)

    def _on_candidate_changed(self) -> None:
        self._analyze_page.refresh_candidates()
        self._on_data_changed()

    def _on_candidate_card_created(self, card_id: str) -> None:
        self._on_data_changed()
        self._card_map_page.select_card(card_id)

    def _on_data_changed(self) -> None:
        self.refresh_workspace_combo()
        self._analyze_page.refresh_categories()
        self._analyze_page.refresh_candidates()
        self._card_map_page.refresh_cards()
        self._chat_page.refresh_cards()
        self._library_page.refresh()
        self._review_page.refresh()
        self.refresh_status()

    def refresh_status(self) -> None:
        self.statusBar().clearMessage()
        self.statusBar().hide()
