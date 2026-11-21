"""首次启动幂等灌入 seed 数据：固定 8 分类 + 示例账单（全部 confirmed）。"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from core.config import Settings
from core.db import session_scope
from core.models import Transaction
from core.validators import yuan_to_cents
from repositories.transactions import ensure_categories

SEED_MARKER = "seed:demo"


def _read_rows(csv_path: str) -> list[dict[str, str]]:
    path = Path(csv_path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def seed_all(settings: Settings) -> str:
    """幂等：只要已有 seed 标记的交易就不再重复写入。返回可读状态说明。"""
    rows = _read_rows(settings.seed_csv_path)
    with session_scope() as session:
        ensure_categories(session)

        existing = int(
            session.scalar(
                select(func.count()).select_from(Transaction).where(Transaction.raw_input == SEED_MARKER)
            )
            or 0
        )
        if existing >= len(rows) and rows:
            return f"seed 已存在（{existing} 笔），跳过。分类表 8 项就绪。"

        # 若部分存在，补齐缺失的（按 merchant+date+amount 判断）
        present = {
            (tx.merchant, tx.occurred_at.isoformat(), tx.amount_cents)
            for tx in session.scalars(select(Transaction).where(Transaction.raw_input == SEED_MARKER)).all()
        }
        added = 0
        for row in rows:
            try:
                # 兼容两种列名：amount（仓库 CSV）与 amount_yuan（旧格式）
                raw_amount = row.get("amount_yuan") or row.get("amount")
                amount_cents = yuan_to_cents(raw_amount)
                occurred_at = date.fromisoformat(row["occurred_at"].strip())
                status = (row.get("status") or "confirmed").strip()
                if status not in ("confirmed", "pending"):
                    continue
                # 演示数据只导入已确认、金额为正的有效账单
                if status != "confirmed" or amount_cents <= 0:
                    continue
            except Exception:  # noqa: BLE001 - 跳过坏行，不阻断启动
                continue
            key = (row.get("merchant", "").strip(), occurred_at.isoformat(), amount_cents)
            if key in present:
                continue
            session.add(
                Transaction(
                    amount_cents=amount_cents,
                    merchant=row.get("merchant", "").strip(),
                    category=row.get("category", "其他").strip(),
                    occurred_at=occurred_at,
                    note=row.get("note", "").strip(),
                    source=row.get("source", "text").strip(),
                    status=status,
                    raw_input=SEED_MARKER,
                )
            )
            added += 1
        return f"seed 完成：新增 {added} 笔，分类表 8 项就绪（累计标记 {existing + added} 笔）。"
