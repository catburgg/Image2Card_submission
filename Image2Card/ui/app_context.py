"""
AppContext — 全局应用上下文（单例）

持有所有后端服务实例：
  KnowledgeBase、Repository、ReviewEngine、GraphEngine、
  CardManager、SearchEngine、ImageAnalysisService、UserConfig

作为所有 UI 页面的共享数据层，避免到处传参。

用法::

    ctx = AppContext.instance()
    ctx.card_mgr.create(term="Carbonara")
    ctx.search.suggest("Car")
    ctx.image_svc.analyze(image_id)
"""

from __future__ import annotations

import logging
from pathlib import Path

from dataclass.models import KnowledgeBase, UserConfig
from storage.repository import Repository
from core.review import ReviewEngine
from core.graph import GraphEngine
from core.card_manager import CardManager
from core.card_chat import CardChatService
from core.search import SearchEngine
from core.image_manager import ImageAnalysisService
from core.ocr_service import OCRService
from core.user_preferences import UserPreferences

logger = logging.getLogger("image2card.app")


class AppContext:
    """应用全局单例上下文"""

    _instance: "AppContext | None" = None

    def __init__(self) -> None:
        self.config   = UserConfig.load()
        data_dir      = Path(self.config.data_dir).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)

        # 存储层
        self.repo     = Repository(str(data_dir / "cards.db"))
        self.repo.repair_portable_image_paths()
        self.kb       = self.repo.load_knowledge_base()

        # 核心服务
        self.review   = ReviewEngine()
        self.graph    = GraphEngine()
        self.card_mgr = CardManager(self.kb, self.repo)
        self.search   = SearchEngine(self.kb)
        self.card_chat = CardChatService(self.config.to_vlm_config())

        # OCR 服务（预加载 PP-OCR 模型到内存，降低首次分析延迟）
        # 可通过环境变量 OCR_DEVICE 覆盖设备（默认 cpu）
        self.ocr      = OCRService(
            cache_dir=self.config.ocr_cache_dir if hasattr(self.config, "ocr_cache_dir") else "",
        )

        # 图片分析服务（VLM 配置来自 UserConfig）
        image_store   = str(data_dir / "images")
        self.image_svc = ImageAnalysisService(
            kb=self.kb,
            repo=self.repo,
            vlm_config=self.config.to_vlm_config(),
            image_store_dir=image_store,
            persist_images=True,
            ocr_service=self.ocr,
        )

        # 用户偏好（拒绝词条等）
        self.user_prefs = UserPreferences(str(data_dir))

        logger.info("AppContext 初始化完成，数据目录：%s", data_dir)

    @classmethod
    def instance(cls) -> "AppContext":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """测试或重新加载时清除单例"""
        cls._instance = None

    def save_config(self) -> None:
        self.config.save()
        # 同步更新 image_svc 的 VLM 配置
        self.image_svc.update_config(self.config.to_vlm_config())
        self.card_chat.update_config(self.config.to_vlm_config())
