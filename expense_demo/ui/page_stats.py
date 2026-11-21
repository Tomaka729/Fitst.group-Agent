"""统计页：按类别与月份展示（数据全部来自 confirmed 交易的 SQL 聚合）。"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.db import session_scope
from repositories import transactions as repo


def render() -> None:
    st.subheader("消费统计")
    st.caption("仅统计已确认（confirmed）的交易；pending 草稿不计入。")

    with session_scope() as session:
        by_category = repo.stats_by_category(session, start_date=None, end_date=None)
        by_month = repo.stats_by_month(session)
        recent = repo.list_transactions(session, status="confirmed", limit=20)

    if not by_category:
        st.info("还没有已确认的交易。先在「记账」页确认几笔，或查看 seed 数据是否成功加载。")
        return

    total = sum(cents for _, cents in by_category)
    st.metric("累计支出", f"¥{total / 100:,.2f}")

    st.markdown("##### 分类占比")
    cat_df = pd.DataFrame(by_category, columns=["分类", "金额（元）"])
    cat_df["金额（元）"] = cat_df["金额（元）"] / 100
    st.bar_chart(cat_df.set_index("分类"))
    st.dataframe(cat_df, width="stretch", hide_index=True)

    st.markdown("##### 月度趋势")
    month_df = pd.DataFrame(by_month, columns=["月份", "金额（元）"])
    month_df["金额（元）"] = month_df["金额（元）"] / 100
    st.line_chart(month_df.set_index("月份"))
    st.dataframe(month_df, width="stretch", hide_index=True)

    st.markdown("##### 最近 20 笔")
    for tx in recent:
        st.write(f"- {tx.occurred_at} · {tx.category} · {tx.merchant} · ¥{tx.amount_cents / 100:.2f} · {tx.source}")
