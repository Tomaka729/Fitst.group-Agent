"""AppTest 无浏览器验证：无 Key（默认 prod）与有 Key 两种场景的页面渲染/功能开关。

- 无 Key：侧边栏只出现「统计」，统计页正常渲染出已确认交易；记账/查账不出现在导航。
- 有 Key：模拟配置（monkeypatch 环境 + 直接设置 dotenv 覆盖）后三个页面都可渲染。
Reports exceptions/metrics/dataframes and exits non-zero on any exception.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ.setdefault("DB_PATH", str(root / "data" / "expense.db"))

from streamlit.testing.v1 import AppTest  # noqa: E402


def radio_labels(at: AppTest) -> list[str]:
    radios = at.sidebar.radio
    if not radios:
        return []
    return list(radios[0].options)


def summarize(label: str, at: AppTest, *, expect_pages: list[str] | None = None) -> int:
    exceptions = list(at.exception)
    print(f"--- page: {label} ---")
    print(f"exceptions = {len(exceptions)}")
    for exc in exceptions:
        print("  EXC:", repr(exc.value))
    print("titles   =", [t.value for t in at.title])
    print("radio    =", radio_labels(at))
    print("warnings =", [w.value[:70] for w in at.warning])
    print("infos    =", [i.value[:70] for i in at.info])
    print("errors   =", [e.value[:70] for e in at.error])
    print("metrics  =", [(m.label, m.value) for m in at.metric])
    print("dataframes =", len(at.dataframe))
    if expect_pages is not None:
        actual = radio_labels(at)
        assert actual == expect_pages, f"{label}: expected nav {expect_pages}, got {actual}"
    return len(exceptions)


total = 0

# ---- 场景 1：无 Key（默认 prod 降级）----
os.environ["ZAI_API_KEY"] = ""
os.environ["STRICT"] = "false"
os.environ["APP_ENV"] = "prod"
at = AppTest.from_file(str(root / "app.py"), default_timeout=60)
at.run()
total += summarize("prod 无 Key / 统计", at, expect_pages=["统计"])
# 生产模式默认不注入 seed：统计页要么有累计支出指标（有数据），
# 要么显示「还没有已确认的交易」空状态提示（无数据）——两者都属于正确降级，均不得抛异常。
_has_metric = bool(at.metric)
_has_empty_hint = any("还没有已确认的交易" in w.value for w in at.info)
assert _has_metric or _has_empty_hint, "统计页应显示指标或空状态提示（统计始终可用）"

# ---- 场景 2：有 Key（模拟配置，三个功能全开）----
# AppTest 内 load_settings 走 dotenv；用环境变量注入 fake key 并设 DOTENV_OVERRIDE=0 让环境变量优先
os.environ["ZAI_API_KEY"] = "test-key-for-apptest"
os.environ["DOTENV_OVERRIDE"] = "0"
at2 = AppTest.from_file(str(root / "app.py"), default_timeout=60)
at2.run()
total += summarize("prod 有 Key / 记账", at2, expect_pages=["记账", "查账", "统计"])
at2.sidebar.radio[0].set_value("查账").run()
total += summarize("prod 有 Key / 查账", at2, expect_pages=["记账", "查账", "统计"])
at2.sidebar.radio[0].set_value("统计").run()
total += summarize("prod 有 Key / 统计", at2, expect_pages=["记账", "查账", "统计"])

print("TOTAL_EXCEPTIONS =", total)
sys.exit(1 if total else 0)
