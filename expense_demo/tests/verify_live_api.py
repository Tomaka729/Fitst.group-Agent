"""生产模式「真实 API」链路测试（需 .env 中配置真实 ZAI_API_KEY）。

约束（与交付约定一致）：
- 只使用项目内演示数据：demo_data/ 下的小票图/语音，以及 Read.md 记录的演示话术。
- 不调用 seed_all()，不写入生产库 data/expense.db。
- 所有落库动作发生在一个临时隔离 DB，脚本结束即删除。

运行：docker compose exec -T expense-demo python3 tests/verify_live_api.py
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---- 关键：先切到临时隔离库，绝不让任何写入落到生产库 data/expense.db ----
_fd, _tmp_db = tempfile.mkstemp(prefix="expense_live_", suffix=".db")
os.close(_fd)
os.unlink(_tmp_db)  # 交给 SQLAlchemy 自己建表
os.environ["DB_PATH"] = _tmp_db

from core.config import load_settings  # noqa: E402
from core.db import session_scope  # noqa: E402
from llm.client import LLMClient  # noqa: E402
from repositories.transactions import (  # noqa: E402
    count_transactions,
    stats_by_category,
    sum_amount_cents,
)
from services.bookkeeping import (  # noqa: E402
    confirm_draft,
    draft_from_audio,
    draft_from_image,
    draft_from_text,
    save_draft,
)

TODAY = date(2026, 11, 19)
settings = load_settings()


def _elapsed(t: float) -> str:
    return f"{time.time() - t:.1f}s"


print("=" * 64)
print("生产模式真实 API 链路测试")
print(f"  APP_ENV      : {settings.app_env}")
print(f"  ENABLE_SEED  : {settings.enable_seed}  (不调用 seed_all)")
print(f"  DB_PATH      : {settings.db_path}  (临时隔离，非生产库)")
print(f"  llm_ready    : {settings.llm_ready}  | model_text: {settings.model_text}")
print(f"  vision/audio : {settings.model_vision} / {settings.model_audio}")
print("=" * 64)

client = LLMClient(settings)
results: dict[str, bool] = {}

# ---------------------------------------------------------------- 1. 文字记账
print("\n[1] 文字记账 —— 演示话术「昨天打车三十二块五，滴滴出行」")
t = time.time()
r = draft_from_text("昨天打车三十二块五，滴滴出行", TODAY, client=client)
print(f"  耗时 {_elapsed(t)} | ok={r.ok} | {r.message}")
if r.ok and r.draft:
    d = r.draft
    print(f"  草稿: 商户={d.merchant!r} 金额={d.amount_cents}分 分类={d.category} 日期={d.occurred_at} source={d.source}")
    tx_id = save_draft(d)
    with session_scope() as s:
        pending_cnt = count_transactions(s, start_date=None, end_date=None, category=None)
    print(f"  save_draft -> id={tx_id}; 此时统计笔数={pending_cnt} (pending 不计入)")
    confirm_draft(tx_id)
    with session_scope() as s:
        confirmed_cnt = count_transactions(s, start_date=None, end_date=None, category=None)
        total = sum_amount_cents(s, start_date=None, end_date=None, category=None)
        cats = list(stats_by_category(s, start_date=None, end_date=None))
    print(f"  confirm 后 统计笔数={confirmed_cnt}, 总额=¥{total / 100:,.2f}, 分类分布={cats}")
    results["文字记账+入库+统计"] = confirmed_cnt == 1
else:
    results["文字记账+入库+统计"] = False

# ---------------------------------------------------------------- 2. 查账意图
print("\n[2] 查账意图解析（自然语言 -> 查询条件，数字由 SQL 算）")
for q in ("这个月餐饮花了多少", "哪类花得最多"):
    t = time.time()
    intent = client.parse_query_intent(q, TODAY)
    print(f"  「{q}」耗时 {_elapsed(t)} -> {intent}")
results["查账意图解析"] = bool(client.parse_query_intent("这个月餐饮花了多少", TODAY))

# ---------------------------------------------------------------- 3. 图片 OCR
print("\n[3] 图片 OCR —— demo_data/receipt_coffee.png")
img = (ROOT / "demo_data" / "receipt_coffee.png").read_bytes()
t = time.time()
ocr = client.ocr_receipt(img, TODAY, mime="image/png")
print(f"  耗时 {_elapsed(t)} -> {ocr}")
if ocr:
    r3 = draft_from_image(img, TODAY, mime="image/png", image_hash=hashlib.sha256(img).hexdigest(), client=client)
    print(f"  draft_from_image: ok={r3.ok} | {r3.message}")
    if r3.ok and r3.draft:
        print(f"  草稿: 商户={r3.draft.merchant!r} 金额={r3.draft.amount_cents}分 分类={r3.draft.category}")
results["图片OCR"] = bool(ocr)

# ---------------------------------------------------------------- 4. 语音 ASR
print("\n[4] 语音 ASR —— demo_data/voice_taxi.wav")
wav = (ROOT / "demo_data" / "voice_taxi.wav").read_bytes()
t = time.time()
transcript = client.transcribe_audio(wav, "voice_taxi.wav")
print(f"  耗时 {_elapsed(t)} -> 转写={transcript!r}")
if transcript:
    r4 = draft_from_audio(wav, "voice_taxi.wav", TODAY, client=client)
    print(f"  draft_from_audio: ok={r4.ok} | {r4.message}")
    if r4.ok and r4.draft:
        print(f"  草稿: 商户={r4.draft.merchant!r} 金额={r4.draft.amount_cents}分 分类={r4.draft.category}")
results["语音ASR"] = bool(transcript)

# ---------------------------------------------------------------- 汇总 + 清理
print("\n" + "=" * 64)
for k, v in results.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}")
print("=" * 64)

for suffix in ("", "-wal", "-shm"):
    p = Path(str(_tmp_db) + suffix)
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass
print("临时隔离库已删除；生产库 data/expense.db 未被写入。")
