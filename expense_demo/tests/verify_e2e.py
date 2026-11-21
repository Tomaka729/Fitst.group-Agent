"""Full end-to-end verification of the demo's core invariants.

Uses the real file-backed SQLite database at data/expense.db and prints a
human-readable trace of every check. Safe to re-run: the temporary transaction
inserted for the pending/confirmed check is removed at the end.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ["DB_PATH"] = str(root / "data" / "expense.db")

from core.config import load_settings  # noqa: E402
from core.db import session_scope  # noqa: E402
from core.validators import yuan_to_cents  # noqa: E402
from repositories.seed import seed_all  # noqa: E402
from repositories.transactions import (  # noqa: E402
    confirm_transaction,
    count_transactions,
    create_transaction,
    delete_transaction,
    stats_by_category,
    stats_by_month,
    sum_amount_cents,
)

settings = load_settings()
print("=== 1. CONFIG ===")
print("DB_PATH      :", settings.db_path)
print("LLM ready    :", settings.llm_ready, "(no API key is fine for query/stats demo)")
print("models       :", settings.model_text, "/", settings.model_vision, "/", settings.model_audio)

print("\n=== 2. SEED IDEMPOTENCY ===")
print("seed #1:", seed_all(settings))
print("seed #2:", seed_all(settings))

print("\n=== 3. MONEY ===")
for value in ("32", "32.5", "0.29", "3200.00"):
    print(f"  yuan_to_cents({value!r}) = {yuan_to_cents(value)}")

print("\n=== 4. SQL AGGREGATION (confirmed only) ===")
with session_scope() as session:
    total_count = count_transactions(session, start_date=None, end_date=None, category=None)
    total_cents = sum_amount_cents(session, start_date=None, end_date=None, category=None)
    print("  total count :", total_count)
    print("  total amount:", total_cents, "cents =", f"¥{total_cents / 100:,.2f}")
    print("  by category :")
    for name, cents in stats_by_category(session, start_date=None, end_date=None):
        print(f"    {name:<4} ¥{cents / 100:>9,.2f}")
    print("  by month    :")
    for month, cents in stats_by_month(session):
        print(f"    {month} ¥{cents / 100:>9,.2f}")

    print("\n=== 5. PENDING MUST NOT COUNT ===")
    draft = create_transaction(
        session,
        amount_cents=9999,
        merchant="E2E-TEST",
        category="其他",
        occurred_at=date.today(),
        note="temporary verification row",
        source="text",
        status="pending",
        raw_input="e2e verification",
    )
    session.flush()
    during = count_transactions(session, start_date=None, end_date=None, category=None)
    print("  count with 1 pending draft :", during, "(expected", total_count, ")")
    assert during == total_count, "pending draft leaked into stats!"

    confirm_transaction(session, draft.id)
    session.flush()
    after_confirm = count_transactions(session, start_date=None, end_date=None, category=None)
    print("  count after confirmation   :", after_confirm, "(expected", total_count + 1, ")")
    assert after_confirm == total_count + 1, "confirmation did not unlock the row"

    delete_transaction(session, draft.id)
    session.flush()
    restored = count_transactions(session, start_date=None, end_date=None, category=None)
    print("  count after cleanup        :", restored, "(expected", total_count, ")")
    assert restored == total_count, "cleanup failed"

print("\nALL E2E CHECKS PASSED")
