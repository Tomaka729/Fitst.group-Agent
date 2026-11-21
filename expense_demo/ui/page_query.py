"""查账页：自然语言问题 → 查询条件 → SQL 计算的数字。"""
from __future__ import annotations

from datetime import date

import streamlit as st

from core.models import Transaction
from services.query import answer_query


def render() -> None:
    st.subheader("自然语言查账")
    st.caption("试试：上个月吃饭花了多少？/ 这个月哪类花得最多？/ 列出上周的交通记录")

    question = st.text_input("你的问题", key="query_question")
    if st.button("查一下", type="primary", key="btn_query"):
        answer = answer_query(question, date.today())
        if not answer.ok:
            st.warning(answer.message)
            return
        st.success(answer.message)
        if answer.intent is not None:
            with st.expander("本次解析出的查询条件（数字由 SQL 计算，模型不参与算数）"):
                st.json(
                    {
                        "start_date": answer.intent.start_date.isoformat() if answer.intent.start_date else None,
                        "end_date": answer.intent.end_date.isoformat() if answer.intent.end_date else None,
                        "category": answer.intent.category,
                        "metric": answer.intent.metric,
                    }
                )
        if answer.ranking:
            st.markdown("##### 类别排行（SQL SUM 聚合，仅 confirmed）")
            for index, (category, cents) in enumerate(answer.ranking, start=1):
                st.write(f"{index}. {category} · ¥{cents / 100:,.2f}")
        if answer.rows:
            st.markdown("##### 明细")
            for tx in answer.rows:
                amount = f"{tx.amount_cents / 100:.2f}"
                st.write(f"- {tx.occurred_at} · {tx.category} · {tx.merchant} · ¥{amount}")
