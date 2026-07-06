"""
OCR Service — 基于 PaddleOCR 的文字检测与识别服务

封装 PaddleOCR 的初始化和调用，支持预加载模型以消除冷启动延迟。
对外提供标准接口：recognize(image_path) -> str，返回格式化结果字符串。
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageOps

logger = logging.getLogger("image2card.ocr")


class OCRService:
    """OCR 识别服务，单例模式，初始化时自动加载 PP-OCR 模型。"""

    def __init__(
        self,
        device: str = "",
        cache_dir: str = "",
        det_model: str = "",
        rec_model: str = "",
    ) -> None:
        self._device = device or os.environ.get("OCR_DEVICE", "cpu")
        self._cache_dir = cache_dir
        self._det_model = det_model or os.environ.get("OCR_DET_MODEL", "PP-OCRv5_mobile_det")
        self._rec_model = rec_model or os.environ.get("OCR_REC_MODEL", "PP-OCRv5_mobile_rec")
        self._max_side = int(os.environ.get("OCR_MAX_SIDE", "1536"))
        self._min_confidence = float(os.environ.get("OCR_MIN_CONFIDENCE", "0.5"))
        self._ocr = None
        self._loaded = False
        self._load_error: Exception | None = None

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------

    def load_model(self) -> None:
        """加载 PP-OCR 模型。可在后台线程或启动时调用。"""
        if self._loaded:
            return
        t0 = time.time()
        try:
            if self._cache_dir:
                os.environ.setdefault("PADDLE_PDX_CACHE_HOME", self._cache_dir)
                os.environ.setdefault("PADDLEX_HOME", self._cache_dir)

            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                text_detection_model_name=self._det_model,
                text_recognition_model_name=self._rec_model,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
                device=self._device,
            )
            self._loaded = True
            logger.info("OCR 模型加载完成，耗时 %.1fs", time.time() - t0)
        except Exception as exc:
            self._load_error = exc
            logger.error("OCR 模型加载失败：%s", exc)

    def is_loaded(self) -> bool:
        return self._loaded

    def ensure_loaded(self) -> None:
        """确保模型已加载，若加载失败则抛出 RuntimeError。"""
        if not self._loaded:
            self.load_model()
        if self._load_error:
            raise RuntimeError("OCR 模型加载失败") from self._load_error

    # ------------------------------------------------------------------
    # 识别接口
    # ------------------------------------------------------------------

    def recognize(self, image_path: str) -> str:
        """
        对图片执行 OCR 识别，返回格式化的结果字符串。

        返回格式（空格对齐，与 system prompt 示例一致）：:

             #    Conf    BBox (x0,y0,x1,y1)    Word
             1  0.9754     (29,174,275,200)     CHICKEN SCHNITZEL

        若未检测到文字，返回 "(no text detected)"。
        """
        self.ensure_loaded()

        prepared_path, scale_x, scale_y, tmp_path = self._prepare_image_for_ocr(image_path)
        try:
            t0 = time.time()
            results = self._ocr.predict(prepared_path)
            elapsed = time.time() - t0
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

        res = results[0]  # single image

        polys = res["rec_polys"]  # (N, 4, 2)
        texts = res["rec_texts"]
        scores = res["rec_scores"]

        if len(polys) == 0 or len(texts) == 0:
            logger.info("OCR 未检测到文字（%.1fs）", elapsed)
            return "(no text detected)"

        lines = []
        for text, score, poly in zip(texts, scores, polys):
            if score < self._min_confidence:
                continue
            xs = [p[0] * scale_x for p in poly]
            ys = [p[1] * scale_y for p in poly]
            bbox_str = f"({int(min(xs))},{int(min(ys))},{int(max(xs))},{int(max(ys))})"
            idx = len(lines) + 1
            lines.append(f"{idx:>5}  {score:.4f}    {bbox_str:<22}  {text}")

        if not lines:
            logger.info("OCR 未检测到高置信文字（%.1fs）", elapsed)
            return "(no text detected)"

        result_str = "\n".join(lines)
        logger.info(
            "OCR 识别完成：%d/%d 个高置信词条，耗时 %.1fs",
            len(lines),
            len(texts),
            elapsed,
        )
        return result_str

    def _prepare_image_for_ocr(self, image_path: str) -> tuple[str, float, float, Path | None]:
        """
        PaddleOCR 对超大图的内存占用很高；进入 OCR 前先生成受控尺寸临时图。

        返回值为 (实际识别路径, x 坐标回原图缩放比, y 坐标回原图缩放比, 临时路径)。
        """
        path = Path(image_path)
        try:
            with Image.open(path) as raw_image:
                image = ImageOps.exif_transpose(raw_image)
                original_width, original_height = image.size

                if max(image.size) <= self._max_side:
                    return str(path), 1.0, 1.0, None

                image.thumbnail((self._max_side, self._max_side), Image.Resampling.LANCZOS)

                if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", rgba.size, (255, 255, 255))
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    image = background
                elif image.mode != "RGB":
                    image = image.convert("RGB")

                tmp_dir = Path(self._cache_dir or tempfile.gettempdir()) / "preprocessed"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    suffix=".jpg",
                    prefix=f"{path.stem}_ocr_",
                    dir=tmp_dir,
                    delete=False,
                ) as tmp:
                    tmp_path = Path(tmp.name)

                image.save(tmp_path, format="JPEG", quality=92, optimize=True)
                scale_x = original_width / image.size[0]
                scale_y = original_height / image.size[1]
                logger.info(
                    "OCR 输入图已缩放：%s %dx%d -> %dx%d",
                    path.name,
                    original_width,
                    original_height,
                    image.size[0],
                    image.size[1],
                )
                return str(tmp_path), scale_x, scale_y, tmp_path
        except Exception as exc:
            logger.warning("OCR 输入图预处理失败，使用原图：%s", exc)
            return str(path), 1.0, 1.0, None
