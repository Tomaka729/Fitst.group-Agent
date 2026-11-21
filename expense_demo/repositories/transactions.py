"""交易仓储层：只负责数据访问，统计相关查询一律过滤 status=confirmed。"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import CATEGORIES, Category, Transaction
from core.validators import month_key


def ensure_categories(session: Session) -> None:
    for name in CATEGORIES:
        if session.get(Category, name) is None:
            session.add(Category(name=name))


def create_transaction(
    session: Session,
    *,
    amount_cents: int,
    merchant: str,
    category: str,
    occurred_at: date,
    note: str,
    source: str,
    status: str,
    raw_input: str,
    image_hash: str | None = None,
) -> Transaction:
    tx = Transaction(
        amount_cents=amount_cents,
        merchant=merchant,
        category=category,
        occurred_at=occurred_at,
        note=note,
        source=source,
        status=status,
        raw_input=raw_input,
        image_hash=image_hash,
        created_at=datetime.now(),
    )
    session.add(tx)
    session.flush()
    return tx


def get_by_id(session: Session, tx_id: int) -> Transaction | None:
    return session.get(Transaction, tx_id)


def confirm_transaction(session: Session, tx_id: int) -> Transaction | None:
    tx = get_by_id(session, tx_id)
    if tx is not None:
        tx.status = "confirmed"
        session.flush()
    return tx


def update_transaction(
    session: Session,
    tx_id: int,
    *,
    amount_yuan: Any = None,
    merchant: str | None = None,
    category: str | None = None,
    occurred_at: date | None = None,
    note: str | None = None,
) -> Transaction | None:
    """确认前允许用户修正字段；金额以元传入，此处再做换算，保证入库是分。"""
    from core.validators import yuan_to_cents  # 局部导入避免与 validators 顶层耦合

    tx = get_by_id(session, tx_id)
    if tx is None:
        return None
    if amount_yuan not in (None, ""):
        tx.amount_cents = yuan_to_cents(amount_yuan)
    if merchant is not None:
        tx.merchant = merchant.strip()
    if category is not None:
        tx.category = category
    if occurred_at is not None:
        tx.occurred_at = occurred_at
    if note is not None:
        tx.note = note.strip()
    session.flush()
    return tx


def delete_transaction(session: Session, tx_id: int) -> bool:
    tx = get_by_id(session, tx_id)
    if tx is None:
        return False
    session.delete(tx)
    session.flush()
    return True


def find_by_image_hash(session: Session, image_hash: str) -> Transaction | None:
    return session.scalar(select(Transaction).where(Transaction.image_hash == image_hash).limit(1))


def list_transactions(
    session: Session,
    *,
    status: str | None = "confirmed",
    limit: int = 50,
) -> Sequence[Transaction]:
    stmt = select(Transaction)
    if status is not None:
        stmt = stmt.where(Transaction.status == status)
    stmt = stmt.order_by(Transaction.occurred_at.desc(), Transaction.id.desc()).limit(limit)
    return session.scalars(stmt).all()


def query_transactions(
    session: Session,
    *,
    start_date: date | None,
    end_date: date | None,
    category: str | None,
) -> Sequence[Transaction]:
    """查账明细查询：固定 status=confirmed，遵守数字只由 SQL/数据算出的原则。"""
    stmt = select(Transaction).where(Transaction.status == "confirmed")
    if start_date is not None:
        stmt = stmt.where(Transaction.occurred_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(Transaction.occurred_at <= end_date)
    if category is not None:
        stmt = stmt.where(Transaction.category == category)
    return session.scalars(stmt.order_by(Transaction.occurred_at.desc())).all()


def sum_amount_cents(
    session: Session,
    *,
    start_date: date | None,
    end_date: date | None,
    category: str | None,
) -> int:
    """所有金额聚合都走 SQL SUM，模型绝不参与算数。"""
    stmt = select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.status == "confirmed"
    )
    if start_date is not None:
        stmt = stmt.where(Transaction.occurred_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(Transaction.occurred_at <= end_date)
    if category is not None:
        stmt = stmt.where(Transaction.category == category)
    return int(session.scalar(stmt) or 0)


def count_transactions(
    session: Session,
    *,
    start_date: date | None,
    end_date: date | None,
    category: str | None,
) -> int:
    stmt = select(func.count(Transaction.id)).where(Transaction.status == "confirmed")
    if start_date is not None:
        stmt = stmt.where(Transaction.occurred_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(Transaction.occurred_at <= end_date)
    if category is not None:
        stmt = stmt.where(Transaction.category == category)
    return int(session.scalar(stmt) or 0)


def stats_by_category(
    session: Session, *, start_date: date | None, end_date: date | None
) -> list[tuple[str, int]]:
    stmt = (
        select(Transaction.category, func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(Transaction.status == "confirmed")
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount_cents).desc())
    )
    if start_date is not None:
        stmt = stmt.where(Transaction.occurred_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(Transaction.occurred_at <= end_date)
    return [(row[0], int(row[1])) for row in session.execute(stmt).all()]


def stats_by_month(session: Session) -> list[tuple[str, int]]:
    month_expr = func.strftime("%Y-%m", Transaction.occurred_at)
    stmt = (
        select(month_expr, func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(Transaction.status == "confirmed")
        .group_by(month_expr)
        .order_by(month_expr)
    )
    return [(row[0], int(row[1])) for row in session.execute(stmt).all()]


def month_bounds(month: str) -> tuple[date, date]:
    """'YYYY-MM' -> 该月首尾日期，供统计页复用。"""
    normalized = month_key(month)
    year, mon = (int(part) for part in normalized.split("-"))
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    from datetime import timedelta

    return start, end - timedelta(days=1)


def day_bounds(value: date) -> tuple[datetime, datetime]:
    return datetime.combine(value, time.min), datetime.combine(value, time.max)
