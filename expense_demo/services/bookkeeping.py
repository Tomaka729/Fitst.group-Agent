"""记账业务服务：三种输入收敛成草稿，用户确认后才写入 confirmed。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from core.db import session_scope
from core.validators import RecordDraft
from llm.client import LLMClient

from repositories import transactions as repo


class DuplicateImageError(ValueError):
    """同一张图片已入库，避免重复记账。"""


@dataclass
class DraftResult:
    ok: bool
    message: str
    draft: RecordDraft | None = None


_LLM_DOWN_HINT = "AI 服务暂不可用（未配置 Key 或调用失败）。请在 .env 填 ZAI_API_KEY 并重建容器；未填 Key 时仅「统计」页可用。"


def draft_from_text(text: str, today: date, client: LLMClient | None = None) -> DraftResult:
    text = (text or "").strip()
    if not text:
        return DraftResult(False, "请先说一句要记的账，例如「昨天打车 32 块」。")
    client = client or LLMClient()
    payload = client.extract_record(text, today)
    if payload is None:
        return DraftResult(False, _LLM_DOWN_HINT)

    draft = RecordDraft.from_model_payload(payload, source="text", raw_input=text, today=today)
    if not draft.is_valid:
        return DraftResult(False, draft.clarify_message())
    message = "已抽出草稿，请核对后确认入库。"
    if draft.merchant_inferred:
        message = "已抽出草稿（没提到商户，已按类别占位，确认前可修正），请核对后确认入库。"
    return DraftResult(True, message, draft)


def draft_from_image(
    image_bytes: bytes,
    today: date,
    *,
    mime: str = "image/jpeg",
    image_hash: str | None = None,
    client: LLMClient | None = None,
) -> DraftResult:
    client = client or LLMClient()
    payload = client.ocr_receipt(image_bytes, today, mime=mime)
    if payload is None:
        return DraftResult(False, _LLM_DOWN_HINT)

    draft = RecordDraft.from_model_payload(
        payload,
        source="image",
        raw_input="[图片小票]",
        today=today,
        image_hash=image_hash,
    )
    if not draft.is_valid:
        if draft.amount_cents == 0:
            return DraftResult(False, "图片太模糊，没识别到金额。请换张清晰的小票，或改用文字记账。")
        return DraftResult(False, draft.clarify_message())
    message = "已识别小票，请核对后确认入库。"
    if draft.merchant_inferred:
        message = "已识别小票（没看清商户，已按类别占位，确认前可修正），请核对后确认入库。"
    return DraftResult(True, message, draft)


def draft_from_audio(
    audio_bytes: bytes,
    filename: str,
    today: date,
    *,
    client: LLMClient | None = None,
) -> DraftResult:
    client = client or LLMClient()
    transcript = client.transcribe_audio(audio_bytes, filename)
    if not transcript:
        return DraftResult(False, "没听清音频内容（或 ASR 不可用）。请重录一段，或改用文字记账。")
    # ASR 结果复用文字链路：结构化抽取与校验逻辑完全一致
    result = draft_from_text(transcript, today, client=client)
    if result.ok and result.draft is not None:
        result.draft.source = "audio"
        result.draft.raw_input = transcript
        result.message = "语音已转写并抽出草稿，请核对后确认入库。"
        if result.draft.merchant_inferred:
            result.message = "语音已转写并抽出草稿（没提到商户，已按类别占位），请核对后确认入库。"
    elif not result.ok and "AI 服务暂不可用" in result.message:
        result.message = "转写成功，但 AI 服务暂不可用，请稍后重试或改用文字记账。"
    return result


def save_draft(draft: RecordDraft) -> int:
    """草稿以 pending 落库，等待用户确认；统计不会计入 pending。"""
    with session_scope() as session:
        if draft.image_hash:
            existing = repo.find_by_image_hash(session, draft.image_hash)
            if existing is not None:
                raise DuplicateImageError("这张图片已经记过账了，已跳过重复录入。")
        tx = repo.create_transaction(
            session,
            amount_cents=draft.amount_cents,
            merchant=draft.merchant,
            category=draft.category,
            occurred_at=draft.occurred_at,
            note=draft.note,
            source=draft.source,
            status="pending",
            raw_input=draft.raw_input,
            image_hash=draft.image_hash,
        )
        return int(tx.id)


def confirm_draft(tx_id: int) -> bool:
    with session_scope() as session:
        return repo.confirm_transaction(session, tx_id) is not None


def correct_draft(tx_id: int, **changes: Any) -> bool:
    with session_scope() as session:
        return repo.update_transaction(session, tx_id, **changes) is not None


def discard_draft(tx_id: int) -> bool:
    with session_scope() as session:
        return repo.delete_transaction(session, tx_id)
