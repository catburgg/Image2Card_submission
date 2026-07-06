"""
LibraryAndPreferencePanel — 图库和用户偏好查看面板

显示：
  1. 图库：按日期分组的来源图片列表
  2. 偏好：用户的拒绝词条统计（Ignored / Familiar）
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.app_context import AppContext

logger = logging.getLogger("image2card.ui.library_preference")


class LibraryAndPreferencePanel(QFrame):
    """图库和用户偏好查看面板"""

    image_selected = pyqtSignal(str)  # 选中的图片 ID

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self.setMinimumWidth(350)
        self.setObjectName("sidebar")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # ── 图库部分 ────────────────────────────────────────────────────
        title_library = QLabel("图库")
        title_library.setObjectName("title")
        root.addWidget(title_library)

        scroll_library = QScrollArea()
        scroll_library.setWidgetResizable(True)
        scroll_library.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll_library, 1)  # stretch=1，占用多余高度

        self._library_list = QListWidget()
        self._library_list.setSelectionMode(QListWidget.SingleSelection)
        self._library_list.itemSelectionChanged.connect(self._on_image_selected)
        scroll_library.setWidget(self._library_list)

        # ── 偏好部分 ────────────────────────────────────────────────────
        title_pref = QLabel("用户偏好")
        title_pref.setObjectName("title")
        root.addWidget(title_pref)

        self._pref_label = QLabel()
        self._pref_label.setWordWrap(True)
        self._pref_label.setObjectName("hint")
        root.addWidget(self._pref_label)

        # ── 刷新按钮 ────────────────────────────────────────────────────
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh)
        root.addWidget(btn_refresh)

        self.refresh()

    def refresh(self, workspace: str = "") -> None:
        """刷新图库和偏好显示
        
        Args:
            workspace: 工作区（空字符串表示全局）
        """
        self._refresh_library(workspace)
        self._refresh_preference(workspace)

    def _refresh_library(self, workspace: str = "") -> None:
        """刷新图库列表（按日期分组）"""
        self._library_list.clear()

        # 获取所有图片并按日期分组
        all_images = self._ctx.kb.all_images()
        
        # 按日期倒序排列，最新的在前
        all_images.sort(key=lambda img: img.imported_at, reverse=True)

        # 按日期分组
        grouped_by_date: dict[str, list] = {}
        for image in all_images:
            # 只显示匹配工作区的图片
            if workspace and image.category != workspace:
                continue

            date_str = image.imported_at.strftime("%Y-%m-%d")
            if date_str not in grouped_by_date:
                grouped_by_date[date_str] = []
            grouped_by_date[date_str].append(image)

        # 按日期倒序添加到列表
        for date_str in sorted(grouped_by_date.keys(), reverse=True):
            # 添加日期标签
            date_item = QListWidgetItem(f"📅 {date_str}")
            date_item.setFlags(date_item.flags() & ~Qt.ItemIsSelectable)
            date_item.setForeground(Qt.gray)
            self._library_list.addItem(date_item)

            # 添加该日期的图片
            for image in grouped_by_date[date_str]:
                title = image.title or Path(image.file_path).name
                count_str = f" ({len(image.card_ids)} cards)" if image.card_ids else ""
                item_text = f"  📄 {title}{count_str}"
                
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, image.id)  # 存储图片 ID
                self._library_list.addItem(item)

    def _refresh_preference(self, workspace: str = "") -> None:
        """刷新偏好统计"""
        summary = self._ctx.user_prefs.get_rejected_summary(workspace=workspace)

        total = summary["total"]
        ignored = summary["ignored"]
        familiar = summary["familiar"]

        pref_text = f"""✓ 已接受: {total} 项
  • 拒绝: {ignored} 项
  • 已熟悉: {familiar} 项"""

        self._pref_label.setText(pref_text)

    def _on_image_selected(self) -> None:
        """处理图片选择"""
        item = self._library_list.currentItem()
        if item:
            image_id = item.data(Qt.UserRole)
            if image_id:
                self.image_selected.emit(image_id)
