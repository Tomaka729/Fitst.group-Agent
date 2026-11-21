"""查账服务：模型只把自然语言翻译成查询条件，所有数字由 SQL 算出。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

from core.db import session_scope
from core.models import CATEGORIES, Transaction
from core.validators import normalize_category
from llm.client import LLMClient

from repositories import transactions as repo

VALID_METRICS = ("sum", "count", "list", "rank")


@dataclass(frozen=True)
class QueryIntent:
    start_date: date | None
    end_date: date | None
    category: str | None
    metric: str  # sum / count / list / rank


@dataclass
class QueryAnswer:
    ok: bool
    message: str
    intent: QueryIntent | None = None
    total_cents: int = 0
    count: int = 0
    rows: Sequence[Transaction] = ()
    ranking: list[tuple[str, int]] = field(default_factory=list)


def _coerce_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _coerce_category(value: Any) -> str | None:
    """把模型给的类别收敛成 8 类之一；缺省/无效一律返回 None（= 不加类别过滤）。

    注意：normalize_category 对未知输入一律兜底成「其他」，因此必须显式区分
    「用户明确说了其他」与「模型没给类别」，否则空值会被误过滤成只查「其他」。
    """
    if value is None or not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text in CATEGORIES:
        return text
    normalized = normalize_category(text)
    return None if normalized == "其他" else normalized


def parse_intent(payload: dict[str, Any] | None) -> QueryIntent:
    """把模型 JSON 收敛成合法意图；日期非法则忽略，类别只认 8 类。"""
    payload = payload or {}
    start = _coerce_date(payload.get("start_date"))
    end = _coerce_date(payload.get("end_date"))
    if start and end and start > end:
        start, end = end, start

    category = _coerce_category(payload.get("category"))
    metric = str(payload.get("metric") or "sum").strip().lower()
    if metric not in VALID_METRICS:
        metric = "sum"
    return QueryIntent(start, end, category, metric)


def answer_query(question: str, today: date, client: LLMClient | None = None) -> QueryAnswer:
    question = (question or "").strip()
    if not question:
        return QueryAnswer(False, "请告诉我你想查什么，例如「上个月吃饭花了多少？」")

    client = client or LLMClient()
    payload = client.parse_query_intent(question, today)
    if payload is None:
        return QueryAnswer(False, "AI 服务暂不可用，无法解析你的问题。请检查 .env 的 ZAI_API_KEY 与网络后重试；你仍可在「统计」页查看示例数据。")

    intent = parse_intent(payload)
    with session_scope() as session:
        total = repo.sum_amount_cents(
            session, start_date=intent.start_date, end_date=intent.end_date, category=intent.category
        )
        count = repo.count_transactions(
            session, start_date=intent.start_date, end_date=intent.end_date, category=intent.category
        )
        rows: Sequence[Transaction] = ()
        ranking: list[tuple[str, int]] = []
        if intent.metric == "list":
            rows = repo.query_transactions(
                session,
                start_date=intent.start_date,
                end_date=intent.end_date,
                category=intent.category,
            )
        elif intent.metric == "rank":
            # 「哪类花得最多」必须按类别分组比较：忽略单一类别过滤，数字仍由 SQL 聚合
            ranking = repo.stats_by_category(
                session, start_date=intent.start_date, end_date=intent.end_date
            )

    scope = _describe_scope(intent, include_category=intent.metric != "rank")
    yuan = total / 100
    if intent.metric == "rank":
        if not ranking:
            message = f"{scope} 还没有已确认的支出，暂时无法比较哪类花得最多。"
        else:
            top_cents = ranking[0][1]
            tied = [name for name, cents in ranking if cents == top_cents]
            names = "、".join(f"「{name}」" for name in tied)
            suffix = f"（共 {len(ranking)} 个类别有支出，{count} 笔已确认记录），完整排行见下方。"
            if len(tied) > 1:
                message = f"{scope} 花得最多的是 {names}（并列），各 ¥{top_cents / 100:,.2f}{suffix}"
            else:
                message = f"{scope} 花得最多的是{names} ¥{top_cents / 100:,.2f}{suffix}"
    elif intent.metric == "count":
        message = f"{scope}共有 {count} 笔已确认记录。"
    elif intent.metric == "list":
        message = f"{scope}共 {count} 笔，明细见下方。"
    else:
        message = f"{scope}共花费 ¥{yuan:,.2f}（{count} 笔已确认记录）。"
    return QueryAnswer(True, message, intent, total, count, rows, ranking)


def _describe_scope(intent: QueryIntent, *, include_category: bool = True) -> str:
    parts: list[str] = []
    if intent.start_date and intent.end_date:
        parts.append(f"{intent.start_date.isoformat()} 至 {intent.end_date.isoformat()}")
    elif intent.start_date:
        parts.append(f"{intent.start_date.isoformat()} 之后")
    elif intent.end_date:
        parts.append(f"{intent.end_date.isoformat()} 之前")
    else:
        parts.append("全部时间")
    if include_category and intent.category:
        parts.append(f"「{intent.category}」")
    return " · ".join(parts)
