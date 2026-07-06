"""
demo.py  —  ImageParser + ImageRenderer 联调 Demo

用法：
    python demo.py [image_path]

    若不提供路径，会弹出文件选择对话框。
    使用 mock 模式，无需 API Key。mock 结果为意大利餐厅菜单场景
    （包含 Carbonara、Tiramisu 两个词条，各带 bbox）。

交互：
    - 鼠标悬停在橙色 bbox 上 → 显示词条缩略卡片
    - 点击 bbox → 右侧展开卡片详情（含链接可点击跳转浏览器）
    - Ctrl + 滚轮 → 缩放图片
    - 拖拽 → 平移图片
"""

import sys
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QStatusBar,
)

from core.vlm import ImageParser, VLMConfig, VLMInput
from core.renderer import ImageRenderer


class DemoWindow(QMainWindow):
    def __init__(self, image_path: str) -> None:
        super().__init__()
        path = Path(image_path)
        self.setWindowTitle(f"Image2Card Demo  ·  {path.name}  [mock]")
        self.resize(1280, 800)

        # ---- 解析 ----
        config    = VLMConfig(mock_mode=False, verbose=True)
        parser    = ImageParser(config)
        vlm_input = VLMInput(image_path=image_path, config=config)
        result    = parser.parse(vlm_input)

        # ---- 状态栏 ----
        bar = QStatusBar()
        bar.showMessage(
            f"[Mock]  场景：{result.scene_type}  |  "
            f"识别条目：{len(result.items)}  |  "
            f"新候选卡片：{len(result.cards)}  |  "
            f"Ctrl+滚轮 缩放 · 拖拽平移 · 点击词条查看详情"
        )
        self.setStatusBar(bar)

        # ---- 渲染 ----
        renderer = ImageRenderer()
        renderer.render(image_path, result)
        self.setCentralWidget(renderer)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 从命令行参数或文件对话框获取图片路径
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        image_path, _ = QFileDialog.getOpenFileName(
            None,
            "选择一张图片（将以 mock 结果标注演示）",
            str(Path.home()),
            "Images (*.jpg *.jpeg *.png *.bmp *.webp)",
        )
        if not image_path:
            sys.exit(0)

    window = DemoWindow(image_path)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
