"""数据库引擎与短生命周期 Session；适配 Streamlit 的线程模型。"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import load_settings
from core.models import Base

try:
    import streamlit as st

    _cache = st.cache_resource(show_spinner=False)
except ImportError:  # 纯测试环境无 streamlit 时降级，不影响生产行为
    _cache = lru_cache(maxsize=1)


@_cache
def get_engine() -> Engine:
    """Streamlit 多脚本重跑下用 cache_resource 保证 engine 单例（测试环境退化为 lru_cache）。"""
    settings = load_settings()
    connect_args = {"check_same_thread": False}
    engine_kwargs: dict = {"connect_args": connect_args, "future": True}
    if settings.db_path == ":memory:":
        # 内存库需单连接共享，否则每个 Session 看到的是不同的空库（仅供测试使用）
        engine_kwargs["poolclass"] = StaticPool
    engine = create_engine(f"sqlite:///{settings.db_path}", **engine_kwargs)
    Base.metadata.create_all(engine)
    return engine


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """每次 DB 操作开一个短 Session，用完即关；绝不存入 st.session_state。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
