"""配置与功能开关测试：默认 prod、无 Key 降级、STRICT 强制、按 Key 开关功能。"""
from __future__ import annotations

import pytest

from core import config as config_module
from core.config import ConfigError, load_settings


def test_default_app_env_is_prod(monkeypatch):
    """不设 APP_ENV 时默认生产模式（.env 的文件值由 load_dotenv 提供，这里清掉走内置默认）。"""
    monkeypatch.delenv("APP_ENV", raising=False)
    assert load_settings().app_env == "prod"


def test_prod_without_key_starts_and_stats_available(monkeypatch):
    """生产模式缺 Key 不再终止启动：统计始终可用，AI 功能关闭。"""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ZAI_API_KEY", "")
    monkeypatch.setenv("STRICT", "false")
    settings = load_settings()  # 不应抛 ConfigError
    assert settings.stats_enabled is True
    assert settings.record_enabled is False
    assert settings.query_enabled is False
    assert settings.llm_ready is False


def test_feature_flags_open_with_key(monkeypatch):
    """配置 Key 后记账/查账自动开启，统计仍恒开。"""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    monkeypatch.setenv("STRICT", "false")
    settings = load_settings()
    assert settings.llm_ready is True
    assert settings.stats_enabled is True
    assert settings.record_enabled is True
    assert settings.query_enabled is True


def test_stats_enabled_regardless_of_env_and_key(monkeypatch):
    """统计开关与运行环境、Key 均无关，任何组合都为 True。"""
    for app_env in ("dev", "demo", "test", "prod"):
        for key in ("", "some-key"):
            monkeypatch.setenv("APP_ENV", app_env)
            monkeypatch.setenv("ZAI_API_KEY", key)
            monkeypatch.setenv("STRICT", "false")
            assert load_settings().stats_enabled is True


def test_strict_requires_key(monkeypatch):
    """STRICT=true 时缺 Key 必须快速失败。"""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("STRICT", "true")
    monkeypatch.setenv("ZAI_API_KEY", "")
    with pytest.raises(ConfigError):
        load_settings()


def test_seed_default_follows_env(monkeypatch):
    """ENABLE_SEED 留空时：prod 关、dev 开；显式值优先。"""
    monkeypatch.setenv("ENABLE_SEED", "")
    monkeypatch.setenv("APP_ENV", "prod")
    assert load_settings().enable_seed is False
    monkeypatch.setenv("APP_ENV", "dev")
    assert load_settings().enable_seed is True
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ENABLE_SEED", "true")
    assert load_settings().enable_seed is True


def test_env_file_discovery_skips_directories(tmp_path, monkeypatch):
    """ENV_FILE_PATH 指向目录时必须跳过（不崩溃），回退到其他候选/None。"""
    import importlib

    dir_as_env = tmp_path / "as_dir"
    dir_as_env.mkdir()  # 一个「.env 形态」的目录
    real_env = tmp_path / "real.env"
    real_env.write_text("APP_ENV=demo\n", encoding="utf-8")

    # 显式路径是目录 → 应被 is_file() 跳过；此时其余候选由模块自身决定，不抛异常。
    monkeypatch.setenv("ENV_FILE_PATH", str(dir_as_env))
    reloaded = importlib.reload(config_module)
    assert reloaded.ENV_FILE is None or reloaded.ENV_FILE.is_file()
    assert reloaded.ENV_FILE != dir_as_env  # 绝不把目录当成配置文件

    # 恢复主模块状态，避免影响其他测试
    monkeypatch.delenv("ENV_FILE_PATH", raising=False)
    importlib.reload(config_module)
