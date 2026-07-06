"""
ReviewSessionPage — 百词斩式复习界面

界面结构：
  ┌──────────────────────────────────────────┐
  │  配置阶段                                  │
  │  ┌──────────┐  ┌──────────┐  ┌────────┐  │
  │  │ 卡片数:10 │  │ 难度:中等 │  │ 开始复习│  │
  │  └──────────┘  └──────────┘  └────────┘  │
  ├──────────────────────────────────────────┤
  │  答题阶段                                  │
  │  进度 3/10  ████████░░░░░░░░░░░░░░  30%  │
  │                                          │
  │  ┌────────────────────────────────────┐  │
  │  │  摘要文本（词条名被匿名化）          │  │
  │  └────────────────────────────────────┘  │
  │                                          │
  │  ┌──────────────┐  ┌──────────────┐     │
  │  │  选项 A       │  │  选项 B       │     │
  │  └──────────────┘  └──────────────┘     │
  │  ┌──────────────┐  ┌──────────────┐     │
  │  │  选项 C       │  │  选项 D       │     │
  │  └──────────────┘  └──────────────┘     │
  │  点击选项可查看该卡片详情                  │
  ├──────────────────────────────────────────┤
  │  总结阶段                                  │
  │  正确率 + 详情列表                         │
  └──────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QAbstractSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.review_session import ReviewSession
from dataclass.models import Card
from ui.app_context import AppContext

logger = logging.getLogger("image2card.ui.review_session")


# ---------------------------------------------------------------------------
# 颜色常量（内联，与 styles.py 保持一致）
# ---------------------------------------------------------------------------

BG_MAIN = "#1e1e2e"
BG_CARD = "#2e2e45"
BG_INPUT = "#35354f"
ACCENT = "#7c6df0"
ACCENT2 = "#4a90d9"
SUCCESS = "#4caf50"
WARNING = "#ff9800"
DANGER = "#f44336"
TEXT_PRI = "#e8e8f0"
TEXT_SEC = "#9090aa"
BORDER = "#44445a"

OPTION_COLORS = ["#7c6df0", "#4a90d9", "#e67e22", "#1abc9c"]

# 字体大小倍率（相对于全局基础字号）
FONT_XL = 2.4    # 大标题
FONT_LG = 1.6    # 标题
FONT_MD = 1.15   # 正文
FONT_SM = 1.0    # 小字


def _scaled_font(multiplier: float, bold: bool = False) -> QFont:
    """基于全局应用字体创建缩放后的 QFont，避免 QSS 硬编码 px 导致的字体不一致。"""
    app = QApplication.instance()
    base_pt = app.font().pointSize() if app else 10
    font = QFont()
    font.setPointSize(max(6, round(base_pt * multiplier)))
    if bold:
        font.setBold(True)
    return font


def _short_text(text: str, limit: int = 120) -> str:
    """截断文本，用于 tooltip 和摘要显示。"""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


class ReviewSessionPage(QWidget):
    """百词斩式复习会话页面"""

    session_finished = pyqtSignal()
    card_selected = pyqtSignal(str)  # 用户点击选项查看卡片详情

    def __init__(
        self,
        ctx: AppContext,
        workspace_getter,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._workspace_getter = workspace_getter
        self._session: Optional[ReviewSession] = None
        self._answered = False
        self._option_terms: list[str] = []  # 当前题目选项对应的词条名

        self._build_ui()
        self._show_config()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._config_panel = self._build_config_panel()
        root.addWidget(self._config_panel, 1)

        self._quiz_panel = self._build_quiz_panel()
        root.addWidget(self._quiz_panel, 1)

        self._summary_panel = self._build_summary_panel()
        root.addWidget(self._summary_panel, 1)

    # ------------------------------------------------------------------
    # 配置面板
    # ------------------------------------------------------------------

    def _build_config_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("reviewConfig")
        panel.setStyleSheet(f"QWidget#reviewConfig {{ background: {BG_MAIN}; }}")

        layout = QVBoxLayout(panel)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(20)

        # 标题
        title = QLabel("开始复习")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(_scaled_font(FONT_XL, bold=True))
        title.setStyleSheet(f"color: {TEXT_PRI}; padding: 0; margin: 0;")
        layout.addWidget(title)

        subtitle = QLabel("选择复习设置，开启一次专注的复习会话")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setFont(_scaled_font(FONT_SM))
        subtitle.setStyleSheet(f"color: {TEXT_SEC};")
        layout.addWidget(subtitle)

        layout.addSpacing(16)

        # ── 卡片数量 ──
        count_row = QHBoxLayout()
        count_row.setAlignment(Qt.AlignCenter)
        count_label = QLabel("复习卡片数")
        count_label.setFont(_scaled_font(FONT_MD))
        count_label.setStyleSheet(f"color: {TEXT_PRI};")
        count_row.addWidget(count_label)

        self._num_spin = QSpinBox()
        self._num_spin.setMinimum(1)
        self._num_spin.setMaximum(100)
        self._num_spin.setValue(10)
        self._num_spin.setFixedWidth(100)
        self._num_spin.setFont(_scaled_font(FONT_MD))
        self._num_spin.setToolTip(
            "点击上部箭头增加数量\n点击下部箭头减少数量\n也可直接输入数字"
        )
        self._num_spin.setButtonSymbols(QAbstractSpinBox.UpDownArrows)

        count_row.addWidget(self._num_spin)

        spin_hint = QLabel("点击箭头或直接输入")
        spin_hint.setFont(_scaled_font(0.85))
        spin_hint.setStyleSheet(f"color: {TEXT_SEC};")
        count_row.addWidget(spin_hint)
        layout.addLayout(count_row)

        # ── 难度选择 ──
        diff_container = QVBoxLayout()
        diff_container.setSpacing(12)
        
        diff_title_row = QHBoxLayout()
        diff_label = QLabel("复习难度")
        diff_label.setFont(_scaled_font(FONT_MD, bold=True))
        diff_label.setStyleSheet(f"color: {TEXT_PRI};")
        diff_title_row.addStretch()
        diff_title_row.addWidget(diff_label)
        diff_title_row.addStretch()
        diff_container.addLayout(diff_title_row)

        diff_row = QHBoxLayout()
        diff_row.setAlignment(Qt.AlignCenter)
        diff_row.setSpacing(20)

        self._diff_buttons: list[QPushButton] = []
        diff_options = [
            (1, "简单", "优先熟悉词条"),
            (2, "中等", "均衡随机选择"),
            (3, "困难", "挑战陌生词条"),
        ]
        for val, name, hint in diff_options:
            btn_col = QVBoxLayout()
            btn_col.setSpacing(6)
            
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setFixedSize(110, 42)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFont(_scaled_font(FONT_MD))
            btn.clicked.connect(lambda _, v=val: self._on_diff_selected(v))
            
            # 按钮样式
            btn.setStyleSheet(
                f"QPushButton {{"
                f"background: {BG_CARD}; color: {TEXT_PRI};"
                f"border: 1px solid {BORDER}; border-radius: 8px;"
                f"}}"
                f"QPushButton:hover {{ border-color: {ACCENT}; background: {BG_INPUT}; }}"
                f"QPushButton:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}"
            )
            
            if val == 2:
                btn.setChecked(True)
            self._diff_buttons.append(btn)
            btn_col.addWidget(btn)
            
            caption = QLabel(hint)
            caption.setAlignment(Qt.AlignCenter)
            caption.setFont(_scaled_font(0.8))
            caption.setStyleSheet(f"color: {TEXT_SEC};")
            btn_col.addWidget(caption)
            
            diff_row.addLayout(btn_col)
            
        diff_container.addLayout(diff_row)
        layout.addLayout(diff_container)

        # ── 跳过熟悉选项 ──
        skip_row = QHBoxLayout()
        skip_row.setAlignment(Qt.AlignCenter)
        self._skip_check = QCheckBox("跳过已熟悉的词条 (熟悉度 5/5)")
        self._skip_check.setChecked(True)
        self._skip_check.setFont(_scaled_font(FONT_SM))
        self._skip_check.setStyleSheet(
            f"QCheckBox {{ color: {TEXT_PRI}; spacing: 8px; }}"
            f"QCheckBox::indicator {{"
            f"width: 18px; height: 18px;"
            f"background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 4px;"
            f"}}"
            f"QCheckBox::indicator:checked {{"
            f"background: {ACCENT}; border-color: {ACCENT};"
            f"}}"
        )
        skip_row.addWidget(self._skip_check)
        layout.addLayout(skip_row)

        layout.addSpacing(24)

        # ── 开始按钮 ──
        self._start_btn = QPushButton("开始复习")
        self._start_btn.setFixedSize(240, 56)
        self._start_btn.setCursor(Qt.PointingHandCursor)
        self._start_btn.setFont(_scaled_font(FONT_LG, bold=True))
        self._start_btn.clicked.connect(self._on_start)
        self._start_btn.setStyleSheet(
            f"QPushButton {{"
            f"background: {ACCENT}; color: white;"
            f"border: none; border-radius: 12px;"
            f"}}"
            f"QPushButton:hover {{ background: #8b7df7; }}"
            f"QPushButton:pressed {{ background: #6b5de0; }}"
        )
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        btn_row.addWidget(self._start_btn)
        layout.addLayout(btn_row)

        # ── 卡片数提示 ──
        hint = QLabel("当前工作区共有卡片待加载...")
        hint.setAlignment(Qt.AlignCenter)
        hint.setFont(_scaled_font(0.9))
        hint.setStyleSheet(f"color: {TEXT_SEC};")
        hint.setObjectName("cardCountHint")
        layout.addWidget(hint)

        layout.addStretch()
        return panel

    # ------------------------------------------------------------------
    # 答题面板
    # ------------------------------------------------------------------

    def _build_quiz_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("reviewQuiz")
        panel.setStyleSheet(f"QWidget#reviewQuiz {{ background: {BG_MAIN}; }}")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(48, 32, 48, 32)
        layout.setSpacing(16)

        # ── 顶栏：进度 ──
        top_bar = QHBoxLayout()

        self._exit_btn = QPushButton("退出")
        self._exit_btn.setFixedWidth(72)
        self._exit_btn.setCursor(Qt.PointingHandCursor)
        self._exit_btn.setFont(_scaled_font(FONT_SM))
        self._exit_btn.clicked.connect(self._on_exit)
        self._exit_btn.setStyleSheet(
            f"QPushButton {{"
            f"background: transparent; color: {TEXT_SEC};"
            f"border: 1px solid {BORDER}; border-radius: 6px;"
            f"padding: 4px 10px;"
            f"}}"
            f"QPushButton:hover {{ color: {DANGER}; border-color: {DANGER}; }}"
        )
        top_bar.addWidget(self._exit_btn)
        top_bar.addStretch()

        self._progress_label = QLabel("0 / 0")
        self._progress_label.setFont(_scaled_font(FONT_LG, bold=True))
        self._progress_label.setStyleSheet(f"color: {ACCENT};")
        top_bar.addWidget(self._progress_label)
        top_bar.addStretch()

        spacer = QWidget()
        spacer.setFixedWidth(72)
        top_bar.addWidget(spacer)
        layout.addLayout(top_bar)

        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {BG_CARD}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}"
        )
        layout.addWidget(self._progress_bar)

        layout.addSpacing(16)

        # ── 摘要区域 ──
        summary_header = QLabel("以下描述对应哪个词条？")
        summary_header.setAlignment(Qt.AlignCenter)
        summary_header.setFont(_scaled_font(FONT_MD))
        summary_header.setStyleSheet(f"color: {TEXT_SEC};")
        layout.addWidget(summary_header)

        self._summary_frame = QFrame()
        self._summary_frame.setObjectName("summaryCard")
        self._summary_frame.setStyleSheet(
            f"QFrame#summaryCard {{"
            f"background: {BG_CARD}; border: 2px solid {BORDER}; border-radius: 16px;"
            f"}}"
        )
        summary_inner = QVBoxLayout(self._summary_frame)
        summary_inner.setContentsMargins(32, 28, 32, 28)

        self._summary_text = QLabel("加载中...")
        self._summary_text.setWordWrap(True)
        self._summary_text.setAlignment(Qt.AlignCenter)
        self._summary_text.setFont(_scaled_font(FONT_LG))
        self._summary_text.setStyleSheet(
            f"color: {TEXT_PRI}; border: none; background: transparent;"
        )
        self._summary_text.setMinimumHeight(100)
        summary_inner.addWidget(self._summary_text)
        layout.addWidget(self._summary_frame)

        layout.addSpacing(12)

        # ── 选项按钮 2x2 网格 ──
        self._option_buttons: list[QPushButton] = []
        option_grid = QVBoxLayout()
        option_grid.setSpacing(10)

        for row_idx in range(2):
            row = QHBoxLayout()
            row.setSpacing(14)
            for col_idx in range(2):
                btn_idx = row_idx * 2 + col_idx
                color = OPTION_COLORS[btn_idx]
                btn = QPushButton()
                btn.setMinimumHeight(60)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setFont(_scaled_font(FONT_MD, bold=True))
                base_css = (
                    f"QPushButton {{"
                    f"background: {BG_CARD}; color: {TEXT_PRI};"
                    f"border: 2px solid {color}; border-radius: 12px;"
                    f"padding: 10px 16px; text-align: left;"
                    f"}}"
                    f"QPushButton:hover {{"
                    f"background: {color}; color: white; border-color: {color};"
                    f"}}"
                    f"QPushButton:disabled {{ color: {TEXT_SEC}; }}"
                )
                btn.setStyleSheet(base_css)
                btn.clicked.connect(lambda _, i=btn_idx: self._on_option_clicked(i))
                self._option_buttons.append(btn)
                row.addWidget(btn, 1)
            option_grid.addLayout(row)

        layout.addLayout(option_grid)

        # ── 反馈区（hint + 正确/错误 + 错误详情） ──
        self._option_hint = QLabel("")
        self._option_hint.setAlignment(Qt.AlignCenter)
        self._option_hint.setFont(_scaled_font(0.85))
        self._option_hint.setStyleSheet(f"color: {TEXT_SEC};")

        self._feedback_label = QLabel("")
        self._feedback_label.setAlignment(Qt.AlignCenter)
        self._feedback_label.setWordWrap(True)
        self._feedback_label.setFont(_scaled_font(FONT_MD, bold=True))
        self._feedback_label.setMinimumHeight(48)

        self._wrong_detail = QLabel("")
        self._wrong_detail.setAlignment(Qt.AlignCenter)
        self._wrong_detail.setWordWrap(True)
        self._wrong_detail.setFont(_scaled_font(FONT_SM))
        self._wrong_detail.setStyleSheet(
            f"color: {TEXT_SEC}; padding: 8px 16px; border-radius: 8px;"
            f"background: {BG_CARD};"
        )

        feedback_area = QVBoxLayout()
        feedback_area.setSpacing(6)
        feedback_area.addWidget(self._option_hint)
        feedback_area.addWidget(self._feedback_label)
        feedback_area.addWidget(self._wrong_detail)
        layout.addLayout(feedback_area)

        # ── 下一题按钮 ──
        self._next_btn = QPushButton("下一题")
        self._next_btn.setFixedSize(180, 48)
        self._next_btn.setCursor(Qt.PointingHandCursor)
        self._next_btn.setFont(_scaled_font(FONT_MD, bold=True))
        self._next_btn.clicked.connect(self._on_next)
        self._next_btn.setStyleSheet(
            f"QPushButton {{"
            f"background: {ACCENT}; color: white; border: none; border-radius: 10px;"
            f"}}"
            f"QPushButton:hover {{ background: #8b7df7; }}"
            f"QPushButton:pressed {{ background: #6b5de0; }}"
        )
        next_row = QHBoxLayout()
        next_row.setAlignment(Qt.AlignCenter)
        next_row.addWidget(self._next_btn)
        layout.addLayout(next_row)

        layout.addStretch()
        return panel

    # ------------------------------------------------------------------
    # 总结面板
    # ------------------------------------------------------------------

    def _build_summary_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("reviewSummary")
        panel.setStyleSheet(f"QWidget#reviewSummary {{ background: {BG_MAIN}; }}")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(48, 32, 48, 32)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignCenter)

        self._summary_title = QLabel("复习完成")
        self._summary_title.setAlignment(Qt.AlignCenter)
        self._summary_title.setFont(_scaled_font(FONT_XL, bold=True))
        self._summary_title.setStyleSheet(f"color: {TEXT_PRI};")
        layout.addWidget(self._summary_title)

        self._summary_score = QLabel("0 / 0")
        self._summary_score.setAlignment(Qt.AlignCenter)
        self._summary_score.setFont(_scaled_font(3.5, bold=True))
        layout.addWidget(self._summary_score)

        self._summary_rate = QLabel("正确率 0%")
        self._summary_rate.setAlignment(Qt.AlignCenter)
        self._summary_rate.setFont(_scaled_font(FONT_LG))
        self._summary_rate.setStyleSheet(f"color: {TEXT_SEC};")
        layout.addWidget(self._summary_rate)

        self._summary_comment = QLabel("")
        self._summary_comment.setAlignment(Qt.AlignCenter)
        self._summary_comment.setWordWrap(True)
        self._summary_comment.setFont(_scaled_font(FONT_MD))
        self._summary_comment.setStyleSheet(f"color: {TEXT_PRI}; padding: 16px;")
        layout.addWidget(self._summary_comment)

        # 详情滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(300)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {BG_CARD}; width: 6px; border-radius: 3px; }}"
            f"QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

        self._result_list = QWidget()
        self._result_list_layout = QVBoxLayout(self._result_list)
        self._result_list_layout.setSpacing(8)
        self._result_list_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._result_list)
        layout.addWidget(scroll)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        btn_row.setSpacing(16)

        self._retry_btn = QPushButton("再来一次")
        self._retry_btn.setFixedSize(160, 48)
        self._retry_btn.setCursor(Qt.PointingHandCursor)
        self._retry_btn.setFont(_scaled_font(FONT_MD, bold=True))
        self._retry_btn.clicked.connect(self._show_config)
        self._retry_btn.setStyleSheet(
            f"QPushButton {{"
            f"background: {ACCENT}; color: white; border: none; border-radius: 10px;"
            f"}}"
            f"QPushButton:hover {{ background: #8b7df7; }}"
        )

        self._done_btn = QPushButton("完成")
        self._done_btn.setFixedSize(160, 48)
        self._done_btn.setCursor(Qt.PointingHandCursor)
        self._done_btn.setFont(_scaled_font(FONT_MD))
        self._done_btn.clicked.connect(self._on_done)
        self._done_btn.setStyleSheet(
            f"QPushButton {{"
            f"background: {BG_CARD}; color: {TEXT_PRI};"
            f"border: 1px solid {BORDER}; border-radius: 10px;"
            f"}}"
            f"QPushButton:hover {{ border-color: {ACCENT}; }}"
        )

        btn_row.addWidget(self._retry_btn)
        btn_row.addWidget(self._done_btn)
        layout.addLayout(btn_row)

        layout.addStretch()
        return panel

    # ------------------------------------------------------------------
    # 阶段切换
    # ------------------------------------------------------------------

    def _show_config(self) -> None:
        self._session = None
        self._config_panel.setVisible(True)
        self._quiz_panel.setVisible(False)
        self._summary_panel.setVisible(False)
        self._update_config_hint()

    def _show_quiz(self) -> None:
        self._config_panel.setVisible(False)
        self._quiz_panel.setVisible(True)
        self._summary_panel.setVisible(False)
        self._show_current_question()

    def _show_summary(self) -> None:
        self._config_panel.setVisible(False)
        self._quiz_panel.setVisible(False)
        self._summary_panel.setVisible(True)
        self._render_summary()

    # ------------------------------------------------------------------
    # 配置阶段方法
    # ------------------------------------------------------------------

    def _update_config_hint(self) -> None:
        hint = self.findChild(QLabel, "cardCountHint")
        if hint is None:
            return
        workspace = self._workspace_getter()
        cards = (
            self._ctx.kb.cards_by_category(workspace)
            if workspace
            else self._ctx.kb.all_cards()
        )
        available = len(cards)
        hint.setText(
            f"当前工作区共有 {available} 张卡片可用"
            + ("" if available > 0 else " -- 请先添加卡片")
        )
        self._num_spin.setMaximum(max(1, available))
        if self._num_spin.value() > available:
            self._num_spin.setValue(max(1, available))

    def _on_diff_selected(self, value: int) -> None:
        for btn in self._diff_buttons:
            btn.setChecked(False)
            btn.setFont(_scaled_font(0.95))
            btn.setStyleSheet(
                f"QPushButton {{"
                f"background: {BG_CARD}; color: {TEXT_SEC};"
                f"border: 2px solid {BORDER}; border-radius: 10px;"
                f"padding: 8px;"
                f"}}"
                f"QPushButton:hover {{ border-color: {ACCENT}; }}"
            )
        sender = self.sender()
        if isinstance(sender, QPushButton):
            sender.setChecked(True)
            sender.setFont(_scaled_font(0.95, bold=True))
            sender.setStyleSheet(
                f"QPushButton {{"
                f"background: {ACCENT}; color: white;"
                f"border: 2px solid {ACCENT}; border-radius: 10px;"
                f"padding: 8px;"
                f"}}"
            )

    def _selected_difficulty(self) -> int:
        for i, btn in enumerate(self._diff_buttons):
            if btn.isChecked():
                return i + 1
        return 2

    def _on_start(self) -> None:
        workspace = self._workspace_getter()
        cards = (
            self._ctx.kb.cards_by_category(workspace)
            if workspace
            else self._ctx.kb.all_cards()
        )
        if not cards:
            return
        num = self._num_spin.value()
        difficulty = self._selected_difficulty()
        skip_familiar = self._skip_check.isChecked()
        self._session = ReviewSession(
            cards, num_questions=num, difficulty=difficulty,
            skip_familiar=skip_familiar,
        )
        if self._session.total_questions == 0:
            return
        self._show_quiz()

    # ------------------------------------------------------------------
    # 答题阶段方法
    # ------------------------------------------------------------------

    def _show_current_question(self) -> None:
        if self._session is None or self._session.is_finished:
            self._on_session_end()
            return

        q = self._session.current_question
        if q is None:
            self._on_session_end()
            return

        self._answered = False
        self._option_terms = q.options[:]

        # 进度
        done, total = self._session.progress
        self._progress_label.setText(f"{done} / {total}")
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(done)

        # 摘要（高亮 _____）
        summary_text = q.anonymized_summary.replace(
            "_____",
            '<span style="color:#f1c40f; font-weight:bold; '
            'background:#3d3d20; padding:2px 8px; border-radius:4px;">_____</span>'
        )
        self._summary_text.setText(summary_text)
        self._summary_text.setTextFormat(Qt.RichText)

        # 重置选项按钮
        for i, btn in enumerate(self._option_buttons):
            if i < len(q.options):
                prefix = ["A", "B", "C", "D"][i]
                btn.setText(f"{prefix}.  {q.options[i]}")
                btn.setEnabled(True)
                btn.setToolTip("")
                color = OPTION_COLORS[i]
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"background: {BG_CARD}; color: {TEXT_PRI};"
                    f"border: 2px solid {color}; border-radius: 12px;"
                    f"padding: 10px 16px; text-align: left;"
                    f"}}"
                    f"QPushButton:hover {{"
                    f"background: {color}; color: white; border-color: {color};"
                    f"}}"
                )
            else:
                btn.setText("")
                btn.setEnabled(False)
                btn.setToolTip("")
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; border: none; }}"
                )

        # 清除反馈
        self._feedback_label.setText("")
        self._feedback_label.setStyleSheet("")
        self._wrong_detail.setText("")
        self._wrong_detail.setVisible(False)
        self._option_hint.setText("")
        self._next_btn.setVisible(False)

    def _on_option_clicked(self, option_index: int) -> None:
        """点击选项：未作答时提交答案；已作答时查看卡片详情。"""
        if self._session is None:
            return

        # ── 已作答 → 查看卡片详情（无需 current_question，answer() 已推进索引） ──
        if self._answered:
            if 0 <= option_index < len(self._option_terms):
                term = self._option_terms[option_index]
                card = self._ctx.card_mgr.get_by_term(term)
                if card:
                    self.card_selected.emit(card.id)
            return

        # ── 首次点击 → 提交答案 ──
        q = self._session.current_question
        if q is None:
            return
        self._answered = True
        is_correct = self._session.answer(option_index)

        # 所有选项保持可用，更新 tooltip 以便查看详情
        for i, btn in enumerate(self._option_buttons):
            if i < len(self._option_terms):
                term = self._option_terms[i]
                card = self._ctx.card_mgr.get_by_term(term)
                hint_text = (
                    _short_text(card.summary or card.model_note or "", 100)
                    if card else ""
                )
                btn.setToolTip(f"点击查看「{term}」的卡片详情\n{hint_text}")
                btn.setEnabled(True)
            else:
                btn.setEnabled(False)

        # 高亮正确答案（绿色）
        correct_btn = self._option_buttons[q.correct_index]
        correct_btn.setStyleSheet(
            f"QPushButton {{"
            f"background: {SUCCESS}; color: white;"
            f"border: 2px solid {SUCCESS}; border-radius: 12px;"
            f"padding: 10px 16px; text-align: left;"
            f"}}"
            f"QPushButton:hover {{ background: #5dbf60; }}"
        )

        # ── 反馈文字 ──
        if is_correct:
            self._feedback_label.setText("回答正确！熟悉度 +1")
            self._feedback_label.setStyleSheet(
                f"color: {SUCCESS}; background: #1a3a1a;"
                f"padding: 12px; border-radius: 10px;"
            )
            self._wrong_detail.setVisible(False)
        else:
            # 高亮错误选择（红色）
            wrong_btn = self._option_buttons[option_index]
            wrong_btn.setStyleSheet(
                f"QPushButton {{"
                f"background: {DANGER}; color: white;"
                f"border: 2px solid {DANGER}; border-radius: 12px;"
                f"padding: 10px 16px; text-align: left;"
                f"}}"
                f"QPushButton:hover {{ background: #f55a4e; }}"
            )

            self._feedback_label.setText(
                f"回答错误！正确答案是「{q.correct_term}」"
            )
            self._feedback_label.setStyleSheet(
                f"color: {DANGER}; background: #3a1a1a;"
                f"padding: 12px; border-radius: 10px;"
            )

            # 显示错误选项的摘要
            wrong_term = (
                self._option_terms[option_index]
                if 0 <= option_index < len(self._option_terms)
                else ""
            )
            wrong_card = (
                self._ctx.card_mgr.get_by_term(wrong_term) if wrong_term else None
            )
            if wrong_card:
                wrong_summary = _short_text(
                    wrong_card.summary or wrong_card.model_note or "", 200
                )
                self._wrong_detail.setText(
                    f"你选的「{wrong_term}」是：{wrong_summary}"
                )
            else:
                self._wrong_detail.setText(f"你选的「{wrong_term}」暂无简介")
            self._wrong_detail.setVisible(True)

        # 答后提示
        self._option_hint.setText("点击任意选项可查看该卡片详情")

        # 下一题按钮
        done, total = self._session.progress
        self._next_btn.setText("查看总结" if done >= total else "下一题")
        self._next_btn.setVisible(True)

    def _on_next(self) -> None:
        if self._session is None:
            return
        if self._session.is_finished:
            self._on_session_end()
        else:
            self._show_current_question()

    def _on_exit(self) -> None:
        if self._session and not self._session.is_finished:
            self._session = None
        self._show_config()

    def _on_session_end(self) -> None:
        if self._session is None:
            return
        self._session.persist_results(self._ctx.card_mgr)
        self._show_summary()
        self.session_finished.emit()

    # ------------------------------------------------------------------
    # 总结阶段
    # ------------------------------------------------------------------

    def _render_summary(self) -> None:
        if self._session is None:
            return

        correct = self._session.correct_count
        total = self._session.total_questions
        accuracy = correct / total * 100 if total > 0 else 0

        self._summary_score.setText(f"{correct} / {total}")
        self._summary_rate.setText(f"正确率 {accuracy:.0f}%")

        if accuracy >= 90:
            self._summary_title.setText("太棒了！")
            self._summary_comment.setText("你对这些词条掌握得非常好！")
            self._summary_score.setStyleSheet(f"color: {SUCCESS};")
        elif accuracy >= 70:
            self._summary_title.setText("不错！")
            self._summary_comment.setText("大部分词条都掌握了，继续加油！")
            self._summary_score.setStyleSheet(f"color: {ACCENT2};")
        elif accuracy >= 50:
            self._summary_title.setText("还有提升空间")
            self._summary_comment.setText("再练一次，你可以做得更好！")
            self._summary_score.setStyleSheet(f"color: {WARNING};")
        else:
            self._summary_title.setText("继续努力")
            self._summary_comment.setText("多加练习，你会越来越好的！")
            self._summary_score.setStyleSheet(f"color: {DANGER};")

        # 清空旧结果
        while self._result_list_layout.count():
            child = self._result_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # 渲染每题结果
        results = self._session.get_results()
        for r in results:
            self._result_list_layout.addWidget(self._build_result_item(r))
        self._result_list_layout.addStretch()

    def _build_result_item(self, result: dict) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {BG_CARD}; border-radius: 8px; padding: 8px; }}"
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        idx_label = QLabel(f"#{result['index']}")
        idx_label.setFixedWidth(36)
        idx_label.setFont(_scaled_font(FONT_SM))
        idx_label.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        layout.addWidget(idx_label)

        icon = "V" if result["is_correct"] else "X"
        icon_color = SUCCESS if result["is_correct"] else DANGER
        icon_label = QLabel(icon)
        icon_label.setFixedWidth(20)
        icon_label.setFont(_scaled_font(FONT_MD, bold=True))
        icon_label.setStyleSheet(f"color: {icon_color}; background: transparent;")
        layout.addWidget(icon_label)

        term_label = QLabel(result["term"])
        term_label.setFont(_scaled_font(FONT_MD, bold=True))
        term_label.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        layout.addWidget(term_label, 1)

        if not result["is_correct"]:
            user_ans = QLabel(f"你选了「{result['user_answer']}」")
            user_ans.setFont(_scaled_font(0.85))
            user_ans.setStyleSheet(f"color: {DANGER}; background: transparent;")
            layout.addWidget(user_ans)

        layout.addStretch()
        return frame

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """外部调用刷新（工作区切换时）。"""
        if self._config_panel.isVisible():
            self._update_config_hint()

    def _on_done(self) -> None:
        self._show_config()
