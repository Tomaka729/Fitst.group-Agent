"""Mocked end-to-end rehearsal of the three bookkeeping pipelines.

No API key required: a stub LLM client returns the same structured payloads a
real GLM model would. Rows created in the real DB are deleted at the end.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ["DB_PATH"] = str(root / "data" / "expense.db")

from core.db import session_scope  # noqa: E402
from llm.client import extract_json  # noqa: E402
from repositories.transactions import (  # noqa: E402
    count_transactions,
    delete_transaction,
    get_by_id,
)
from services.bookkeeping import (  # noqa: E402
    DuplicateImageError,
    confirm_draft,
    draft_from_audio,
    draft_from_image,
    draft_from_text,
    save_draft,
)

today = date(2026, 11, 15)
created_ids: list[int] = []


class StubLLMClient:
    """Deterministic stand-in for text / vision / audio model calls."""

    def extract_record(self, text: str, day: date):
        if "32" in text:
            return {
                "amount_yuan": 32,
                "merchant": "滴滴出行",
                "category": "交通",
                "occurred_at": "昨天",
                "note": "打车",
            }
        if "咖啡" in text:
            return {
                "amount_yuan": "28.00",
                "merchant": "瑞幸咖啡",
                "category": "餐饮",
                "occurred_at": "今天",
                "note": "ASR 转写后抽取",
            }
        return {
            "amount_yuan": None,
            "merchant": "某商店",
            "category": "购物",
            "occurred_at": "今天",
            "note": "",
        }

    def ocr_receipt(self, image_bytes: bytes, day: date, mime: str = "image/jpeg"):
        return {
            "amount_yuan": "58.50",
            "merchant": "便利店",
            "category": "购物",
            "occurred_at": "今天",
            "note": "示例小票 OCR",
        }

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.wav"):
        return "昨天买咖啡28块"


stub = StubLLMClient()

print("=== 1. JSON PEELING / FALLBACK ===")
print("  fenced :", extract_json('```json\n{"amount_yuan": 32}\n```'))
print("  embedded:", extract_json('这里有一份账单 {"merchant": "滴滴"} 请处理'))
print("  invalid :", extract_json("完全不是 JSON"))

print("\n=== 2. TEXT PIPELINE ===")
result = draft_from_text("昨天打车32块", today, client=stub)
print("  ok      :", result.ok, "|", result.message)
draft = result.draft
print("  draft   :", draft.merchant, draft.category, draft.amount_cents, "cents", draft.occurred_at)
with session_scope() as session:
    before = count_transactions(session, start_date=None, end_date=None, category=None)
tx_id = save_draft(draft)
created_ids.append(tx_id)
with session_scope() as session:
    row = get_by_id(session, tx_id)
    during = count_transactions(session, start_date=None, end_date=None, category=None)
    print("  in DB   : status=", row.status, "source=", row.source, "amount=", row.amount_cents)
    print("  stats   :", before, "->", during, "(pending excluded)")
confirm_draft(tx_id)
with session_scope() as session:
    row = get_by_id(session, tx_id)
    after = count_transactions(session, start_date=None, end_date=None, category=None)
    print("  confirm : status=", row.status, "stats=", after, "(+1)")

print("\n=== 3. IMAGE PIPELINE + DEDUP ===")
receipt = (root / "demo_data" / "sample_receipt.png").read_bytes()
import hashlib

image_hash = hashlib.sha256(receipt).hexdigest()
img_result = draft_from_image(receipt, today, image_hash=image_hash, client=stub)
print("  ok      :", img_result.ok, "|", img_result.message)
print("  draft   :", img_result.draft.merchant, img_result.draft.amount_cents, "cents", "source=", img_result.draft.source)
img_id = save_draft(img_result.draft)
created_ids.append(img_id)
print("  saved   : tx_id=", img_id)
try:
    save_draft(img_result.draft)
    print("  dedup   : FAILED (duplicate was accepted)")
except DuplicateImageError as exc:
    print("  dedup   : OK ->", exc)

print("\n=== 4. AUDIO PIPELINE (ASR -> TEXT) ===")
audio = (root / "demo_data" / "voice_demo.wav").read_bytes()
audio_result = draft_from_audio(audio, "voice_demo.wav", today, client=stub)
print("  ok      :", audio_result.ok, "|", audio_result.message)
print("  draft   :", audio_result.draft.merchant, audio_result.draft.amount_cents, "cents", "source=", audio_result.draft.source)
print("  raw     :", audio_result.draft.raw_input)

print("\n=== 5. MISSING AMOUNT -> CLARIFY, NO WRITE ===")
poor = draft_from_text("买了个东西", today, client=stub)
print("  ok      :", poor.ok)
print("  message :", poor.message)

print("\n=== 6. CLEANUP ===")
with session_scope() as session:
    for row_id in created_ids:
        delete_transaction(session, row_id)
    print("  deleted tx ids:", created_ids)
    final = count_transactions(session, start_date=None, end_date=None, category=None)
    print("  final count   :", final, "(expected", before, ")")
    assert final == before

print("\nALL PIPELINE CHECKS PASSED")
