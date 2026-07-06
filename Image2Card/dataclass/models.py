"""
Image2Card 核心数据结构定义

模块结构：
  枚举        CandidateStatus       候选卡片状态
              RelationType          卡片关系类型
              ReviewRating          复习评级

  基础结构    BoundingBox           图片位置区域（dataclass，__post_init__ 保证 x1≤x2, y1≤y2）
              Link                  互联网链接（NamedTuple）

  核心实体    Category              工作区（用户管理的最高层组织单元）
              Card                  知识卡片（含内部类 Card.Edge）
              SourceImage           来源图片（含 category 归属）

  VLM 输出    VLMBBox               Pydantic bbox，含坐标规范化 validator
  (Pydantic)  VLMLink               Pydantic 链接
              VLMResultItem         items 数组元素（高置信条目，含 existing）
              VLMCandidateCard      cards 数组元素（仅新词条）
              AnalyzeResult         VLM 完整分析结果（顶层 Pydantic 模型，JSON 可校验）

  复习记录    ReviewLog             单次复习记录（FSRS）

  全局状态    KnowledgeBase         卡片库全局状态

  VLM 相关    VLMConfig             模型 API 配置（独立给 VLM 层使用）
              VLMInput              单次调用输入
"""

from __future__ import annotations

from tabnanny import verbose
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
import json as _json
import os
from pathlib import Path as _Path
from typing import ClassVar, NamedTuple, Optional
from pydantic import BaseModel, Field, model_validator


def _load_env_files() -> None:
    """
    Load simple KEY=VALUE env files without adding a runtime dependency.

    Real environment variables keep priority. Later local files override
    earlier local files, so ~/.image2card/.env.local can travel with the data
    directory and supersede project defaults after migration.
    """
    original_keys = set(os.environ)
    project_dir = _Path(__file__).resolve().parents[1]
    data_dir = _Path.home() / ".image2card"
    for path in (
        project_dir / ".env",
        project_dir / ".env.local",
        data_dir / ".env",
        data_dir / ".env.local",
    ):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key or key in original_keys:
                continue
            os.environ[key] = value.strip().strip("\"'")


_load_env_files()


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class CandidateStatus(Enum):
    """候选卡片在用户确认流程中的状态"""
    NEW = "new"
    EXISTING = "existing"
    FAMILIAR = "familiar"
    SIMILAR = "similar"
    IGNORED = "ignored"
    UNCERTAIN = "uncertain"
    CONFIRMED = "confirmed"


class RelationType(Enum):
    """卡片之间的关系类型（对应 Card.Edge.relation_type）"""
    RELATED_TO = "related_to"
    APPEARS_WITH = "appears_with"       # 同一张图片中共现（系统自动生成）
    IS_A = "is_a"
    PART_OF = "part_of"
    CONTRAST_WITH = "contrast_with"
    PREREQUISITE_OF = "prerequisite_of"


class ReviewRating(Enum):
    """复习时用户的四档反馈，对应 FSRS 标准输入"""
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


# ---------------------------------------------------------------------------
# 基础结构
# ---------------------------------------------------------------------------

class Link(NamedTuple):
    """互联网链接，NamedTuple 轻量且可哈希"""
    title: str
    url: str


@dataclass
class BoundingBox:
    """
    词条在图片中的像素位置区域。
    __post_init__ 保证构造后始终满足 x1 ≤ x2, y1 ≤ y2（top-left → bottom-right）。
    """
    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if self.x1 > self.x2:
            self.x1, self.x2 = self.x2, self.x1
        if self.y1 > self.y2:
            self.y1, self.y2 = self.y2, self.y1

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)


# ---------------------------------------------------------------------------
# 核心实体：工作区（Category）
# ---------------------------------------------------------------------------

# 预置调色板，UI 侧栏用
CATEGORY_COLORS: list[str] = [
    "#7c6df0", "#4a90d9", "#4caf50", "#ff9800",
    "#e74c3c", "#1abc9c", "#9b59b6", "#e67e22",
    "#2980b9", "#27ae60", "#c0392b", "#f39c12",
]


@dataclass
class Category:
    """
    工作区（Category）是系统最高层的组织单元。

    一个 Category 对应一批 Card + 一批 SourceImage + 一张知识图谱视图。
    例如："意大利旅行"、"线性代数期末"、"哲学导论"。

    name 是用户可见的自然键（唯一），Card.category / SourceImage.category
    均存储 name 字符串作为外键。rename() 负责同步更新所有引用。
    """
    name: str                          # 唯一自然键，用户可见
    description: str = ""
    color: str = "#7c6df0"            # 来自 CATEGORY_COLORS
    icon: str = "📁"                  # emoji 图标，侧栏展示用
    created_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# 核心实体：知识卡片
# ---------------------------------------------------------------------------

@dataclass
class Card:
    """
    知识卡片，系统核心存储单元。

    Card.Edge 作为内部类以邻接表方式存储在 Card.edges 中，
    KnowledgeBase 维护反向索引以支持入边查询。

    笔记分离原则：model_note 由模型生成，user_note 由用户编辑，
    模型更新不会覆盖 user_note。
    """

    @dataclass
    class Edge:
        """从当前卡片出发的一条有向边，构成邻接表。"""
        to_card_id: str
        relation_type: RelationType = RelationType.RELATED_TO
        weight: float = 1.0             # 关系强度，用于力导向图谱布局
        created_by: str = "user"        # "user" | "model" | "system"

    # --- 基本信息 ---
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    term: str = ""                  # 词条名，唯一自然键（不强制，但建议避免同名卡片）

    # --- 解释与笔记 ---
    summary: str = ""                   # 简短摘要（卡片列表预览用）
    model_note: str = ""                # 模型生成的详细解释
    user_note: str = ""                 # 用户自己的理解和笔记

    # --- 链接与来源 ---
    links: list[Link] = field(default_factory=list)
    source_image_ids: list[str] = field(default_factory=list)

    # --- 关系（邻接表） ---
    edges: list[Edge] = field(default_factory=list)

    # --- 熟悉度（0–5） ---
    familiarity: int = 0

    # --- 所属工作区（Category.name，空字符串表示未分类） ---
    category: str = ""

    # --- 时间戳 ---
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_reviewed_at: Optional[datetime] = None

    # --- FSRS 间隔重复调度参数（Ye et al., 2023） ---
    difficulty: float = 5.0
    stability: float = 1.0             # 记忆稳定性 S（单位：天）
    next_due: Optional[date] = None
    review_count: int = 0
    lapses: int = 0                    # 遗忘次数（Again 的累计次数）

    def retrievability(self, days_since_review: float) -> float:
        """
        当前可提取性 R（能回忆起来的概率）。
        FSRS 遗忘曲线：R(t) = (1 + t / (9·S))^{-1}
        """
        if self.stability <= 0:
            return 0.0
        return (1 + days_since_review / (9 * self.stability)) ** -1

    def add_edge(
        self,
        to_card_id: str,
        relation_type: RelationType = RelationType.RELATED_TO,
        weight: float = 1.0,
        created_by: str = "user",
    ) -> None:
        """添加一条出边，自动去重（相同目标 + 相同类型视为重复）"""
        for e in self.edges:
            if e.to_card_id == to_card_id and e.relation_type == relation_type:
                return
        self.edges.append(Card.Edge(to_card_id, relation_type, weight, created_by))


# ---------------------------------------------------------------------------
# 核心实体：来源图片
# ---------------------------------------------------------------------------

@dataclass
class SourceImage:
    """
    来源图片记录。图片是持久化的知识来源，不是一次性输入。
    analyze_result 在图片被 VLM 分析后填充，分析前为 None。

    card_ids 记录从该图片确认出的 Card，用于自动建立 APPEARS_WITH 关系。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    file_path: str = ""
    title: str = ""
    tags: list[str] = field(default_factory=list)
    scene_type: str = ""               # 如 "restaurant_menu"，由 VLM 识别后填入

    card_ids: list[str] = field(default_factory=list)

    # 所属工作区（Category.name），与卡片保持一致
    category: str = ""

    # VLM 分析结果；分析后必须填充，None 表示尚未分析
    analyze_result: Optional[AnalyzeResult] = None

    imported_at: datetime = field(default_factory=datetime.now)
    analyzed_at: Optional[datetime] = None

    @property
    def is_analyzed(self) -> bool:
        return self.analyze_result is not None


# ---------------------------------------------------------------------------
# VLM 输出 Pydantic 模型（JSON 可校验）
# ---------------------------------------------------------------------------

class VLMBBox(BaseModel):
    """
    VLM 返回的 bounding box。
    model_validator 在构造后规范化坐标，保证 x1 ≤ x2, y1 ≤ y2。
    """
    x1: float
    y1: float
    x2: float
    y2: float

    @model_validator(mode="after")
    def normalize_coords(self) -> "VLMBBox":
        if self.x1 > self.x2:
            self.x1, self.x2 = self.x2, self.x1
        if self.y1 > self.y2:
            self.y1, self.y2 = self.y2, self.y1
        return self

    def to_bbox(self) -> BoundingBox:
        """转换为内部 BoundingBox dataclass（坐标已规范化，无需再检查）"""
        return BoundingBox(self.x1, self.y1, self.x2, self.y2)


class VLMLink(BaseModel):
    """VLM 返回的链接条目"""
    title: str
    url: str

    def to_link(self) -> Link:
        return Link(self.title, self.url)


class VLMResultItem(BaseModel):
    """
    items 数组中的一个条目。
    代表图片中高置信识别出的词条，包括已有卡片（existing/familiar）。
    用于渲染 Captioned Image 覆盖层；status 决定高亮颜色。
    """
    original_text: str
    card: str                                       # 规范化词条名
    status: CandidateStatus = CandidateStatus.NEW
    card_id: Optional[str] = None                  # existing/familiar 时填已有卡片 id
    bbox: Optional[VLMBBox] = None
    bbox_confidence: float = Field(0.0, ge=0.0, le=1.0)


class VLMCandidateCard(BaseModel):
    """
    cards 数组中的一个条目，仅包含新词条（不在已有卡片库中）。
    用于生成候选卡片确认队列。
    """
    card: str                                       # 词条名
    card_summary: str = ""                         # 一句话简介（卡片预览用）
    model_content: str = ""                        # 2-4 句详细背景说明
    familiarity_suggestion: int = Field(0, ge=0, le=5)
    links: list[VLMLink] = Field(default_factory=list)
    related_terms: list[str] = Field(default_factory=list)


class AnalyzeResult(BaseModel):
    """
    VLM 对一张图片的完整分析结果。Pydantic 模型，支持 JSON 校验与序列化。

    items  → 高置信识别条目（含历史卡片），用于 Captioned Image 渲染
    cards  → 仅新词条子集，用于生成候选卡片确认队列
    """
    scene_type: str
    language: str
    summary: str
    items: list[VLMResultItem]
    cards: list[VLMCandidateCard]


# ---------------------------------------------------------------------------
# 复习记录
# ---------------------------------------------------------------------------

@dataclass
class ReviewLog:
    """单次复习记录，持久化到 review_log 表，用于 FSRS 统计分析"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    card_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    rating: ReviewRating = ReviewRating.GOOD
    stability_before: float = 0.0
    stability_after: float = 0.0
    retrievability_at_review: float = 0.0


# ---------------------------------------------------------------------------
# 全局状态：知识库
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """
    卡片库的全局状态，相当于内存中的数据库。
    管理所有 Card 和 SourceImage 的增删查，并为 VLM 调用提供卡片上下文。

    持久化（JSON / SQLite）由上层 Repository 层负责，本类只维护运行时状态。
    """

    def __init__(self) -> None:
        self._cards: dict[str, Card] = {}
        self._images: dict[str, SourceImage] = {}
        self._categories: dict[str, Category] = {}   # name → Category
        # 反向索引：card_id → 所有指向它的 (from_card_id, Edge)
        self._in_edges: dict[str, list[tuple[str, Card.Edge]]] = {}

    # --- 卡片 ---

    def add_card(self, card: Card) -> None:
        self._cards[card.id] = card
        for edge in card.edges:
            self._in_edges.setdefault(edge.to_card_id, []).append((card.id, edge))

    def remove_card(self, card_id: str) -> None:
        card = self._cards.pop(card_id, None)
        if card is None:
            return
        for edge in card.edges:
            bucket = self._in_edges.get(edge.to_card_id, [])
            self._in_edges[edge.to_card_id] = [(f, e) for f, e in bucket if f != card_id]
        self._in_edges.pop(card_id, None)

    def get_card(self, card_id: str) -> Optional[Card]:
        return self._cards.get(card_id)

    def find_by_term(self, term: str) -> Optional[Card]:
        """按词条名（大小写不敏感）查找卡片"""
        t = term.lower()
        for card in self._cards.values():
            if card.term.lower() == t:
                return card
        return None

    def all_cards(self) -> list[Card]:
        return list(self._cards.values())

    # --- 图片 ---

    def add_image(self, image: SourceImage) -> None:
        self._images[image.id] = image

    def remove_image(self, image_id: str) -> None:
        self._images.pop(image_id, None)

    def get_image(self, image_id: str) -> Optional[SourceImage]:
        return self._images.get(image_id)

    def all_images(self) -> list[SourceImage]:
        return list(self._images.values())

    # --- 关系 ---

    def in_edges(self, card_id: str) -> list[tuple[str, Card.Edge]]:
        """返回所有指向 card_id 的 (from_card_id, Edge) 对"""
        return self._in_edges.get(card_id, [])

    # --- VLM 上下文 ---

    def vlm_card_context(self, include_summary: bool = False, workspace: str = "") -> list[dict]:
        """
        返回供 VLM Prompt 使用的卡片摘要列表，让模型判断哪些词是 existing/familiar。
        
        Args:
            include_summary: 是否附带 summary（会增加 token 消耗）
            workspace: 限定工作区；空字符串表示不限制（全量）。
                       非空时仅返回同工作区的卡片（含"默认"工作区）。
        """
        result = []
        for card in self._cards.values():
            if workspace and not self._is_same_workspace(card.category, workspace):
                continue
            entry: dict = {
                "card_id": card.id,
                "card": card.term,

                "familiarity": card.familiarity,
            }
            if include_summary and card.summary:
                entry["card_summary"] = card.summary
            result.append(entry)
        return result

    @staticmethod
    def _is_same_workspace(card_category: str, target_workspace: str) -> bool:
        """
        判断卡片所属工作区是否与目标工作区属于"同一工作区"。
        
        当前规则：
          - card_category == target_workspace（同一工作区）
          - card_category == "默认"（默认工作区对所有工作区可见，作为共享池）
        
        未来可扩展（如层级工作区、共享工作区列表等）。
        """
        if not card_category or not target_workspace:
            return False
        if card_category == target_workspace:
            return True
        if card_category == "默认":
            return True
        return False

    # --- 工作区（Category）---

    def add_category(self, cat: Category) -> None:
        self._categories[cat.name] = cat

    def remove_category(self, name: str) -> None:
        self._categories.pop(name, None)

    def get_category(self, name: str) -> Optional[Category]:
        return self._categories.get(name)

    def all_categories(self) -> list[Category]:
        """返回所有 Category 实体，按 name 排序"""
        return sorted(self._categories.values(), key=lambda c: c.name)

    def category_names(self) -> list[str]:
        """返回所有类别名（含未注册但已被卡片引用的孤儿类别）"""
        registered = set(self._categories.keys())
        used = {c.category for c in self._cards.values() if c.category}
        return sorted(registered | used)

    def rename_category(self, old_name: str, new_name: str) -> None:
        """
        重命名类别，同步更新所有 Card.category 和 SourceImage.category。
        注意：持久化由上层 Repository/CardManager 负责。
        """
        cat = self._categories.pop(old_name, None)
        if cat:
            cat.name = new_name
            self._categories[new_name] = cat
        for card in self._cards.values():
            if card.category == old_name:
                card.category = new_name
        for image in self._images.values():
            if image.category == old_name:
                image.category = new_name

    def cards_by_category(self, category: str) -> list[Card]:
        """返回属于指定类别的所有卡片"""
        return [c for c in self._cards.values() if c.category == category]

    def images_by_category(self, category: str) -> list[SourceImage]:
        """返回属于指定类别的所有图片"""
        return [img for img in self._images.values() if img.category == category]


# ---------------------------------------------------------------------------
# 用户全局配置
# ---------------------------------------------------------------------------


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass
class UserConfig:
    """
    用户全局配置，持久化到 ~/.image2card/user_config.json。

    VLM 配置、数据目录、类别树、主题和复习设置均保存在此处。
    api_key 存储在本地 JSON 文件中，仅用于演示，生产环境建议使用系统密钥链。
    """

    # VLM API 设置
    vlm_provider: str = os.environ.get("VLM_PROVIDER", "openai")
    vlm_api_key: str = ""
    vlm_api_endpoint: str = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    vlm_model_name: str = os.environ.get("OPENAI_MODEL", "gpt-4o")
    vlm_wire_api: str = os.environ.get("OPENAI_WIRE_API", "chat")
    vlm_timeout_seconds: int = _env_int("OPENAI_TIMEOUT_SECONDS", 60)
    vlm_trust_env: bool = _env_bool("OPENAI_TRUST_ENV", False)
    vlm_mock_mode: bool = False
    vlm_verbose: bool = False

    # 数据存储目录
    data_dir: str = field(
        default_factory=lambda: str(_Path.home() / ".image2card")
    )

    # 界面主题：dark | light
    theme: str = "dark"

    # 字体缩放倍数（1.0 = 100%）
    font_scale: float = 1.0

    # 复习每日上限
    daily_review_limit: int = 20

    # 配置文件路径（类变量，不参与序列化）
    _CONFIG_PATH: ClassVar[str] = str(_Path.home() / ".image2card" / "user_config.json")

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def save(self) -> None:
        """将配置写入 JSON 文件"""
        path = _Path(self._CONFIG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "vlm_provider":     self.vlm_provider,
            "vlm_api_key":      self.vlm_api_key,
            "vlm_api_endpoint": self.vlm_api_endpoint,
            "vlm_model_name":   self.vlm_model_name,
            "vlm_wire_api":     self.vlm_wire_api,
            "vlm_timeout_seconds": self.vlm_timeout_seconds,
            "vlm_trust_env":    self.vlm_trust_env,
            "vlm_mock_mode":    self.vlm_mock_mode,
            "vlm_verbose":      self.vlm_verbose,
            "data_dir":         self.data_dir,
            "theme":            self.theme,
            "font_scale":       self.font_scale,
            "daily_review_limit": self.daily_review_limit,
        }
        path.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "UserConfig":
        """从 JSON 文件加载配置；文件不存在时返回默认配置。"""
        path = _Path(cls._CONFIG_PATH)
        if not path.exists():
            cfg = cls()
            cfg.save()
            return cfg
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            cfg = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            cfg._apply_env_compat_migration()
            cfg._apply_portable_data_dir()
            return cfg
        except Exception:
            return cls()

    def _apply_portable_data_dir(self) -> None:
        """
        Treat a copied ~/.image2card/user_config.json as portable.

        Older configs persist an absolute data_dir such as
        /Users/alice/.image2card. When that directory is copied to another
        machine, the config file itself lives under the current user's home,
        so an absent old-home .image2card should resolve to the current one.
        Custom existing data directories are left untouched.
        """
        default_dir = _Path.home() / ".image2card"
        configured = _Path(self.data_dir).expanduser()
        if configured == default_dir:
            self.data_dir = str(default_dir)
            return
        if configured.name == ".image2card" and not configured.exists() and default_dir.exists():
            self.data_dir = str(default_dir)

    def _apply_env_compat_migration(self) -> None:
        """
        Older configs defaulted to qwen. If the project-local env is clearly
        OpenAI-compatible and no DashScope key is configured, use that instead.
        """
        if self.vlm_provider.lower() not in {"qwen", "dashscope"}:
            return
        if self.vlm_api_key or os.environ.get("DASHSCOPE_API_KEY"):
            return
        if not os.environ.get("OPENAI_API_KEY"):
            return

        self.vlm_provider = os.environ.get("VLM_PROVIDER", "openai")
        self.vlm_api_endpoint = os.environ.get("OPENAI_BASE_URL", self.vlm_api_endpoint)
        self.vlm_model_name = os.environ.get("OPENAI_MODEL", self.vlm_model_name)
        self.vlm_wire_api = os.environ.get("OPENAI_WIRE_API", self.vlm_wire_api)
        self.vlm_timeout_seconds = _env_int("OPENAI_TIMEOUT_SECONDS", self.vlm_timeout_seconds)
        self.vlm_trust_env = _env_bool("OPENAI_TRUST_ENV", self.vlm_trust_env)

    def to_vlm_config(self):
        """将 VLM 相关字段转换为 VLMConfig（避免循环导入，延迟 import）"""
        from core.vlm import VLMConfig  # type: ignore
        return VLMConfig(
            provider=self.vlm_provider,
            api_key=self.vlm_api_key,
            api_endpoint=self.vlm_api_endpoint,
            model_name=self.vlm_model_name,
            wire_api=self.vlm_wire_api,
            timeout_seconds=self.vlm_timeout_seconds,
            trust_env=self.vlm_trust_env,
            mock_mode=self.vlm_mock_mode,
            verbose=self.vlm_verbose,
        )
