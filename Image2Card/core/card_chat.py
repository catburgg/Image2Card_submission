from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable

import httpx
from openai import OpenAI

from core.vlm import VLMConfig
from dataclass.models import Card

logger = logging.getLogger("image2card.card_chat")


@dataclass
class ChatTurn:
    role: str
    content: str


class CardChatService:
    """Text-only LLM helper for explaining selected cards."""

    def __init__(self, config: VLMConfig) -> None:
        self.config = config
        self._client: OpenAI | None = None

    def update_config(self, config: VLMConfig) -> None:
        self.config = config
        self._client = None

    def explain(
        self,
        cards: list[Card],
        prompt: str = "",
        history: Iterable[ChatTurn] | None = None,
    ) -> str:
        if not cards:
            raise ValueError("请先选择至少一张卡片")

        user_prompt = prompt.strip() or (
            "请用中文讲解这些卡片。先给整体关系，再逐张解释重点，最后给我一个适合复习的记忆线索。"
        )

        if self.config.mock_mode:
            return self._mock_response(cards, user_prompt)

        messages = self._build_messages(cards, user_prompt, list(history or []))
        return self._call_api(messages)

    def _build_messages(self, cards: list[Card], prompt: str, history: list[ChatTurn]) -> list[dict]:
        system = (
            "你是 Image2Card 的卡片讲解助手。"
            "用户会选择若干知识卡片，你需要基于卡片资料进行解释、比较、串联和复习提示。"
            "优先使用卡片中的模型简介、模型解释和用户笔记；不要编造卡片资料中没有依据的细节。"
            "如果用户提出自定义要求，按用户要求组织回答。回答默认使用中文，专有名词可保留原文。"
        )
        card_context = self._format_cards(cards)
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"以下是用户选中的卡片资料：\n\n{card_context}"},
        ]

        for turn in history[-8:]:
            if turn.role in {"user", "assistant"} and turn.content.strip():
                messages.append({"role": turn.role, "content": turn.content.strip()})

        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _format_cards(cards: list[Card]) -> str:
        blocks = []
        for idx, card in enumerate(cards, start=1):
            links = "\n".join(f"  - {link.title}: {link.url}" for link in card.links) or "  - 无"
            edge_terms = ", ".join(edge.to_card_id for edge in card.edges) or "无"
            block = (
                f"## {idx}. {card.term or '(未命名)'}\n"
                f"- 工作区: {card.category or '未分类'}\n"
                f"- 熟悉度: {card.familiarity}/5\n"
                f"- 简介: {card.summary or '无'}\n"
                f"- 模型解释: {card.model_note or '无'}\n"
                f"- 用户笔记: {card.user_note or '无'}\n"
                f"- 外部链接:\n{links}\n"
                f"- 关系边目标卡片ID: {edge_terms}"
            )
            blocks.append(block)
        return "\n\n".join(blocks)

    @staticmethod
    def _mock_response(cards: list[Card], prompt: str) -> str:
        terms = "、".join(card.term for card in cards if card.term) or "这些卡片"
        return (
            f"Mock 讲解：你选择了 {len(cards)} 张卡片：{terms}。\n\n"
            f"你的问题是：{prompt}\n\n"
            "可以先把它们当成一个小主题来复习：先读每张卡片的一句话简介，再比较它们的共同点和差异，"
            "最后用自己的话写一个 2-3 句总结。"
        )

    def _get_client(self) -> OpenAI:
        if self._client is None:
            provider = self.config.provider.lower()
            env_key_name = "DASHSCOPE_API_KEY" if provider in {"qwen", "dashscope"} else "OPENAI_API_KEY"
            api_key = self.config.api_key or os.getenv(env_key_name)
            if not api_key:
                if provider in {"qwen", "dashscope"}:
                    raise ValueError("缺少 DASHSCOPE_API_KEY。请在设置页填写 DashScope API Key。")
                raise ValueError("缺少 OPENAI_API_KEY。请在设置页填写 API Key，或在项目/.image2card 的 .env.local 中配置 OPENAI_API_KEY。")

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
        if self.config.wire_api.lower() == "responses":
            response = self._get_client().responses.create(
                model=self.config.model_name,
                input=self._to_responses_input(messages),
                timeout=self.config.timeout_seconds,
            )
            text = self._extract_responses_text(response)
            if text.strip():
                return text
            logger.warning("Responses API 返回空文本，尝试 Chat Completions")

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
            raise ValueError("Chat Completions API 返回空内容")
        return text

    @staticmethod
    def _to_responses_input(messages: list[dict]) -> list[dict]:
        return [
            {
                "role": msg["role"],
                "content": [{"type": "input_text", "text": str(msg.get("content", ""))}],
            }
            for msg in messages
        ]

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
        return "\n".join(chunks)
