"""
Dark theme stylesheet and shared color palette for Image2Card.
"""

# ------------------------------------------------------------------
# 颜色常量
# ------------------------------------------------------------------
BG_MAIN   = "#1e1e2e"   # 主背景（深蓝黑）
BG_PANEL  = "#27273a"   # 侧边栏 / 面板背景
BG_CARD   = "#2e2e45"   # 卡片块背景
BG_INPUT  = "#35354f"   # 输入框背景
ACCENT    = "#7c6df0"   # 主色调（紫）
ACCENT2   = "#4a90d9"   # 辅色（蓝）
SUCCESS   = "#4caf50"
WARNING   = "#ff9800"
DANGER    = "#f44336"
TEXT_PRI  = "#e8e8f0"   # 主文字
TEXT_SEC  = "#9090aa"   # 次级文字
BORDER    = "#44445a"   # 边框

# 熟悉度对应的进度条颜色
FAM_COLORS = [
    "#e74c3c",  # 0 — 完全陌生
    "#e67e22",  # 1
    "#f1c40f",  # 2
    "#2ecc71",  # 3
    "#27ae60",  # 4
    "#1abc9c",  # 5 — 完全熟悉
]

# ------------------------------------------------------------------
# 全局 QSS
# ------------------------------------------------------------------
DARK_QSS = f"""
/* ===== 全局 ===== */
QWidget {{
    background-color: {BG_MAIN};
    color: {TEXT_PRI};
    font-family: "Arial", "Microsoft YaHei", "PingFang SC", sans-serif;
}}

QMainWindow, QDialog {{
    background-color: {BG_MAIN};
}}

/* ===== 滚动条 ===== */
QScrollBar:vertical {{
    background: {BG_PANEL};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {BG_PANEL};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ===== 按钮 ===== */
QPushButton {{
    background-color: {BG_CARD};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 16px;
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: #5a4fcf;
}}
QPushButton:disabled {{
    color: {TEXT_SEC};
    background-color: {BG_PANEL};
}}
QPushButton:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: white;
}}
QPushButton#primary {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: white;
    font-weight: bold;
}}
QPushButton#primary:hover {{
    background-color: #9180f4;
}}
QPushButton#danger {{
    background-color: {DANGER};
    border-color: {DANGER};
    color: white;
}}

/* ===== 输入框 ===== */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}

/* ===== 下拉框 ===== */
QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 28px;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    color: {TEXT_PRI};
    selection-background-color: {ACCENT};
    border: 1px solid {BORDER};
}}

/* ===== 标签 ===== */
QLabel#title {{
    font-weight: bold;
    color: {TEXT_PRI};
}}
QLabel#section {{
    font-weight: bold;
    color: {TEXT_SEC};
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QLabel#hint {{
    color: {TEXT_SEC};
}}

/* ===== 树形控件 ===== */
QTreeWidget {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    alternate-background-color: {BG_CARD};
}}
QTreeWidget::item {{
    padding: 4px 8px;
    border-radius: 4px;
}}
QTreeWidget::item:hover {{
    background-color: {BG_CARD};
}}
QTreeWidget::item:selected {{
    background-color: {ACCENT};
    color: white;
}}
QTreeWidget::branch {{
    background: transparent;
}}

/* ===== 列表 ===== */
QListWidget {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QListWidget::item {{
    padding: 4px 8px;
    border-radius: 4px;
}}
QListWidget::item:hover {{
    background-color: {BG_CARD};
}}
QListWidget::item:selected {{
    background-color: {ACCENT};
    color: white;
}}

/* ===== 表格 ===== */
QTableWidget {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
    alternate-background-color: {BG_CARD};
}}
QTableWidget::item {{
    padding: 4px 8px;
}}
QTableWidget::item:hover {{
    background-color: {BG_CARD};
}}
QTableWidget::item:selected {{
    background-color: {ACCENT};
    color: white;
}}
QHeaderView::section {{
    background-color: {BG_PANEL};
    color: {TEXT_SEC};
    border: none;
    border-bottom: 2px solid {ACCENT};
    padding: 6px 8px;
    font-weight: bold;
}}

/* ===== 分隔符 ===== */
QSplitter::handle {{
    background-color: {BORDER};
    width: 1px;
    height: 1px;
}}

/* ===== 滑动条 ===== */
QSlider::groove:horizontal {{
    background: {BORDER};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}

/* ===== 进度条 ===== */
QProgressBar {{
    background-color: {BORDER};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 3px;
}}

/* ===== 标签页 ===== */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background-color: {BG_PANEL};
}}
QTabBar::tab {{
    background-color: {BG_CARD};
    color: {TEXT_SEC};
    padding: 6px 16px;
    border-radius: 4px 4px 0 0;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {BG_PANEL};
    color: {TEXT_PRI};
    border-bottom: 2px solid {ACCENT};
}}

/* ===== 复选框 ===== */
QCheckBox {{
    spacing: 8px;
    color: {TEXT_PRI};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* ===== 菜单 ===== */
QMenu {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: white;
}}

/* ===== 工具提示 ===== */
QToolTip {{
    background-color: {BG_PANEL};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
}}

/* ===== Frame ===== */
QFrame#card_frame {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#sidebar {{
    background-color: {BG_PANEL};
    border-right: 1px solid {BORDER};
}}
QFrame#topbar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
}}
"""
