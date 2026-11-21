"""查账意图解析测试：mock 掉模型，只验证条件解析与 SQL 数字计算路径。"""
from __future__ import annotations

from datetime import date

from core.db import session_scope
from repositories import transactions as repo
from services import query


class FakeLLM:
    """固定返回一份意图 JSON，模拟模型输出。"""

    def __init__(self, payload):
        self.payload = payload

    def parse_query_intent(self, question, today):
        return self.payload


def test_parse_intent_normalizes_fields():
    intent = query.parse_intent(
        {
            "start_date": "2026-11-01",
            "end_date": "2026-11-15",
            "category": "餐饮",
            "metric": "sum",
        }
    )
    assert intent.start_date == date(2026, 11, 1)
    assert intent.end_date == date(2026, 11, 15)
    assert intent.category == "餐饮"
    assert intent.metric == "sum"


def test_parse_intent_swaps_reversed_dates_and_invalid_category():
    intent = query.parse_intent(
        {
            "start_date": "2026-11-15",
            "end_date": "2026-11-01",
            "category": "火星类别",
            "metric": "unknown",
        }
    )
    assert intent.start_date == date(2026, 11, 1)
    assert intent.end_date == date(2026, 11, 15)
    assert intent.category is None
    assert intent.metric == "sum"


def test_answer_query_computes_total_from_sql(monkeypatch):
    """数字由 SQL 算出：插入三条 confirmed + 一条 pending，验证 pending 不被计入。"""
    today = date(2026, 11, 15)
    with session_scope() as session:
        for amount, status in ((1000, "confirmed"), (2500, "confirmed"), (9999, "pending")):
            repo.create_transaction(
                session,
                amount_cents=amount,
                merchant="测试商户",
                category="餐饮",
                occurred_at=date(2026, 11, 5),
                note="",
                source="text",
                status=status,
                raw_input="test",
            )

    fake = FakeLLM(
        {
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
            "category": "餐饮",
            "metric": "sum",
        }
    )
    answer = query.answer_query("这个月餐饮花了多少", today, client=fake)
    assert answer.ok
    assert answer.total_cents == 3500  # 只算两条 confirmed
    assert answer.count == 2
    assert "35.00" in answer.message


def test_parse_intent_missing_category_is_not_other():
    """回归：模型没给类别时必须不加过滤，绝不能误当作「其他」类。"""
    for raw in (None, "", "   ", "不认识的类别"):
        assert query.parse_intent({"category": raw}).category is None


def test_parse_intent_keeps_explicit_other_and_aliases():
    assert query.parse_intent({"category": "其他"}).category == "其他"
    assert query.parse_intent({"category": "吃饭"}).category == "餐饮"


def test_parse_intent_accepts_rank_metric():
    assert query.parse_intent({"metric": "rank"}).metric == "rank"
    assert query.parse_intent({"metric": "unknown"}).metric == "sum"


def test_answer_query_without_category_counts_all(monkeypatch):
    """回归：「这个月花了多少」不应只统计「其他」类。"""
    today = date(2026, 11, 15)
    with session_scope() as session:
        repo.create_transaction(
            session,
            amount_cents=888800,
            merchant="商场",
            category="购物",
            occurred_at=date(2026, 11, 9),
            note="",
            source="text",
            status="confirmed",
            raw_input="no-category test",
        )
    fake = FakeLLM(
        {
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
            "category": None,
            "metric": "sum",
        }
    )
    answer = query.answer_query("这个月一共花了多少", today, client=fake)
    assert answer.ok
    assert answer.intent.category is None
    assert answer.total_cents >= 888800  # 购物那笔必须被算进去
    assert "其他" not in answer.message


def test_answer_query_rank_reports_top_category():
    """「这个月哪类花得最多」由 SQL 分组排序给出答案，模型不算数。"""
    today = date(2026, 11, 15)
    fake = FakeLLM(
        {
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
            "category": None,
            "metric": "rank",
        }
    )
    answer = query.answer_query("这个月哪类花得最多？", today, client=fake)
    assert answer.ok
    assert answer.intent.metric == "rank"
    assert answer.intent.category is None
    assert answer.ranking
    assert answer.ranking[0][0] == "购物"
    assert "花得最多的是「购物」" in answer.message
    # 排行按金额降序
    assert [cents for _, cents in answer.ranking] == sorted(
        (cents for _, cents in answer.ranking), reverse=True
    )
