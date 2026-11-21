"""纯函数测试：金额元→分、草稿校验、日期与分类归一化。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.validators import (
    RecordDraft,
    ValidationError,
    cents_to_yuan,
    normalize_category,
    parse_occurred_at,
    yuan_to_cents,
)


def test_yuan_to_cents_float_precision():
    # 经典浮点陷阱：0.29 * 100 在 float 下是 28.999...
    assert yuan_to_cents("0.29") == 29
    assert yuan_to_cents(0.29) == 29
    assert yuan_to_cents("32") == 3200
    assert yuan_to_cents("1,234.50") == 123450
    assert yuan_to_cents("88.8") == 8880


def test_yuan_to_cents_rejects_bad_values():
    for bad in (None, "", "abc", 0, -5):
        with pytest.raises(ValidationError):
            yuan_to_cents(bad)


def test_cents_to_yuan_roundtrip():
    assert cents_to_yuan(29) == Decimal("0.29")
    assert cents_to_yuan(3200) == Decimal("32.00")


def test_record_draft_valid_from_payload():
    payload = {
        "merchant": "滴滴出行",
        "amount_yuan": 32,
        "category": "出行",  # 别名应归一到「交通」
        "occurred_at": "昨天",
        "note": "打车",
    }
    draft = RecordDraft.from_model_payload(
        payload, source="text", raw_input="昨天打车32块", today=date(2026, 11, 15)
    )
    assert draft.is_valid
    assert draft.amount_cents == 3200
    assert draft.category == "交通"
    assert draft.occurred_at == date(2026, 11, 14)


def test_record_draft_missing_amount_asks_clarification():
    payload = {"merchant": "食堂", "amount_yuan": None, "category": "餐饮"}
    draft = RecordDraft.from_model_payload(payload, source="text", raw_input="午饭", today=date(2026, 11, 15))
    assert not draft.is_valid
    assert "金额" in draft.clarify_message()


def test_record_draft_missing_merchant_uses_category_placeholder():
    """需求示例「午饭 25，和同事 AA」：无商户也应一次成草稿，不反问。"""
    payload = {
        "merchant": "",
        "amount_yuan": 25,
        "category": "餐饮",
        "occurred_at": None,
        "note": "和同事 AA",
    }
    draft = RecordDraft.from_model_payload(
        payload, source="text", raw_input="午饭 25，和同事 AA", today=date(2026, 11, 15)
    )
    assert draft.is_valid
    assert draft.merchant == "餐饮消费"
    assert draft.merchant_inferred is True
    assert draft.amount_cents == 2500
    assert draft.note == "和同事 AA"


def test_record_draft_missing_amount_still_clarifies():
    """商户可占位，但缺金额仍必须反问，绝不猜数。"""
    payload = {"merchant": "", "amount_yuan": None, "category": "餐饮"}
    draft = RecordDraft.from_model_payload(payload, source="text", raw_input="吃了顿饭", today=date(2026, 11, 15))
    assert not draft.is_valid
    assert "金额" in draft.clarify_message()


def test_draft_from_text_allows_no_merchant():
    from services.bookkeeping import draft_from_text

    class Stub:
        def extract_record(self, text, today):
            return {
                "merchant": "",
                "amount_yuan": 25,
                "category": "餐饮",
                "occurred_at": None,
                "note": "和同事 AA",
            }

    result = draft_from_text("午饭 25，和同事 AA", date(2026, 11, 15), client=Stub())
    assert result.ok
    assert result.draft is not None
    assert result.draft.amount_cents == 2500
    assert result.draft.merchant_inferred
    assert "占位" in result.message


def test_normalize_category_fallback():
    assert normalize_category("餐饮") == "餐饮"
    assert normalize_category("看电影") == "娱乐"
    assert normalize_category("不明类别") == "其他"
    assert normalize_category(None) == "其他"


def test_parse_occurred_at_relative_and_iso():
    today = date(2026, 11, 15)
    assert parse_occurred_at("今天", today) == today
    assert parse_occurred_at("前天", today) == date(2026, 11, 13)
    assert parse_occurred_at("2026-09-05", today) == date(2026, 9, 5)
