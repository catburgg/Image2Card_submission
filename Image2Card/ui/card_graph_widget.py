"""
CardGraphWidget — 聚团式卡片地图控件

使用 matplotlib 渲染卡片聚团图，嵌入到 PyQt5 中。
背景圆表示工作区/主题聚团；节点大小代表熟悉度；鼠标靠近节点时会放大高亮。
点击节点触发 node_clicked(card_id: str) 信号。

依赖：
    pip install matplotlib
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from core.graph import GraphData

logger = logging.getLogger("image2card.ui.graph")

# ---------------------------------------------------------------------------
# 聚团配色方案（最多支持 12 个分组）
# ---------------------------------------------------------------------------
_CLUSTER_COLORS = [
    "#7c6df0", "#4a90d9", "#4caf50", "#ff9800",
    "#e74c3c", "#1abc9c", "#9b59b6", "#e67e22",
    "#2980b9", "#27ae60", "#c0392b", "#8e44ad",
]

_HOVER_DISTANCE_RATIO = 0.035


def _cluster_color(cid: int) -> str:
    return _CLUSTER_COLORS[cid % len(_CLUSTER_COLORS)]


class CardGraphWidget(QWidget):
    """
    将 GraphData 渲染为聚团式卡片地图的 Qt 控件。

    信号：
        node_clicked(card_id: str)  — 用户点击某个节点时发射
    """

    node_clicked = pyqtSignal(str)   # card_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._graph_data: Optional[GraphData] = None
        self._selected_node_id: Optional[str] = None
        self._hover_node_id: Optional[str] = None
        self._id_to_pos: dict[str, tuple[float, float]] = {}

        # 延迟导入 matplotlib，避免启动时卡顿
        self._canvas = None
        self._ax = None
        self._fig = None

        self._build_ui()

    def _build_ui(self) -> None:
        mpl_cache = Path(tempfile.gettempdir()) / "image2card-matplotlib"
        mpl_cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(mpl_cache))
        xdg_cache = Path(tempfile.gettempdir()) / "image2card-cache"
        xdg_cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("XDG_CACHE_HOME", str(xdg_cache))

        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm

        # 配置中文字体支持，避免 CJK 字符显示为方块或报 Glyph missing 警告
        _cjk_fonts = [
            "PingFang SC", "Heiti SC", "Songti SC", "Hiragino Sans GB",
            "Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "FangSong",
            "Noto Sans CJK SC", "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
            "AR PL UMing CN", "AR PL UKai CN",
        ]
        _available = {f.name for f in fm.fontManager.ttflist}
        _found = [f for f in _cjk_fonts if f in _available]
        if _found:
            plt.rcParams["font.sans-serif"] = _found
            plt.rcParams["axes.unicode_minus"] = False
            logger.debug("卡片地图中文字体：%s", _found[0])
        else:
            logger.warning("未找到中文字体，卡片地图中的中文可能无法正常显示")

        plt.style.use("dark_background")
        self._fig, self._ax = plt.subplots(figsize=(8, 6))
        self._fig.patch.set_facecolor("#1e1e2e")
        self._ax.set_facecolor("#1e1e2e")
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 交互事件
        self._fig.canvas.mpl_connect("pick_event", self._on_pick)
        self._fig.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._fig.canvas.mpl_connect("axes_leave_event", self._on_leave)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)

    def render(self, graph_data: GraphData, selected_node_id: Optional[str] = None) -> None:
        """渲染卡片地图数据，清空并重绘。"""
        self._graph_data = graph_data
        self._selected_node_id = selected_node_id
        if self._hover_node_id not in {node.id for node in graph_data.nodes}:
            self._hover_node_id = None
        self._redraw()

    def set_selected_node(self, card_id: Optional[str]) -> None:
        """更新当前选中节点并重绘。"""
        self._selected_node_id = card_id
        self._redraw()

    def clear(self) -> None:
        if self._ax:
            self._ax.cla()
            if self._canvas:
                self._canvas.draw_idle()

    def _redraw(self) -> None:
        if self._ax is None or self._graph_data is None:
            return

        gdata = self._graph_data
        ax = self._ax
        ax.cla()
        ax.set_facecolor("#1e1e2e")
        ax.axis("off")
        ax.set_aspect("equal", adjustable="box")

        if not gdata.nodes:
            ax.text(
                0.5, 0.5, "暂无卡片",
                ha="center", va="center",
                color="#9090aa", fontsize=14,
                transform=ax.transAxes,
            )
            self._canvas.draw_idle()
            return

        pos = gdata.positions  # {card_id: (x, y)}
        node_map = {node.id: node for node in gdata.nodes}

        self._scatter_artists: list = []
        self._id_to_pos = {}

        xs = [pos[n.id][0] for n in gdata.nodes if n.id in pos]
        ys = [pos[n.id][1] for n in gdata.nodes if n.id in pos]
        colors = [_cluster_color(n.cluster_id) for n in gdata.nodes if n.id in pos]
        sizes = [
            self._node_size(n, is_hovered=n.id == self._hover_node_id)
            for n in gdata.nodes
            if n.id in pos
        ]
        node_ids = [n.id for n in gdata.nodes if n.id in pos]
        has_hover = self._hover_node_id in node_ids

        bounds = self._bounds(gdata)
        if bounds is not None:
            x_min, x_max, y_min, y_max = bounds
            x_span = max(x_max - x_min, 1.0)
            y_span = max(y_max - y_min, 1.0)
            ax.set_xlim(x_min - x_span * 0.10, x_max + x_span * 0.10)
            ax.set_ylim(y_min - y_span * 0.14, y_max + y_span * 0.12)

        self._draw_clusters(ax, gdata)

        sc = ax.scatter(
            xs, ys,
            c=colors, s=sizes,
            zorder=3,
            alpha=0.74 if has_hover else 0.92,
            edgecolors="#ffffff",
            linewidths=0.7,
            picker=True,
        )
        self._scatter = sc
        self._node_ids = node_ids

        if self._hover_node_id in pos:
            hover_node = node_map.get(self._hover_node_id)
            if hover_node is not None:
                hx, hy = pos[hover_node.id]
                hover_size = self._node_size(hover_node, is_hovered=True)
                ax.scatter(
                    [hx], [hy],
                    s=[hover_size + 360],
                    facecolors=_cluster_color(hover_node.cluster_id),
                    edgecolors="none",
                    alpha=0.16,
                    zorder=2,
                )
                ax.scatter(
                    [hx], [hy],
                    s=[hover_size + 130],
                    facecolors="none",
                    edgecolors="#ffffff",
                    linewidths=1.6,
                    alpha=0.86,
                    zorder=5,
                )

        if self._selected_node_id in pos:
            selected_node = node_map.get(self._selected_node_id)
            if selected_node is not None:
                sx, sy = pos[selected_node.id]
                selected_size = self._node_size(
                    selected_node,
                    is_hovered=selected_node.id == self._hover_node_id,
                ) + 180
                ax.scatter(
                    [sx], [sy],
                    s=[selected_size],
                    facecolors="none",
                    edgecolors="#f8f5a2",
                    linewidths=2.4,
                    zorder=5,
                )

        # 节点标签
        for node in gdata.nodes:
            if node.id not in pos:
                continue
            x, y = pos[node.id]
            self._id_to_pos[node.id] = (x, y)
            label = node.term if len(node.term) <= 12 else node.term[:11] + "…"
            is_hovered = node.id == self._hover_node_id
            is_selected = node.id == self._selected_node_id
            ax.text(
                x, y - (0.07 if is_hovered else 0.06),
                label,
                ha="center", va="top",
                fontsize=10 if is_hovered else 8,
                fontweight="bold" if is_hovered or is_selected else "normal",
                color="#ffffff" if is_hovered else "#e8e8f0",
                alpha=1.0 if (is_hovered or not has_hover) else 0.62,
                zorder=6 if is_hovered else 4,
                clip_on=True,
            )

        self._canvas.draw_idle()
        logger.debug("CardGraphWidget 重绘：%d 节点", len(gdata.nodes))

    def _draw_clusters(self, ax, gdata: GraphData) -> None:
        from matplotlib.patches import Circle

        for cluster in gdata.clusters:
            color = _cluster_color(cluster.id)
            circle = Circle(
                (cluster.x, cluster.y),
                cluster.radius,
                facecolor=color,
                edgecolor=color,
                linewidth=1.3,
                alpha=0.13,
                zorder=1,
            )
            ax.add_patch(circle)
            outline = Circle(
                (cluster.x, cluster.y),
                cluster.radius,
                facecolor="none",
                edgecolor=color,
                linewidth=1.1,
                alpha=0.52,
                zorder=2,
            )
            ax.add_patch(outline)
            ax.text(
                cluster.x,
                cluster.y + cluster.radius + 0.14,
                f"{cluster.label} · {len(cluster.card_ids)}",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
                color="#f0f0fa",
                alpha=0.92,
                zorder=6,
            )

    @staticmethod
    def _bounds(gdata: GraphData) -> Optional[tuple[float, float, float, float]]:
        xs: list[float] = []
        ys: list[float] = []
        for cluster in gdata.clusters:
            xs.extend([cluster.x - cluster.radius, cluster.x + cluster.radius])
            ys.extend([cluster.y - cluster.radius, cluster.y + cluster.radius])
        for node in gdata.nodes:
            if node.id in gdata.positions:
                x, y = gdata.positions[node.id]
                xs.append(x)
                ys.append(y)
        if not xs or not ys:
            return None
        return min(xs), max(xs), min(ys), max(ys)

    def _on_pick(self, event) -> None:
        """matplotlib pick 事件：找到被点击的节点并发射信号。"""
        if not hasattr(self, "_node_ids"):
            return
        ind = event.ind
        if len(ind) == 0:
            return
        idx = int(ind[0])
        if idx < len(self._node_ids):
            card_id = self._node_ids[idx]
            logger.debug("节点点击：%s", card_id)
            self.node_clicked.emit(card_id)

    def _on_motion(self, event) -> None:
        """鼠标靠近节点时触发轻量磁吸高亮。"""
        if event.inaxes is not self._ax or event.xdata is None or event.ydata is None:
            self._set_hover_node(None)
            return

        nearest_id = self._nearest_node(event.xdata, event.ydata)
        self._set_hover_node(nearest_id)

    def _on_leave(self, _event) -> None:
        self._set_hover_node(None)

    def _set_hover_node(self, card_id: Optional[str]) -> None:
        if card_id == self._hover_node_id:
            return
        self._hover_node_id = card_id
        self._redraw()

    def _nearest_node(self, x: float, y: float) -> Optional[str]:
        if not self._id_to_pos:
            return None

        nearest_id: Optional[str] = None
        nearest_dist = float("inf")
        for card_id, (nx, ny) in self._id_to_pos.items():
            dist = math.hypot(nx - x, ny - y)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_id = card_id
        threshold = self._hover_distance()
        return nearest_id if nearest_dist <= threshold else None

    def _hover_distance(self) -> float:
        if self._ax is None:
            return 0.1
        x0, x1 = self._ax.get_xlim()
        y0, y1 = self._ax.get_ylim()
        return max(abs(x1 - x0), abs(y1 - y0), 1.0) * _HOVER_DISTANCE_RATIO

    @staticmethod
    def _node_size(node, *, is_hovered: bool = False) -> float:
        # importance: [0.2, 1.0] → 基础尺寸 [60, 280]
        base = 60 + 220 * node.importance
        return base * 1.85 if is_hovered else base
