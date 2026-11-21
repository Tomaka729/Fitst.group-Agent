"""测试全局夹具：把 DB_PATH 指向临时文件，避免污染 demo 数据库。"""
from __future__ import annotations

import os

import pytest

from core import db


def _clear_engine_cache() -> None:
    clear = getattr(db.get_engine, "clear", None) or getattr(db.get_engine, "cache_clear", None)
    if clear:
        clear()


@pytest.fixture(scope="session", autouse=True)
def isolated_database():
    """测试使用内存 SQLite，不落盘、不依赖系统临时目录、不污染 demo 数据。"""
    os.environ["DB_PATH"] = ":memory:"
    _clear_engine_cache()
    yield
    _clear_engine_cache()
