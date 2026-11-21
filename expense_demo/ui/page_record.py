"""记账页：文字 / 图片 / 语音三种方式，抽出草稿后由用户确认入库。"""
from __future__ import annotations

from datetime import date

import streamlit as st

from core.models import CATEGORIES
from core.validators import RecordDraft
from services import bookkeeping, image_prep


def _render_draft(draft: RecordDraft, headline: str) -> None:
    """展示草稿并让用户修正 / 确认；app 层不写任何金额换算或 SQL。"""
    st.markdown("#### " + headline)
    st.info("这是一条待确认草稿（pending），确认后才会计入统计。")

    col_amount, col_merchant = st.columns([1, 2])
    with col_amount:
        amount_yuan = st.number_input(
            "金额（元）", min_value=0.01, step=0.01,
            value=round(draft.amount_cents / 100, 2), key=f"amt_{id(draft)}",
        )
    with col_merchant:
        merchant = st.text_input("商户", value=draft.merchant, key=f"mer_{id(draft)}")

    col_cat, col_date = st.columns([1, 1])
    with col_cat:
        category = st.selectbox(
            "分类", CATEGORIES,
            index=CATEGORIES.index(draft.category) if draft.category in CATEGORIES else 7,
            key=f"cat_{id(draft)}",
        )
    with col_date:
        occurred = st.date_input("日期", value=draft.occurred_at, key=f"date_{id(draft)}")

    note = st.text_input("备注（可选）", value=draft.note, key=f"note_{id(draft)}")

    if st.button("确认入库", type="primary", key=f"confirm_{id(draft)}"):
        ok = bookkeeping.correct_draft(draft._tx_id, amount_yuan=amount_yuan, merchant=merchant,
                                       category=category, occurred_at=occurred, note=note) \
            if getattr(draft, "_tx_id", None) else True
        if ok:
            bookkeeping.confirm_draft(draft._tx_id) if getattr(draft, "_tx_id", None) else None
            st.success("已确认入库，统计已更新。")
            st.session_state.pop("draft", None)
            st.rerun()
        else:
            st.error("草稿已失效，请重新识别。")
    if st.button("放弃这条", key=f"discard_{id(draft)}"):
        if getattr(draft, "_tx_id", None):
            bookkeeping.discard_draft(draft._tx_id)
        st.session_state.pop("draft", None)
        st.rerun()


def _persist_and_show(result: bookkeeping.DraftResult, headline: str) -> None:
    if not result.ok or result.draft is None:
        st.warning(result.message)
        return
    draft = result.draft
    try:
        tx_id = bookkeeping.save_draft(draft)
    except bookkeeping.DuplicateImageError as exc:
        st.warning(str(exc))
        return
    draft._tx_id = tx_id  # 仅 UI 层关联草稿与落库 id，不进入领域模型定义
    st.session_state["draft"] = draft
    st.session_state["draft_headline"] = headline
    st.rerun()


def render(llm_ready: bool) -> None:
    st.subheader("记一笔")

    if "draft" in st.session_state and st.session_state["draft"] is not None:
        _render_draft(st.session_state["draft"], st.session_state.get("draft_headline", "请核对草稿"))
        st.divider()

    if not llm_ready:
        st.info("配置 ZAI_API_KEY 后即可使用下方三种记账方式。当前可先体验「查账」「统计」页。")
        return

    text_tab, image_tab, audio_tab = st.tabs(["文字记账", "图片记账", "语音记账"])

    with text_tab:
        st.caption("试试：昨天打车 32 块 / 午饭 25 和同事 AA")
        user_text = st.text_area("说一句账目", key="record_text")
        if st.button("识别为草稿", key="btn_text"):
            _persist_and_show(bookkeeping.draft_from_text(user_text, date.today()), "文字识别草稿")

    with image_tab:
        st.caption("上传小票或支付截图，识别后仍需你确认")
        uploaded = st.file_uploader("选择图片", type=["png", "jpg", "jpeg"], key="record_image")
        if uploaded is not None and st.button("识别为草稿", key="btn_image"):
            prepared = image_prep.prepare_image(uploaded.getvalue())
            if not prepared.ok:
                st.warning(prepared.message)
            else:
                st.caption(prepared.message)
                _persist_and_show(
                    bookkeeping.draft_from_image(
                        prepared.data, date.today(), image_hash=prepared.image_hash
                    ),
                    "小票识别草稿",
                )

    with audio_tab:
        st.caption("上传 wav/mp3，或用麦克风录一段；ASR 转文字后复用文字链路")
        uploaded_audio = st.file_uploader("选择音频", type=["wav", "mp3", "m4a"], key="record_audio")
        recorded = st.audio_input("或点击录音", key="record_mic")
        source = uploaded_audio or recorded
        if source is not None and st.button("识别为草稿", key="btn_audio"):
            _persist_and_show(
                bookkeeping.draft_from_audio(source.getvalue(), source.name, date.today()),
                "语音识别草稿",
            )
