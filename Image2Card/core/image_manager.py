"""
ImageAnalysisService — 图片分析完整流程

将"图片上传 → VLM 分析 → AnalyzeResult 与 KB 比对 → 生成候选列表"
的完整流程封装为一个服务类。

CandidateManager 负责候选的确认/忽略流程，本类只负责分析阶段。

公共接口::

    svc = ImageAnalysisService(kb, repo, parser)

    # 添加图片（注册并保存为来源，不分析）
    image = svc.add_image("path/to/menu.jpg", title="罗马餐厅")

    # 分析图片（调用 VLM）
    result = svc.analyze(image.id, scene_hint="restaurant menu")

    # 获取图片的卡片列表
    cards = svc.get_cards_for_image(image.id)

    # 重新分析（覆盖旧结果）
    result = svc.re_analyze(image.id)
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from dataclass.models import (
    AnalyzeResult,
    KnowledgeBase,
    SourceImage,
    Card,
)
from storage.repository import Repository
from core.vlm import ImageParser, VLMInput, VLMConfig
from core.candidate import CandidateManager, PendingCandidate
from core.recognition import filter_high_confidence_result
from core.ocr_service import OCRService

logger = logging.getLogger("image2card.image_manager")


class ImageAnalysisService:
    """
    图片生命周期管理 + VLM 分析流程服务。

    职责划分：
      - 添加、删除来源图片（注册到 KB + 持久化）
      - 触发 VLM 分析，更新 SourceImage.analyze_result
      - 将分析结果与 KB 比对（EXISTING / FAMILIAR 标注）
      - 提供对 CandidateManager 的便捷封装

    VLMConfig 由调用方（AppContext）在初始化时传入，
    支持在运行时热更新（调用 update_config）。
    """

    def __init__(
        self,
        kb: KnowledgeBase,
        repo: Repository,
        vlm_config: VLMConfig,
        image_store_dir: str = "",
        persist_images: bool = True,
        ocr_service: OCRService | None = None,
    ) -> None:
        self._kb       = kb
        self._repo     = repo
        self._parser   = ImageParser(vlm_config)
        self._store_dir = Path(image_store_dir) if image_store_dir else None
        self._persist_images = persist_images
        self._ocr_service = ocr_service

        # 每次调用 analyze() 都会重新生成 CandidateManager
        self._candidate_mgr: Optional[CandidateManager] = None

    # ------------------------------------------------------------------
    # 配置热更新
    # ------------------------------------------------------------------

    def update_config(self, vlm_config: VLMConfig) -> None:
        """运行时更新 VLM 配置（切换模型/API Key 后调用）"""
        self._parser = ImageParser(vlm_config)
        logger.info("VLM 配置已更新：provider=%s model=%s mock=%s",
                    vlm_config.provider, vlm_config.model_name, vlm_config.mock_mode)

    # ------------------------------------------------------------------
    # 图片注册
    # ------------------------------------------------------------------

    def add_image(
        self,
        file_path: str,
        title: str = "",
        tags: Optional[list[str]] = None,
        category: str = "",
    ) -> SourceImage:
        """
        将图片注册到 KnowledgeBase，可选地将文件拷贝到 image_store_dir。
        category 对应 Category.name，空字符串表示未分类。
        不触发 VLM 分析。
        """
        src = Path(file_path)
        if not src.is_file():
            raise FileNotFoundError(f"图片文件不存在：{file_path}")

        # 可选：将图片拷贝到统一存储目录。默认开启，用于保留来源图片。
        stored_path = str(src)
        if self._persist_images and self._store_dir is not None:
            self._store_dir.mkdir(parents=True, exist_ok=True)
            dest = self._store_dir / src.name
            # 若目标已存在则加时间戳后缀避免覆盖
            if dest.exists() and dest.resolve() != src.resolve():
                suffix = datetime.now().strftime("%Y%m%d%H%M%S")
                dest = self._store_dir / f"{src.stem}_{suffix}{src.suffix}"
            if dest.resolve() != src.resolve():
                shutil.copy2(str(src), str(dest))
            stored_path = str(dest)

        image = SourceImage(
            file_path=stored_path,
            title=title or src.stem,
            tags=tags or [],
            category=category,
        )

        self._kb.add_image(image)
        if self._persist_images:
            self._repo.save_image(image)
        logger.info("add_image: %s (id=%s, category=%r)", image.file_path, image.id, category)
        return image

    def discard_persisted_images(self, *, remove_stored_files: bool = False) -> None:
        """清理旧版本遗留图片记录；卡片保留，只移除来源图片引用。"""
        for card in self._kb.all_cards():
            card.source_image_ids = []

        for image in list(self._kb.all_images()):
            self._kb.remove_image(image.id)

        self._repo.discard_images_and_source_refs()
        self._candidate_mgr = None

        if remove_stored_files:
            self._clear_image_store()

    def _clear_image_store(self) -> None:
        if self._store_dir is None or not self._store_dir.exists():
            return
        for child in self._store_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)

    def delete_image(self, image_id: str, *, remove_stored_file: bool = False) -> None:
        """从 KB 和数据库删除图片记录；可安全删除应用图片目录中的存储文件。"""
        image = self._kb.get_image(image_id)
        if image is None:
            logger.warning("delete_image: %s 不存在", image_id)
            return
        stored_path = Path(image.file_path)

        # 保留卡片本体，只移除这张图片作为来源的引用。
        for card in self._kb.all_cards():
            if image_id in card.source_image_ids:
                card.source_image_ids = [
                    source_id for source_id in card.source_image_ids
                    if source_id != image_id
                ]
                self._repo.save_card(card)

        self._repo.delete_image(image_id)
        self._kb.remove_image(image_id)

        if self._candidate_mgr is not None:
            if any(c.image_id == image_id for c in self._candidate_mgr.all_pending()):
                self._candidate_mgr = None

        if remove_stored_file:
            self._delete_stored_image_file(stored_path)

        logger.info("delete_image: %s", image_id)

    def _delete_stored_image_file(self, path: Path) -> None:
        if self._store_dir is None:
            return
        try:
            resolved = path.resolve()
            store_dir = self._store_dir.resolve()
            resolved.relative_to(store_dir)
        except ValueError:
            logger.warning("delete_image: 跳过非应用图片目录文件 %s", path)
            return
        except OSError as exc:
            logger.warning("delete_image: 解析图片路径失败 %s: %s", path, exc)
            return

        try:
            if resolved.is_file():
                resolved.unlink()
        except OSError as exc:
            logger.warning("delete_image: 删除图片文件失败 %s: %s", resolved, exc)

    def get_image(self, image_id: str) -> Optional[SourceImage]:
        return self._kb.get_image(image_id)

    def all_images(self) -> list[SourceImage]:
        return self._kb.all_images()

    # ------------------------------------------------------------------
    # VLM 分析
    # ------------------------------------------------------------------

    def analyze(
        self,
        image_id: str,
        scene_hint: str = "",
        rejected_terms: Optional[list[str]] = None,
    ) -> tuple[AnalyzeResult, list[PendingCandidate]]:
        """
        对指定图片触发 VLM 分析，返回 (AnalyzeResult, 候选列表)。

        流程：
          1. 构建 VLMInput（附带当前 KB 卡片上下文 + 用户拒绝词条）
          2. 调用 ImageParser.parse()
          3. 更新 SourceImage.analyze_result 并持久化
          4. 通过 CandidateManager 生成候选列表
        
        Args:
            image_id: 图片 ID
            scene_hint: 场景提示（可选）
            rejected_terms: 用户拒绝的词条列表（可选，用于指导 LLM）
        """
        image = self._kb.get_image(image_id)
        if image is None:
            raise KeyError(f"图片 {image_id!r} 不存在，请先调用 add_image()")

        logger.info("analyze: 开始分析图片 %s", image.file_path)

        # ── 先跑 OCR，将结果作为 VLM 的文本上下文 ─────────────────────────
        ocr_context = ""
        if self._ocr_service is not None:
            try:
                ocr_context = self._ocr_service.recognize(image.file_path)
                ocr_lines = ocr_context.strip().split("\n")
                logger.info(
                    "OCR 识别完成，共 %d 行，结果：\n%s",
                    len(ocr_lines), ocr_context,
                )
            except Exception as exc:
                logger.warning("OCR 识别失败，跳过 OCR 上下文：%s", exc)

        vlm_input = VLMInput(
            image_path=image.file_path,
            config=self._parser.config,
            card_context=self._kb.vlm_card_context(
                include_summary=False,
                workspace=image.category,
            ),
            scene_hint=scene_hint,
            ocr_context=ocr_context,
            rejected_terms=rejected_terms or [],
        )

        result = filter_high_confidence_result(self._parser.parse(vlm_input))

        # 更新 SourceImage；默认持久化图片记录。
        image.analyze_result = result
        image.scene_type     = result.scene_type
        image.analyzed_at    = datetime.now()
        if self._persist_images:
            self._repo.save_image(image)

        # 生成候选列表
        self._candidate_mgr = CandidateManager(self._kb, self._repo)
        candidates = self._candidate_mgr.process(result, image_id)

        logger.info(
            "analyze 完成：scene=%s items=%d candidates=%d",
            result.scene_type, len(result.items), len(candidates),
        )
        return result, candidates

    def re_analyze(
        self,
        image_id: str,
        scene_hint: str = "",
    ) -> tuple[AnalyzeResult, list[PendingCandidate]]:
        """重新分析已分析过的图片（覆盖旧结果）"""
        logger.info("re_analyze: 重新分析图片 %s", image_id)
        return self.analyze(image_id, scene_hint=scene_hint)

    # ------------------------------------------------------------------
    # 候选管理器访问
    # ------------------------------------------------------------------

    @property
    def candidate_manager(self) -> Optional[CandidateManager]:
        """返回最近一次 analyze() 生成的 CandidateManager"""
        return self._candidate_mgr

    def require_candidate_manager(self) -> CandidateManager:
        """返回 CandidateManager，若尚未分析则抛出 RuntimeError"""
        if self._candidate_mgr is None:
            raise RuntimeError("尚未分析任何图片，请先调用 analyze()")
        return self._candidate_mgr

    # ------------------------------------------------------------------
    # 便捷：一键分析 + 全量确认
    # ------------------------------------------------------------------

    def analyze_and_confirm_all(
        self,
        image_id: str,
        scene_hint: str = "",
    ) -> tuple[AnalyzeResult, list[Card]]:
        """
        分析图片并批量确认所有 NEW 候选，一步完成。
        适用于快速导入场景（用户不需要逐个确认）。
        """
        result, _ = self.analyze(image_id, scene_hint=scene_hint)
        mgr = self.require_candidate_manager()
        cards = mgr.confirm_all_new()

        # 自动建立 APPEARS_WITH 关系
        if cards:
            mgr.auto_link_confirmed([c.id for c in cards])

        logger.info("analyze_and_confirm_all: 图片=%s 共确认 %d 张卡片", image_id, len(cards))
        return result, cards

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_cards_for_image(self, image_id: str) -> list[Card]:
        """返回与指定图片关联的所有已确认卡片"""
        image = self._kb.get_image(image_id)
        if image is None:
            return []
        cards = []
        for card_id in image.card_ids:
            card = self._kb.get_card(card_id)
            if card:
                cards.append(card)
        return cards
