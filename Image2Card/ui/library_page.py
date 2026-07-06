"""
LibraryPage — 图库查看页面

功能：
  1. 按日期显示图片库（可滚轮）
  2. 显示图片缩略图，点击查看原图
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QDialog,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)

from ui.app_context import AppContext

logger = logging.getLogger("image2card.ui.library_page")

# 缩略图大小
THUMBNAIL_SIZE = 120


class ImagePreviewDialog(QDialog):
    """图片预览对话框"""
    
    def __init__(self, file_path: str, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._delete_requested = False
        self.setWindowTitle(f"预览 - {title}" if title else "图片预览")
        self.resize(800, 600)
        
        root = QVBoxLayout(self)
        
        # 显示原始图片
        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            # 缩放到合适大小（保持宽高比）
            scaled = pixmap.scaledToWidth(750, Qt.SmoothTransformation)
            
            img_label = QLabel()
            img_label.setPixmap(scaled)
            img_label.setAlignment(Qt.AlignCenter)
            
            scroll = QScrollArea()
            scroll.setWidget(img_label)
            scroll.setWidgetResizable(True)
            root.addWidget(scroll)
        else:
            root.addWidget(QLabel("无法加载图片"))
        
        action_row = QHBoxLayout()
        delete_btn = QPushButton("删除图片")
        delete_btn.setObjectName("danger")
        delete_btn.clicked.connect(self._on_delete)
        action_row.addWidget(delete_btn)
        action_row.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        action_row.addWidget(close_btn)
        root.addLayout(action_row)

    def delete_requested(self) -> bool:
        return self._delete_requested

    def _on_delete(self) -> None:
        name = self._title or "这张图片"
        if QMessageBox.question(
            self,
            "删除图片",
            f"确定从图库删除「{name}」吗？\n\n已生成卡片会保留，只会移除这张来源图片的引用。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._delete_requested = True
        self.accept()


class LibraryPage(QWidget):
    """图库查看页面"""
    changed = pyqtSignal()
    
    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        
        lib_panel = self._build_library_panel()
        root.addWidget(lib_panel, 1)
        
        self.refresh()

    def _current_workspace(self) -> str:
        """从 MainWindow 获取当前全局选中的工作区"""
        try:
            return self.window().current_workspace()  # type: ignore[union-attr]
        except Exception:
            return ""
    
    def _build_library_panel(self) -> QWidget:
        """构建图库面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        self._library_list = QListWidget()
        self._library_list.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self._library_list.itemDoubleClicked.connect(self._on_image_double_clicked)
        scroll.setWidget(self._library_list)
        
        layout.addWidget(scroll, 1)
        return panel
    
    def refresh(self) -> None:
        """刷新图库显示"""
        self._refresh_library()
    
    def _refresh_library(self) -> None:
        """刷新图库列表（按日期分组，显示缩略图）"""
        self._library_list.clear()

        workspace = self._current_workspace()
        
        # 获取所有图片并按日期倒序排列
        all_images = self._ctx.kb.all_images()
        all_images.sort(key=lambda img: img.imported_at, reverse=True)
        
        # 按日期分组
        grouped_by_date: dict[str, list] = {}
        for image in all_images:
            # 按工作区过滤
            if workspace and image.category != workspace:
                continue
            date_str = image.imported_at.strftime("%Y-%m-%d")
            if date_str not in grouped_by_date:
                grouped_by_date[date_str] = []
            grouped_by_date[date_str].append(image)
        
        # 添加到列表
        for date_str in sorted(grouped_by_date.keys(), reverse=True):
            # 日期标签
            date_item = QListWidgetItem(f"📅 {date_str}")
            date_item.setFlags(date_item.flags() & ~Qt.ItemIsSelectable)
            date_item.setForeground(Qt.gray)
            self._library_list.addItem(date_item)
            
            # 该日期的图片
            for image in grouped_by_date[date_str]:
                # 加载缩略图
                pixmap = QPixmap(image.file_path)
                if pixmap.isNull():
                    pixmap = QPixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
                    pixmap.fill(Qt.lightGray)
                
                # 缩放到缩略图大小
                thumbnail = pixmap.scaledToWidth(THUMBNAIL_SIZE, Qt.SmoothTransformation)
                
                # 图片名和卡片数
                title = image.title or Path(image.file_path).name
                card_count = len(image.card_ids)
                item_text = f"{title}\n{card_count} card(s)"
                
                item = QListWidgetItem(item_text)
                item.setIcon(QIcon(thumbnail))  # ← 用 QIcon 包装 QPixmap
                item.setData(Qt.UserRole, image.id)
                item.setData(Qt.UserRole + 1, image.file_path)  # 存储文件路径
                
                self._library_list.addItem(item)
    
    def _on_image_double_clicked(self, item: QListWidgetItem) -> None:
        """双击打开图片预览"""
        image_id = item.data(Qt.UserRole)
        file_path = item.data(Qt.UserRole + 1)
        title = item.text().split("\n")[0] if item.text() else ""
        
        if file_path:
            dlg = ImagePreviewDialog(file_path, title, self)
            if dlg.exec_() and dlg.delete_requested():
                try:
                    self._ctx.image_svc.delete_image(str(image_id), remove_stored_file=True)
                    self.refresh()
                    self.changed.emit()
                except Exception as exc:
                    logger.exception("删除图片失败")
                    QMessageBox.critical(self, "删除失败", str(exc))
