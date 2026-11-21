"""纯函数校验：金额换算、草稿校验、日期与分类归一化。不依赖 Streamlit / ORM。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from core.models import CATEGORIES, SOURCES

CENTS_PER_YUAN = 100


class ValidationError(ValueError):
    """字段缺失或非法。"""


def yuan_to_cents(value: Any) -> int:
    """把「元」转成整数分：Decimal(str(x)) * 100，杜绝 0.29*100=28.99 的浮点误差。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError("金额缺失")
    if isinstance(value, bool):
        raise ValidationError("金额非法")
    try:
        amount = Decimal(str(value).strip().replace(",", "").replace("元", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"金额非法: {value!r}") from exc
    cents = amount * CENTS_PER_YUAN
    if cents != cents.to_integral_value():
        raise ValidationError("金额精度超过分，请核对")
    if cents <= 0:
        raise ValidationError("金额必须大于 0")
    return int(cents)


def cents_to_yuan(cents: int) -> Decimal:
    """分转元，返回 Decimal 供展示或进一步计算。"""
    return (Decimal(cents) / CENTS_PER_YUAN).quantize(Decimal("0.01"))


def normalize_category(value: Any) -> str:
    """把模型给的分类收敛到 8 个固定类，未命中归「其他」。"""
    if not isinstance(value, str):
        return "其他"
    text = value.strip()
    if text in CATEGORIES:
        return text
    # 常见别名兜底
    aliases = {
        "餐饮": ("吃", "饭", "餐", "外卖", "food", "dining"),
        "交通": ("车", "行", "打车", "地铁", "公交", "taxi", "transport"),
        "购物": ("购", "买", "商城", "shopping"),
        "居住": ("房租", "水电", "物业", "housing", "rent"),
        "娱乐": ("玩", "电影", "游戏", "娱乐", "entertainment"),
        "医疗": ("医院", "药", "看病", "medical"),
        "学习": ("书", "课", "培训", "education", "study"),
    }
    lowered = text.lower()
    for canonical, keywords in aliases.items():
        if any(k in lowered for k in keywords):
            return canonical
    return "其他"


_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y年%m月%d日",
    "%m月%d日",
)


def parse_occurred_at(value: Any, today: date | None = None) -> date:
    """解析日期：支持 ISO、中文日期，以及「今天/昨天/前天/N天前」。空值默认今天。"""
    today = today or date.today()
    if value is None or (isinstance(value, str) and not value.strip()):
        return today
    text = str(value).strip()

    relative = {"今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2}
    if text in relative:
        return today - timedelta(days=relative[text])
    match = re.fullmatch(r"(\d+)天前", text)
    if match:
        return today - timedelta(days=int(match.group(1)))

    for pattern in _DATE_PATTERNS:
        try:
            parsed = datetime.strptime(text, pattern).date()
            if "%Y" not in pattern:
                parsed = parsed.replace(year=today.year)
            return parsed
        except ValueError:
            continue
    raise ValidationError(f"日期无法解析: {value!r}")


def month_key(value: date | str) -> str:
    """把日期或 'YYYY-MM' 归一到 'YYYY-MM'。"""
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return text
    raise ValidationError(f"月份格式非法: {value!r}")


@dataclass
class RecordDraft:
    """模型抽取结果的中间结构。校验通过后才允许确认入库。"""

    merchant: str
    category: str
    occurred_at: date
    amount_cents: int
    note: str = ""
    source: str = "text"
    raw_input: str = ""
    image_hash: str | None = None
    fill_clarifications: list[str] = field(default_factory=list)
    merchant_inferred: bool = False  # 原始输入没给商户，用类别占位（仍允许用户在确认前修正）

    @classmethod
    def from_model_payload(
        cls,
        payload: dict[str, Any],
        *,
        source: str,
        raw_input: str,
        today: date | None = None,
        image_hash: str | None = None,
    ) -> "RecordDraft":
        """把模型 JSON 转成草稿；金额在这里统一转分，分类在这里收敛。"""
        today = today or date.today()
        merchant = str(payload.get("merchant") or "").strip()
        category = normalize_category(payload.get("category"))
        note = str(payload.get("note") or "").strip()

        clarifications: list[str] = []
        merchant_inferred = False
        if not merchant:
            # 商户不是必填项：用「类别消费」占位，避免「午饭 25」这类无商户输入被反问。
            # 该占位不编造具体店名，且在确认前用户可自行修正。
            merchant = f"{category}消费"
            merchant_inferred = True

        amount_raw = payload.get("amount_yuan")
        try:
            amount_cents = yuan_to_cents(amount_raw)
        except ValidationError:
            amount_cents = 0
            clarifications.append("没识别到金额，请直接告诉我数字（例如 32）。")

        try:
            occurred_at = parse_occurred_at(payload.get("occurred_at"), today=today)
        except ValidationError:
            occurred_at = today
            clarifications.append("日期没看懂，已暂按今天记录，如需修改请在确认前调整。")

        if source not in SOURCES:
            source = "text"

        return cls(
            merchant=merchant,
            category=category,
            occurred_at=occurred_at,
            amount_cents=amount_cents,
            note=note,
            source=source,
            raw_input=raw_input,
            image_hash=image_hash,
            fill_clarifications=clarifications,
            merchant_inferred=merchant_inferred,
        )

    @property
    def is_valid(self) -> bool:
        return not self.fill_clarifications and self.amount_cents > 0

    def clarify_message(self) -> str:
        return "；".join(self.fill_clarifications)
