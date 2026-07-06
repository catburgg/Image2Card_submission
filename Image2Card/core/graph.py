"""
GraphEngine — 卡片地图生成与布局

将 KnowledgeBase 中的 Card 转化为面向知识地图的可视化数据结构：
  - 节点（cards）：id、term、familiarity、category、theme、cluster_id
  - 聚团（clusters）：工作区/主题形成的可视化分组

卡片库地图采用 hierarchy-first 布局：工作区决定主聚团，卡片在所属聚团内排布。
卡片之间的边保留在数据模型中，但不再作为主视觉和分组依据。

公共接口::

    engine = GraphEngine()
    graph  = engine.build(cards)             # -> GraphData（可序列化为 dict）
    pos    = graph.positions                 # {card_id: (x, y)}
    clusters = graph.clusters                # 工作区/主题聚团
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from dataclass.models import Card, KnowledgeBase

logger = logging.getLogger("image2card.graph")


# ---------------------------------------------------------------------------
# GraphData — 图数据容器
# ---------------------------------------------------------------------------

@dataclass
class GraphNode:
    id: str
    term: str
    familiarity: int
    category: str
    theme: str = "未分主题"
    cluster_id: int = 0
    community_id: int = 0
    importance: float = 0.0       # PageRank + 空间中心度综合得分，用于节点大小
    x: float = 0.0
    y: float = 0.0


@dataclass
class GraphEdge:
    source: str
    target: str
    relation_type: str
    weight: float = 1.0


@dataclass
class GraphCluster:
    id: int
    label: str
    category: str
    theme: str
    card_ids: list[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    radius: float = 1.0


@dataclass
class GraphData:
    """卡片地图的全量数据，由 GraphEngine.build() 返回。"""
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    clusters: list[GraphCluster] = field(default_factory=list)
    positions: dict[str, tuple[float, float]] = field(default_factory=dict)
    communities: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典，供前端渲染使用。"""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "term": n.term,
                    "familiarity": n.familiarity,
                    "category": n.category,
                    "theme": n.theme,
                    "cluster_id": n.cluster_id,
                    "community_id": n.community_id,
                    "importance": n.importance,
                    "x": n.x,
                    "y": n.y,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation_type": e.relation_type,
                    "weight": e.weight,
                }
                for e in self.edges
            ],
            "clusters": [
                {
                    "id": c.id,
                    "label": c.label,
                    "category": c.category,
                    "theme": c.theme,
                    "card_ids": c.card_ids,
                    "x": c.x,
                    "y": c.y,
                    "radius": c.radius,
                }
                for c in self.clusters
            ],
        }


# ---------------------------------------------------------------------------
# GraphEngine
# ---------------------------------------------------------------------------

class GraphEngine:
    """
    卡片地图生成器。

    支持两种使用方式：
      1. build(cards)         — 从 Card 列表构建卡片地图
      2. build_for_kb(kb)     — 从完整 KnowledgeBase 构建卡片地图
    """

    def build(self, cards: list[Card]) -> GraphData:
        """
        从卡片列表构建卡片地图数据，按工作区/主题生成可视化聚团。

        在布局完成后，从 Card.edges 中提取边关系，
        运行 PageRank 迭代算法计算节点重要性（importance），
        重要性越高 → 可视化时节点越大。
        """
        if not cards:
            return GraphData()

        ordered_cards = sorted(cards, key=lambda c: ((c.category or "未分类"), c.term.lower()))
        clusters = self._build_clusters(ordered_cards)
        cluster_by_card = {
            card_id: cluster
            for cluster in clusters
            for card_id in cluster.card_ids
        }
        positions = self._cluster_layout(ordered_cards, clusters)
        communities = {card.id: cluster_by_card[card.id].id for card in ordered_cards}

        # ── 从 Card.edges 提取边 ──
        card_id_set = {card.id for card in ordered_cards}
        edges: list[GraphEdge] = []
        for card in ordered_cards:
            for edge in card.edges:
                if edge.to_card_id in card_id_set:
                    edges.append(
                        GraphEdge(
                            source=card.id,
                            target=edge.to_card_id,
                            relation_type=edge.relation_type.value,
                            weight=edge.weight,
                        )
                    )

        # ── 构建节点并计算 importance ──
        importance_scores = self._compute_importance(ordered_cards, edges, positions)

        nodes: list[GraphNode] = []
        for card in ordered_cards:
            cluster = cluster_by_card[card.id]
            x, y = positions[card.id]
            nodes.append(
                GraphNode(
                    id=card.id,
                    term=card.term,
                    familiarity=card.familiarity,
                    category=card.category,
                    theme=cluster.theme,
                    cluster_id=cluster.id,
                    community_id=cluster.id,
                    importance=importance_scores.get(card.id, 0.5),
                    x=x,
                    y=y,
                )
            )

        gdata = GraphData(
            nodes=nodes,
            edges=edges,
            clusters=clusters,
            positions=positions,
            communities=communities,
        )
        logger.info(
            "GraphEngine.build: %d 节点, %d 边, %d 聚团",
            len(nodes), len(edges), len(clusters),
        )
        return gdata

    def build_for_kb(self, kb: KnowledgeBase, category: str = "") -> GraphData:
        """从 KnowledgeBase 构建卡片地图（可按类别过滤）。"""
        cards = kb.cards_by_category(category) if category else kb.all_cards()
        return self.build(cards)

    # ------------------------------------------------------------------
    # 内部：工作区聚团布局
    # ------------------------------------------------------------------

    @staticmethod
    def _theme_for_card(_card: Card) -> str:
        return "未分主题"

    def _build_clusters(self, cards: list[Card]) -> list[GraphCluster]:
        buckets: dict[tuple[str, str], list[Card]] = {}
        for card in cards:
            category = card.category or "未分类"
            theme = self._theme_for_card(card)
            buckets.setdefault((category, theme), []).append(card)

        clusters: list[GraphCluster] = []
        for idx, ((category, theme), grouped_cards) in enumerate(sorted(buckets.items())):
            label = category if theme == "未分主题" else f"{category} / {theme}"
            clusters.append(
                GraphCluster(
                    id=idx,
                    label=label,
                    category="" if category == "未分类" else category,
                    theme=theme,
                    card_ids=[card.id for card in grouped_cards],
                    radius=self._cluster_radius(len(grouped_cards)),
                )
            )
        return clusters

    def _cluster_layout(
        self,
        cards: list[Card],
        clusters: list[GraphCluster],
    ) -> dict[str, tuple[float, float]]:
        cluster_count = len(clusters)
        if cluster_count == 1:
            clusters[0].x = 0.0
            clusters[0].y = 0.0
        elif cluster_count == 2:
            distance = clusters[0].radius + clusters[1].radius + 1.45
            clusters[0].x = -distance / 2
            clusters[0].y = 0.0
            clusters[1].x = distance / 2
            clusters[1].y = 0.0
        else:
            ring_radius = max(3.2, sum(c.radius for c in clusters) / math.pi)
            for idx, cluster in enumerate(clusters):
                angle = (2 * math.pi * idx / cluster_count) - (math.pi / 2)
                cluster.x = math.cos(angle) * ring_radius
                cluster.y = math.sin(angle) * ring_radius

        card_by_id = {card.id: card for card in cards}
        positions: dict[str, tuple[float, float]] = {}
        for cluster in clusters:
            cluster_cards = [
                card_by_id[card_id]
                for card_id in cluster.card_ids
                if card_id in card_by_id
            ]
            for idx, card in enumerate(cluster_cards):
                dx, dy = self._point_in_cluster(idx, len(cluster_cards), cluster.radius)
                positions[card.id] = (cluster.x + dx, cluster.y + dy)
        return positions

    @staticmethod
    def _cluster_radius(size: int) -> float:
        return max(1.25, 0.55 * math.sqrt(max(size, 1)) + 0.75)

    @staticmethod
    def _point_in_cluster(idx: int, total: int, radius: float) -> tuple[float, float]:
        if total <= 1:
            return 0.0, 0.0

        golden_angle = math.pi * (3 - math.sqrt(5))
        normalized = (idx + 0.5) / total
        r = radius * 0.72 * math.sqrt(normalized)
        theta = idx * golden_angle
        return math.cos(theta) * r, math.sin(theta) * r

    # ------------------------------------------------------------------
    # PageRank 迭代算法 — 衡量节点在图中的重要性
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_pagerank(
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        damping: float = 0.85,
        max_iter: int = 100,
        tol: float = 1e-6,
    ) -> dict[str, float]:
        """
        经典 PageRank 迭代算法 (Brin & Page, 1998)。

        参数:
            damping  — 阻尼因子，默认 0.85
            max_iter — 最大迭代次数
            tol      — 收敛阈值（L1 范数）
        返回:
            {card_id: PageRank 得分}
        """
        n = len(nodes)
        if n == 0:
            return {}

        node_ids = [node.id for node in nodes]
        node_index = {nid: i for i, nid in enumerate(node_ids)}

        # 构建邻接表
        out_degree: dict[str, int] = {nid: 0 for nid in node_ids}
        in_neighbors: dict[str, list[str]] = {nid: [] for nid in node_ids}

        for edge in edges:
            if edge.source in node_index and edge.target in node_index:
                out_degree[edge.source] += 1
                in_neighbors[edge.target].append(edge.source)

        # 处理无出边节点（悬空节点）：均匀分布
        dangling_nodes = [nid for nid in node_ids if out_degree[nid] == 0]

        # 初始化 PageRank 为均匀分布
        pr: dict[str, float] = {nid: 1.0 / n for nid in node_ids}

        for _ in range(max_iter):
            prev = pr.copy()
            # 悬空节点的总 PageRank
            dangling_sum = sum(prev[nid] for nid in dangling_nodes)

            diff = 0.0
            for nid in node_ids:
                rank = (1.0 - damping) / n  # 随机跳转
                # 来自悬空节点的贡献（视为连接到所有节点）
                rank += damping * dangling_sum / n

                # 来自入边邻居的贡献
                for source in in_neighbors[nid]:
                    rank += damping * prev[source] / out_degree[source]

                diff += abs(rank - pr[nid])
                pr[nid] = rank

            if diff < tol:
                break

        return pr

    @staticmethod
    def _compute_importance(
        cards: list[Card],
        edges: list[GraphEdge],
        positions: dict[str, tuple[float, float]],
    ) -> dict[str, float]:
        """
        综合节点重要性得分 = PageRank × 空间中心度。

        PageRank 衡量拓扑重要性（边多 → 重要），
        空间中心度衡量布局重要性（靠近图中心 → 重要）。
        """
        if not cards:
            return {}

        # 暂用 Card 构造轻量 GraphNode 列表供 PageRank 使用
        pseudo_nodes = [
            GraphNode(
                id=card.id,
                term=card.term,
                familiarity=card.familiarity,
                category=card.category,
            )
            for card in cards
        ]

        pagerank = GraphEngine._compute_pagerank(pseudo_nodes, edges)

        # 归一化 PageRank 到 [0, 1]
        if pagerank:
            vals = list(pagerank.values())
            pr_min, pr_max = min(vals), max(vals)
            pr_range = pr_max - pr_min if pr_max > pr_min else 1.0
        else:
            return {card.id: 0.5 for card in cards}

        result: dict[str, float] = {}
        for card in cards:
            pr_norm = (pagerank.get(card.id, 0.0) - pr_min) / pr_range  # [0, 1]

            # 空间中心度：距原点 (0, 0) 越近 → 得分越高
            if card.id in positions:
                x, y = positions[card.id]
                dist = math.hypot(x, y)
                spatial = 1.0 / (1.0 + dist * 0.3)  # [0.23, 1.0]
            else:
                spatial = 0.5

            # 加权组合：PageRank 占主导 (70%)，空间中心度辅助 (30%)
            importance = 0.7 * pr_norm + 0.3 * spatial
            # 映射到 [0.2, 1.0] 防止节点完全消失
            result[card.id] = 0.2 + 0.8 * importance

        return result
