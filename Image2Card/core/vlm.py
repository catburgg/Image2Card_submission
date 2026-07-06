"""
VLM 调用层：ImageParser

负责将 VLMInput（图片 + 配置 + 已有卡片上下文）发送给视觉语言模型，
校验返回的 JSON，并在格式出错时自动要求模型修正，最终返回 AnalyzeResult。

公共接口：
    ImageParser(config: VLMConfig) -> parser
    parser.parse(vlm_input: VLMInput) -> AnalyzeResult
"""

import base64
import io
import json
import logging
import logging.handlers
import mimetypes
import os
import re
from pathlib import Path


def _load_local_env() -> None:
    """Load project-local env files without requiring shell-level exports."""
    root = Path(__file__).parent.parent
    for name in (".env.local", ".env"):
        path = root / name
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


_load_local_env()

# ---------------------------------------------------------------------------
# 日志配置：同时输出到控制台和日志文件
# ---------------------------------------------------------------------------

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("image2card.vlm")
    if logger.handlers:          # 避免重复添加 handler
        return logger
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(fmt)

    # 文件 handler（按大小轮转，最大 5 MB × 3 份）
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "vlm.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


_logger = _setup_logger()

import httpx
from openai import OpenAI
from PIL import Image, ImageOps
from pydantic import ValidationError

# 从数据层导入所需类型
from dataclass.models import AnalyzeResult
from core.recognition import RECOGNITION_CONFIDENCE_THRESHOLD
from dataclasses import dataclass, field

_MAX_IMAGE_UPLOAD_BYTES = 4 * 1024 * 1024
_MAX_IMAGE_DIMENSION = 2048
_JPEG_QUALITIES = (88, 82, 76, 70, 64, 58)

# ---------------------------------------------------------------------------
# VLM 配置与输入（独立给 VLM 层使用）
# ---------------------------------------------------------------------------

@dataclass
class VLMConfig:
    """
    视觉语言模型识别器的 API 配置。
    api_key 存储时应加密或存入系统密钥链，不明文写入 JSON。
    """
    provider: str = os.environ.get("VLM_PROVIDER", "openai")  # openai | qwen | gemini | claude | custom | mock
    api_endpoint: str = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")  # 自定义 base_url
    api_key: str = os.environ.get("OPENAI_API_KEY", "")  # 优先使用环境变量，避免硬编码
    model_name: str = os.environ.get("OPENAI_MODEL", "gpt-4o")
    wire_api: str = os.environ.get("OPENAI_WIRE_API", "chat")  # chat | responses
    timeout_seconds: int = int(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60"))
    trust_env: bool = os.environ.get("OPENAI_TRUST_ENV", "false").lower() in {"1", "true", "yes", "on"}
    mock_mode: bool = False            # 开启后返回预置 demo 数据，不发起实际请求
    verbose: bool = False              # 是否输出详细日志

    def __post_init__(self) -> None:
        """兼容旧的 DashScope/Qwen 配置，同时保留 UI 中显式保存的值。"""
        if self.provider.lower() in {"qwen", "dashscope"}:
            self.api_endpoint = os.environ.get(
                "DASHSCOPE_API_ENDPOINT",
                self.api_endpoint or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            self.api_key = os.environ.get("DASHSCOPE_API_KEY", self.api_key)
            self.model_name = os.environ.get("DASHSCOPE_MODEL", self.model_name or "qwen3.6-plus")
            self.wire_api = "chat"

@dataclass
class VLMInput:
    """
    单次 VLM 调用的完整输入，由调用方在每次分析前从 KnowledgeBase 构造。

    card_context  ← KnowledgeBase.vlm_card_context()
    scene_hint    ← 用户指定的场景提示，如 "restaurant menu"（可为空）
    ocr_context   ← OCRService.recognize() 的格式化输出，作为额外文本上下文
    rejected_terms ← 用户拒绝的词条列表（用于指导 LLM 不重复推荐）
    """
    image_path: str
    config: VLMConfig
    card_context: list[dict] = field(default_factory=list)
    scene_hint: str = ""
    ocr_context: str = ""
    rejected_terms: list[str] = field(default_factory=list)  # 用户拒绝的词条


# ---------------------------------------------------------------------------
# System prompt 模板
# ---------------------------------------------------------------------------

_MOCK_RESULT_JSON = """{
  "scene_type": "restaurant_menu",
  "language": "Italian",
  "summary": "An Italian restaurant menu featuring pasta and dessert items.",
  "items": [
    {
      "original_text": "Spaghetti Carbonara",
      "card": "Carbonara",
      "status": "new",
      "card_id": null,
      "bbox": {"x1": 120, "y1": 240, "x2": 300, "y2": 272},
      "bbox_confidence": 0.96
    },
    {
      "original_text": "Tiramisù",
      "card": "Tiramisu",
      "status": "new",
      "card_id": null,
      "bbox": {"x1": 120, "y1": 290, "x2": 250, "y2": 318},
      "bbox_confidence": 0.94
    }
  ],
  "cards": [
    {
      "card": "Carbonara",

      "card_summary": "Carbonara 是一道经典的罗马传统意面，以鸡蛋、Pecorino Romano 奶酪、Guanciale 猪脸肉和黑胡椒为核心食材。",
      "model_content": "Spaghetti Carbonara 起源于意大利罗马，是当地最具代表性的家常意面之一。其标志性的奶滑口感并非来自奶油，而是将热意面与生鸡蛋液快速拌匀，利用余温使蛋液凝固成丝绸般的酱汁。正宗做法使用 Guanciale（猪脸颊肉）而非培根，并以 Pecorino Romano 硬奶酪增添咸鲜风味。",
      "familiarity_suggestion": 1,
      "links": [{"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Carbonara"}],
      "bbox": {"x1": 120, "y1": 240, "x2": 300, "y2": 272},
      "related_terms": ["Guanciale", "Pecorino Romano", "Tiramisu"]
    },
    {
      "card": "Tiramisu",

      "card_summary": "Tiramisu 是意大利经典咖啡风味甜点，以 Mascarpone 奶酪、浓缩咖啡浸泡的手指饼干和可可粉层叠制成。",
      "model_content": "Tiramisu 发源于意大利威尼托大区，名字在意大利语中意为「提振精神」。制作时将手指饼干（Ladyfinger）浸入浓缩咖啡，再与 Mascarpone 奶酪和蛋黄打发的混合物交替铺层，最后筛上可可粉。整道甜点无需烘烤，冷藏后食用风味更佳。",
      "familiarity_suggestion": 2,
      "links": [{"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Tiramisu"}],
      "bbox": {"x1": 120, "y1": 290, "x2": 250, "y2": 318},
      "related_terms": ["Mascarpone", "Carbonara"]
    }
  ]
}"""


# 占位符：{scene_hint}  {card_list}
_SYSTEM_PROMPT_TEMPLATE = """\
You are an image knowledge extractor for a flashcard learning system.
Analyze the provided image and identify knowledge items worth turning into flashcards.

{scene_hint_block}

## Output format — return ONLY a single JSON object, no markdown, no explanation

{{
  "scene_type": "<detected scene, e.g. restaurant_menu | textbook | math_homework | paper | museum | general>",
  "language": "<primary language visible in the image>",
  "summary": "<one sentence describing the image content>",
  "items": [
    {{
      "original_text": "<exact text as it appears in the image>",
      "card": "<canonical term name (normalized/translated if needed)>",
      "status": "<new | existing | familiar | uncertain>",
      "card_id": "<card_id from existing cards if status is existing or familiar, otherwise null>",
      "bbox": {{"x1": 0, "y1": 0, "x2": 100, "y2": 50}},
      "bbox_confidence": 0.0
    }}
  ],
  "cards": [
        {{
      "card": "<term name, must match the corresponding item's card field>",
      "card_summary": "<一句话简介，中文为主，专有名词保留英文原文>",
      "model_content": "<2-4句背景介绍，中文为主，专有名词保留英文原文，适合初学者阅读>",
      "familiarity_suggestion": "<int from 0 to 5 indicating how familiar this term is to a general audience, where 0 means very unfamiliar and 5 means very familiar>",
      "links": [{{"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/..."}}, {{"title": "Baidu Baike", "url": "https://baike.baidu.com/item/..."}}],  # 可选，提供相关链接, 不一定是wikipedia, baidu这种权威百科，也可以是专业网站、论坛、视频等资源
      "related_terms": ["<other term names from this image>"]
    }}
  ]
}}




## Field rules

items — list all significant terms in the image that pass the recognition confidence threshold, including existing ones:
  status "new"      : term is NOT in the existing card list → must also appear in cards
  status "existing" : term matches an existing card (familiarity < 4) → set card_id
  status "familiar" : term matches an existing card with familiarity >= 4 → set card_id
  status "uncertain": you are unsure if this term is worth a card
  
Each returned item is treated as successfully recognized by the app.
If you do not think one term is worth making a card, it can be omitted from items and cards.

For bounding boxes, you will be provided with a reliable OCR result that detects words(sentences/phrases) and their bounding boxes. You only need to select which words are worth making cards, and return the corresponding bbox for those words. A sample OCR result is the following:
     #    Conf    BBox (x0,y0,x1,y1)    Word
     1  0.9754     (29,174,275,200)     CHICKEN SCHNITZEL
     2  0.8928    (598,168,770,204)     22.9(M|25.9(NM)
     3  0.9509     (29,212,460,229)     Premium chicken breast schnitzel roll..
     
For short phrases, the bbox should **be exactly as the provided BoundingBox of the OCR result**. If the term is a short phrase that is part of a longer detected line, it is acceptable to return a tighter bbox that only covers the exact term, as long as you are very confident about the exact location. Some of these words in sentences should be parsed, even if they are not highlighted in the image.

But do not guess or infer bbox if you are not sure, and do not return an approximate bbox that covers a large area around the term. If the exact location is uncertain, it is better fall back to the given bbox by the OCR result.
  Prefer fewer high-confidence boxes over many approximate boxes.
  At most 12 items may be returned. If more terms are valuable, choose the highest-confidence ones and omit the rest.

cards — list ONLY truly new terms (status = "new" or "uncertain"); do NOT repeat existing cards here. Is equivalent to the items with status "new" or "uncertain", but with more detailed information. The card field must match the corresponding item's card field.

## Existing cards  (mark as existing/familiar in items; do NOT add these to cards)
{card_list}

## Rejected terms (skip these in new discoveries; user explicitly rejected them)
{rejected_terms_block}

"""


# ---------------------------------------------------------------------------
# 模拟结果（mock_mode 使用，方便离线演示）
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _load_image_as_data_url(image_path: str) -> str:
    """
    将本地图片读取并编码为 Base64 Data URL，供 OpenAI 兼容 API 的 image_url 字段使用。
    支持 JPG / PNG / WEBP / BMP；超过上传限制时自动缩放压缩，不修改原文件。
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在：{image_path}")

    raw = path.read_bytes()
    mime, _ = mimetypes.guess_type(str(path))
    if not mime or not mime.startswith("image/"):
        ext = path.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp",
                "bmp": "image/bmp"}.get(ext, "image/jpeg")

    payload = raw
    try:
        with Image.open(path) as image:
            width, height = image.size
            needs_reencode = (
                len(raw) > _MAX_IMAGE_UPLOAD_BYTES
                or max(width, height) > _MAX_IMAGE_DIMENSION
            )
            if needs_reencode:
                payload = _compress_image_for_upload(image, path.name, len(raw))
                mime = "image/jpeg"
    except Exception as exc:
        if len(raw) > _MAX_IMAGE_UPLOAD_BYTES:
            raise ValueError(f"图片 {path.name} 超过 4 MB，自动压缩失败：{exc}") from exc
        _logger.warning("读取图片尺寸失败，使用原图上传：%s", exc)

    b64 = base64.b64encode(payload).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _compress_image_for_upload(image: Image.Image, name: str, original_size: int) -> bytes:
    """将图片压缩到 VLM 上传限制内，返回 JPEG bytes。"""
    original_dimensions = image.size
    img = ImageOps.exif_transpose(image)

    if max(img.size) > _MAX_IMAGE_DIMENSION:
        img.thumbnail((_MAX_IMAGE_DIMENSION, _MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

    if img.mode in {"RGBA", "LA"} or "transparency" in img.info:
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    for quality in _JPEG_QUALITIES:
        payload = _encode_jpeg(img, quality)
        if len(payload) <= _MAX_IMAGE_UPLOAD_BYTES:
            _logger.info(
                "图片自动压缩：%s %dx%d %.2fMB -> %dx%d %.2fMB quality=%d",
                name,
                original_dimensions[0],
                original_dimensions[1],
                original_size / (1024 * 1024),
                img.size[0],
                img.size[1],
                len(payload) / (1024 * 1024),
                quality,
            )
            return payload

    resized = img
    while max(resized.size) > 1024:
        new_size = (max(1, int(resized.size[0] * 0.85)), max(1, int(resized.size[1] * 0.85)))
        resized = resized.resize(new_size, Image.Resampling.LANCZOS)
        payload = _encode_jpeg(resized, _JPEG_QUALITIES[-1])
        if len(payload) <= _MAX_IMAGE_UPLOAD_BYTES:
            _logger.info(
                "图片自动压缩：%s %dx%d %.2fMB -> %dx%d %.2fMB quality=%d",
                name,
                original_dimensions[0],
                original_dimensions[1],
                original_size / (1024 * 1024),
                resized.size[0],
                resized.size[1],
                len(payload) / (1024 * 1024),
                _JPEG_QUALITIES[-1],
            )
            return payload

    raise ValueError("压缩后仍超过上传限制")


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def _redact_images(messages: list[dict]) -> str:
    """
    将 messages 中的 base64 图片 Data URL 替换为 <image_url> 占位符，
    避免日志中出现大量 base64 噪声。
    """
    import copy
    safe = copy.deepcopy(messages)
    for msg in safe:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        part["image_url"]["url"] = "<image_url>"
    return json.dumps(safe, ensure_ascii=False, indent=2)


def _extract_json(text: str) -> str:
    """
    从模型回复中提取 JSON 字符串。
    处理以下情况：
      - 纯 JSON
      - ```json ... ``` 代码块
      - 夹杂在解释文字中的 JSON（抓取第一个 { ... } 块）
    """
    text = text.strip()

    # 优先匹配 ```json 代码块
    m = re.search(r"```json\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()

    # 普通代码块
    m = re.search(r"```\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()

    # 尝试提取首个顶层 JSON 对象
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

    return text  # 最后兜底，原样返回让 Pydantic 报错


# ---------------------------------------------------------------------------
# ImageParser
# ---------------------------------------------------------------------------

class ImageParser:
    """
    调用视觉语言模型，将图片解析为结构化的 AnalyzeResult。

    流程：
      1. 构建 system prompt（含已有卡片上下文 + 有效词条类型）
      2. 调用 VLM API，传入图片和 prompt
      3. 用 Pydantic（AnalyzeResult）校验返回的 JSON
      4. 若校验失败，将错误信息反馈给模型，最多重试 MAX_FIX_RETRIES 次
      5. 超出重试次数后抛出 ValueError

    mock_mode = True 时直接返回预置 demo 结果，不发起网络请求。
    """

    MAX_FIX_RETRIES: int = 2

    def __init__(self, config: VLMConfig) -> None:
        self.config = config
        self._client: OpenAI | None = None  # 延迟初始化，避免 mock 时建立连接
        self._log = _logger
        # verbose=False 时将控制台 handler 提升到 WARNING，只保留文件完整记录
        if not config.verbose:
            for h in self._log.handlers:
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                    h.setLevel(logging.WARNING)
    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def parse(self, vlm_input: VLMInput) -> AnalyzeResult:
        """解析图片，返回经过 Pydantic 校验的 AnalyzeResult。"""
        if self.config.mock_mode:
            self._log.info("mock_mode=True — 返回预置 mock 数据，不调用 API")
            return AnalyzeResult.model_validate_json(_MOCK_RESULT_JSON)

        self._log.info("开始解析图片：%s", vlm_input.image_path)
        messages = self._build_messages(vlm_input)
        self._log.debug("构建请求 messages（共 %d 条）：\n%s", len(messages), _redact_images(messages))
        raw = self._call_api(messages)
        self._log.debug("API 原始返回：\n%s", raw)
        return self._validate_with_fix(raw, messages)

    # ------------------------------------------------------------------
    # 内部：构建请求
    # ------------------------------------------------------------------

    def _build_system_prompt(self, vlm_input: VLMInput) -> str:
        scene_hint_block = (
            f"Scene context provided by user: {vlm_input.scene_hint}"
            if vlm_input.scene_hint
            else ""
        )
        card_list = (
            json.dumps(vlm_input.card_context, ensure_ascii=False, indent=2)
            if vlm_input.card_context
            else "(none — this is the first image; all terms are new)"
        )
        
        # 拒绝词条提示
        rejected_terms_block = ""
        if vlm_input.rejected_terms:
            rejected_list = ", ".join(vlm_input.rejected_terms[:30])  # 最多列出 30 个
            rejected_terms_block = f"User rejected these terms, do not re-discover them: {rejected_list}"
        else:
            rejected_terms_block = "(none)"

        return _SYSTEM_PROMPT_TEMPLATE.format(
            scene_hint_block=scene_hint_block,
            card_list=card_list,
            rejected_terms_block=rejected_terms_block,
            recognition_confidence_threshold=f"{RECOGNITION_CONFIDENCE_THRESHOLD:.2f}",
        ) + f"\n Sample JSON: {_MOCK_RESULT_JSON} \n"

    def _build_messages(self, vlm_input: VLMInput) -> list[dict]:
        system_prompt = self._build_system_prompt(vlm_input)
        data_url = _load_image_as_data_url(vlm_input.image_path)

        user_content: list[dict] = [
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        user_text_parts = ["请分析这张图片，严格按照要求的 JSON 格式返回结果，不要包含任何其他内容。"]

        # ── 附带 OCR 上下文 ──────────────────────────────────────────────
        if vlm_input.ocr_context:
            ocr_lines = vlm_input.ocr_context.strip().split("\n")
            self._log.info(
                "OCR 上下文已传入（共 %d 行），前 5 行：\n%s",
                len(ocr_lines),
                "\n".join(ocr_lines[:5]),
            )
            # 拼上表头，与 system prompt 中的 OCR 示例格式一致
            ocr_header = "     #    Conf    BBox (x0,y0,x1,y1)    Word"
            ocr_block = ocr_header + "\n" + vlm_input.ocr_context
            user_text_parts.insert(
                0,
                "以下是本图片的 OCR 检测结果：\n" + ocr_block + "\n\n---\n",
            )
        else:
            self._log.info("OCR 上下文为空，未传入 VLM")

        user_text = "\n".join(user_text_parts)
        user_content.append({"type": "text", "text": user_text})

        self._log.info("User message 文本内容：\n%s", user_text)

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    # ------------------------------------------------------------------
    # 内部：API 调用
    # ------------------------------------------------------------------

    def _get_client(self) -> OpenAI:
        """延迟初始化 OpenAI 客户端"""
        if self._client is None:
            provider = self.config.provider.lower()
            if provider in {"qwen", "dashscope"}:
                env_key_name = "DASHSCOPE_API_KEY"
            else:
                env_key_name = "OPENAI_API_KEY"

            api_key = self.config.api_key or os.getenv(env_key_name)
            if not api_key:
                if provider in {"qwen", "dashscope"}:
                    hint = "缺少 DASHSCOPE_API_KEY。请在设置页填写 DashScope API Key，或将 Provider 改为 openai 使用 OPENAI_API_KEY。"
                else:
                    hint = "缺少 OPENAI_API_KEY。请在设置页填写 API Key，或在项目/.image2card 的 .env.local 中配置 OPENAI_API_KEY。"
                raise ValueError(
                    hint
                )
            self._client = OpenAI(
                api_key=api_key,
                base_url=self._normalize_base_url(self.config.api_endpoint),
                http_client=httpx.Client(trust_env=self.config.trust_env),
            )
        return self._client

    @staticmethod
    def _normalize_base_url(api_endpoint: str) -> str | None:
        endpoint = (api_endpoint or "").strip().rstrip("/")
        if not endpoint:
            return None
        if endpoint.endswith("/v1"):
            return endpoint
        return f"{endpoint}/v1"

    def _call_api(self, messages: list[dict]) -> str:
        """调用 API，返回模型回复的原始文本"""
        if self.config.wire_api.lower() == "responses":
            response = self._get_client().responses.create(
                model=self.config.model_name,
                input=self._to_responses_input(messages),
                timeout=self.config.timeout_seconds,
            )
            text = self._extract_responses_text(response)
            if text.strip():
                return text
            self._log.warning(
                "Responses API 返回 200 但没有可用文本内容，响应摘要：%s",
                self._response_debug_dump(response),
            )
            self.config.wire_api = "chat"
            self._log.info("尝试使用 Chat Completions wire API 重试一次")
            try:
                return self._call_chat_completions(messages)
            except Exception as exc:
                raise ValueError(
                    "Responses API 返回空内容，且 Chat Completions 退路也失败。"
                    "这通常不是 API key 问题；请在设置页把 Wire API 改为 chat，"
                    "或确认当前 Base URL/模型是否真正支持 /responses。"
                ) from exc

        return self._call_chat_completions(messages)

    def _call_chat_completions(self, messages: list[dict]) -> str:
        """Call Chat Completions-compatible endpoint and return message text."""
        request_kwargs = {
            "model": self.config.model_name,
            "messages": messages,
            "timeout": self.config.timeout_seconds,
        }
        if self.config.provider.lower() in {"qwen", "dashscope"}:
            request_kwargs["extra_body"] = {"enable_search": True}

        response = self._get_client().chat.completions.create(**request_kwargs)
        text = response.choices[0].message.content or ""
        if not text.strip():
            self._log.warning(
                "Chat Completions API 返回空内容，响应摘要：%s",
                self._response_debug_dump(response),
            )
            raise ValueError("Chat Completions API 返回空内容")
        return text

    @staticmethod
    def _to_responses_input(messages: list[dict]) -> list[dict]:
        """Convert Chat Completions-style messages to Responses API input."""
        converted = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                converted.append({
                    "role": msg["role"],
                    "content": [{"type": "input_text", "text": content}],
                })
                continue

            parts = []
            for part in content:
                if part.get("type") == "text":
                    parts.append({"type": "input_text", "text": part.get("text", "")})
                elif part.get("type") == "image_url":
                    parts.append({
                        "type": "input_image",
                        "image_url": part.get("image_url", {}).get("url", ""),
                        "detail": "auto",
                    })
            converted.append({"role": msg["role"], "content": parts})
        return converted

    @staticmethod
    def _extract_responses_text(response) -> str:
        try:
            text = getattr(response, "output_text", None)
        except TypeError:
            text = None
        if text:
            return text

        chunks = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                chunk = getattr(content, "text", None)
                if chunk:
                    chunks.append(chunk)
        if chunks:
            return "\n".join(chunks)

        try:
            data = response.model_dump(mode="python")
        except Exception:
            data = response if isinstance(response, dict) else {}

        if isinstance(data, dict):
            output_text = data.get("output_text")
            if isinstance(output_text, str) and output_text.strip():
                return output_text

            for item in data.get("output", []) or []:
                if not isinstance(item, dict):
                    continue
                for content in item.get("content", []) or []:
                    if not isinstance(content, dict):
                        continue
                    chunk = content.get("text")
                    if isinstance(chunk, str) and chunk.strip():
                        chunks.append(chunk)

            for choice in data.get("choices", []) or []:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message") or {}
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, str) and content.strip():
                    chunks.append(content)
        return "\n".join(chunks)

    @staticmethod
    def _response_debug_dump(response) -> str:
        try:
            text = response.model_dump_json(indent=2)
        except Exception:
            try:
                text = json.dumps(response, ensure_ascii=False, default=str, indent=2)
            except Exception:
                text = repr(response)
        return text[:4000]

    # ------------------------------------------------------------------
    # 内部：校验与自动修正
    # ------------------------------------------------------------------

    def _validate_with_fix(
        self,
        raw: str,
        original_messages: list[dict],
    ) -> AnalyzeResult:
        """
        尝试解析并校验 JSON。失败时将错误反馈给模型，最多重试 MAX_FIX_RETRIES 次。
        所有重试均失败后抛出 ValueError。
        """
        messages = list(original_messages)  # 拷贝，不修改原始消息
        for attempt in range(self.MAX_FIX_RETRIES + 1):
            try:
                json_str = _extract_json(raw)
                return AnalyzeResult.model_validate_json(json_str)

            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                if attempt == self.MAX_FIX_RETRIES:
                    self._log.error(
                        "JSON 校验失败，已达最大重试次数 %d。最后错误：%s",
                        self.MAX_FIX_RETRIES, exc,
                    )
                    raise ValueError(
                        f"VLM 返回的 JSON 经过 {self.MAX_FIX_RETRIES} 次修正仍无法通过校验。\n"
                        f"最后一次错误：{exc}\n"
                        f"原始内容：\n{raw}"
                    ) from exc

                # 将错误反馈给模型，要求重新输出
                error_msg = str(exc)
                self._log.warning("第 %d 次校验失败，反馈错误给模型重试：%s", attempt + 1, error_msg)
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            f"Your JSON output failed validation with the following error:\n{error_msg}\n\n"
                            "Please return ONLY the corrected JSON object. "
                            "Do not include markdown, code blocks, or any explanation."
                        ),
                    },
                ]
                raw = self._call_api(messages)
