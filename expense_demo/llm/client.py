"""GLM（OpenAI 兼容）调用封装：统一 temperature=0、JSON 剥壳、重试与降级。"""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date
from typing import Any

from openai import OpenAI

from core.config import Settings, load_settings
from llm import prompts

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEY = "not-configured"  # 仅在未配置 Key 时构造 client 用，不会发出有效请求


def extract_json(text: str | None) -> dict[str, Any] | None:
    """剥掉 ```json 外壳；失败则用正则抓首个 {...}，仍失败返回 None。"""
    if not text or not text.strip():
        return None
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
    return None


class LLMClient:
    """对上层只暴露语义方法，屏蔽 SDK 细节与错误。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self._client: OpenAI | None = None

    @property
    def ready(self) -> bool:
        return self.settings.llm_ready

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.api_key or _PLACEHOLDER_KEY,
                base_url=self.settings.base_url,
                timeout=60.0,
                max_retries=0,
            )
        return self._client

    def _chat_json(self, system: str, user_content: Any, model: str) -> dict[str, Any] | None:
        """一次调用 + 一次重试；首次带 response_format，重试时去掉以兼容不支持的模型。"""
        if not self.ready:
            logger.info("LLM 未配置 API Key，跳过调用")
            return None
        for attempt in range(2):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0,
                }
                if attempt == 0:
                    kwargs["response_format"] = {"type": "json_object"}
                # GLM-5.x 强制开启思考，默认 max 档很慢；若配置了档位则透传（low/high/max）。
                # 留空则不传，避免不认识该参数的兼容端点报错。
                if self.settings.reasoning_effort:
                    kwargs["reasoning_effort"] = self.settings.reasoning_effort
                response = self._get_client().chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                parsed = extract_json(content)
                if parsed is None:
                    raise ValueError(f"无法解析 JSON: {content!r}")
                return parsed
            except Exception as exc:  # noqa: BLE001 - 对外统一返回 None
                logger.warning("LLM 调用失败(attempt=%s): %s", attempt + 1, exc)
        return None

    def extract_record(self, text: str, today: date) -> dict[str, Any] | None:
        return self._chat_json(
            prompts.SYSTEM_RECORD_EXTRACT,
            prompts.build_record_user_message(text, today),
            self.settings.model_text,
        )

    def parse_query_intent(self, question: str, today: date) -> dict[str, Any] | None:
        return self._chat_json(
            prompts.SYSTEM_QUERY_INTENT,
            prompts.build_query_user_message(question, today),
            self.settings.model_text,
        )

    def ocr_receipt(self, image_bytes: bytes, today: date, mime: str = "image/jpeg") -> dict[str, Any] | None:
        """把图片以 base64 data URL 传给视觉模型，返回结构化字段。"""
        if not self.ready:
            return None
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompts.build_ocr_user_message(today)},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]
        return self._chat_json(prompts.SYSTEM_OCR, content, self.settings.model_vision)

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.wav") -> str | None:
        """ASR：调用智谱 /audio/transcriptions（OpenAI 兼容）。
        模型名用 glm-asr-2512（官方当前值）；stream=false 保证返回完整文本而非流式块。
        若账号无该能力，可替换本方法为 Whisper/讯飞实现。"""
        if not self.ready:
            return None
        try:
            response = self._get_client().audio.transcriptions.create(
                model=self.settings.model_audio,
                file=(filename, audio_bytes),
                stream=False,
            )
            text = getattr(response, "text", None)
            return text.strip() if isinstance(text, str) and text.strip() else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("ASR 调用失败: %s", exc)
            return None
