"""智能记账助手入口：只负责初始化、拿输入、调 service、渲染页面。"""
from __future__ import annotations

import logging

import streamlit as st

from core.config import ConfigError, Settings, load_settings
from repositories.seed import seed_all
from ui import page_query, page_record, page_stats

logger = logging.getLogger("expense_app")

st.set_page_config(page_title="智能记账助手", page_icon="¥", layout="centered")


def bootstrap() -> tuple[Settings, str]:
    """读取配置；按 ENABLE_SEED 决定是否幂等灌入演示数据。返回 (配置, 状态说明)。"""
    settings = load_settings()
    if settings.enable_seed:
        message = seed_all(settings)
    else:
        message = f"演示数据灌入已关闭（APP_ENV={settings.app_env}，ENABLE_SEED=false）。"
    return settings, message


def _feature_availability(settings: Settings) -> dict[str, bool]:
    """功能开关：统计始终可用；记账/查账依赖 GLM，按是否配置 Key 决定。"""
    return {
        "记账": settings.record_enabled,
        "查账": settings.query_enabled,
        "统计": settings.stats_enabled,
    }


def _render_status(available: dict[str, bool], settings: Settings) -> None:
    """侧边栏功能状态面板：清楚标注每个功能是开启还是关闭，以及原因。"""
    with st.sidebar.expander("功能状态", expanded=False):
        st.write(f"运行环境：`{settings.app_env}`" + (" · 生产模式" if settings.app_env in ("prod", "production") else ""))
        st.write(f"API Key：{'已配置' if settings.llm_ready else '未配置'}")
        st.divider()
        for name, enabled in available.items():
            if enabled:
                st.write(f"- {name}：**开启**")
            elif name == "统计":
                st.write(f"- {name}：**关闭**（异常，请检查配置）")
            else:
                st.write(f"- {name}：**关闭**（依赖 GLM，需配置 ZAI_API_KEY）")


def _render_closed(name: str) -> None:
    """被关闭功能的占位提示：不调用任何依赖 Key 的服务。"""
    st.subheader(name)
    st.info(
        f"「{name}」依赖智谱 GLM，当前未配置 ZAI_API_KEY，功能已关闭。"
        "请在项目根目录 .env 填入 ZAI_API_KEY 后重启；「统计」不受影响，始终可用。"
    )


def main() -> None:
    try:
        settings, message = bootstrap()
    except ConfigError as exc:
        # 配置错误属于启动前置条件，给出可读提示后停止，避免带着错误配置运行
        st.error(f"配置错误：{exc}")
        st.info("请检查 .env 后重启服务。字段说明见项目根目录 Read.md。")
        return
    except Exception as exc:  # noqa: BLE001 - 启动阶段兜底，不向用户暴露堆栈
        logger.exception("应用启动失败")
        st.error("应用启动失败，请查看服务端日志。")
        return

    available = _feature_availability(settings)
    st.title("智能记账助手")
    st.caption("说一句话、拍张小票、录段语音 —— 都能记进账本")

    if not settings.llm_ready:
        st.info(
            "未检测到 ZAI_API_KEY：记账、查账依赖 GLM 已关闭；"
            "「统计」只做本地计算、不依赖 API，始终可用。"
            "如需完整功能，在 .env 填入 ZAI_API_KEY 后重启即可。"
        )

    with st.expander("启动信息", expanded=False):
        st.write(f"环境 APP_ENV：{settings.app_env}")
        st.write(f"数据库：{settings.db_path}")
        st.write(f"统计页：{'可用' if available['统计'] else '不可用'}（无需 API Key）")
        st.write(message)

    # 侧边栏只列出已开启的功能；关闭的功能不出现在导航里
    pages = [name for name, enabled in available.items() if enabled]
    page = st.sidebar.radio("功能", pages, label_visibility="collapsed")
    _render_status(available, settings)

    try:
        if page == "记账" and available["记账"]:
            page_record.render(llm_ready=True)
        elif page == "查账" and available["查账"]:
            page_query.render()
        elif page == "统计" and available["统计"]:
            page_stats.render()
        else:
            # 兜底：异常状态下即使收到已关闭功能的请求也不执行依赖 Key 的逻辑
            _render_closed(page)
    except Exception as exc:  # noqa: BLE001 - 页面级错误边界，避免把堆栈渲染给用户
        logger.exception("页面渲染失败")
        st.error("页面处理时发生错误，请查看服务端日志，或检查输入后重试。")


if __name__ == "__main__":
    main()
