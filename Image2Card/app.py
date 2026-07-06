from __future__ import annotations

import logging
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox

from ui.app_context import AppContext
from ui.main_window import MainWindow
from ui.styles import DARK_QSS


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _preload_ocr(ctx: AppContext) -> None:
    """在后台线程中预加载 OCR 模型，避免首次分析时卡顿。"""
    logger = logging.getLogger("image2card.app")

    def _load():
        try:
            ctx.ocr.load_model()
            logger.info("OCR 模型已在后台预加载完成")
        except Exception as exc:
            logger.warning("OCR 模型后台预加载失败（首次使用时将重试）：%s", exc)

    import threading
    t = threading.Thread(target=_load, name="ocr-preload", daemon=True)
    t.start()


def main() -> int:
    _setup_logging()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)

    try:
        ctx = AppContext.instance()
    except Exception as exc:
        QMessageBox.critical(None, "启动失败", f"AppContext 初始化失败:\n{exc}")
        return 1

    # 确保"默认"工作区存在（不存在则静默创建）
    if ctx.kb.get_category("默认") is None:
        ctx.card_mgr.create_category("默认", description="系统默认工作区", icon="📂")

    window = MainWindow(ctx)
    window.show()

    # 启动后异步预加载 OCR 模型，不阻塞 UI 绘制
    QTimer.singleShot(0, lambda: _preload_ocr(ctx))

    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
