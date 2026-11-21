"""集中配置：全部参数来自环境变量，启动时读取并做基础校验。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 稳健定位 .env：按候选顺序找第一个「真实文件」，任一路径被误建成目录都会自动跳过。
# Docker 场景推荐由 compose 的 env_file 把 .env 注入为环境变量（见 docker-compose.yml），
# 这样容器文件系统里根本没有 .env，彻底避免「源文件缺失→Docker 自动建同名目录→读不到配置」的陷阱。
# 本段逻辑同时兼容本地直跑与旧的挂载方式，作为兜底。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 候选顺序：显式指定 > 项目根 > 容器内 /app。
_candidates: list[Path] = []
if os.environ.get("ENV_FILE_PATH"):
    _candidates.append(Path(os.environ["ENV_FILE_PATH"]).expanduser())
_candidates += [PROJECT_ROOT / ".env", Path("/app/.env")]
# 只认真实文件：若某路径被误建成目录，is_file() 为 False，自动跳到下一个候选。
ENV_FILE: Path | None = next((p for p in _candidates if p.is_file()), None)

# 默认不覆盖已存在的环境变量：让 compose env_file / docker run -e / CI 注入值优先于文件。
# 设 DOTENV_OVERRIDE=1 可恢复「文件优先」（本地调试用）。
_override = os.environ.get("DOTENV_OVERRIDE", "0").strip().lower() in ("1", "true", "yes", "on")
if ENV_FILE is not None:
    load_dotenv(dotenv_path=ENV_FILE, override=_override)

# 智谱 GLM 的 OpenAI 兼容端点（可用 .env 覆盖）
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"


class ConfigError(RuntimeError):
    """配置缺失或非法时抛出，便于上层给出可读提示。"""


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model_text: str
    model_vision: str
    model_audio: str
    db_path: str
    seed_csv_path: str
    app_env: str
    enable_seed: bool
    strict: bool
    reasoning_effort: str = ""

    @property
    def llm_ready(self) -> bool:
        """是否配置了 API Key。"""
        return bool(self.api_key.strip())

    @property
    def stats_enabled(self) -> bool:
        """统计只做本地 SQL 聚合，不依赖任何外部 API —— 任何环境、有无 Key 都开启。"""
        return True

    @property
    def record_enabled(self) -> bool:
        """记账（文字/图片/语音）依赖 GLM 抽取，无 Key 时关闭。"""
        return self.llm_ready

    @property
    def query_enabled(self) -> bool:
        """查账的自然语言意图解析依赖 GLM，无 Key 时关闭。"""
        return self.llm_ready


def _read(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _read_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_settings() -> Settings:
    """读取并校验环境变量。

    - APP_ENV 默认 prod（生产优先）；合法值 dev/demo/test/prod/production。
    - 运行环境与功能可用性解耦：prod 缺 Key 不再终止启动，而是按功能开关降级——
      统计页（stats_enabled）始终可用，记账/查账（依赖 GLM）在缺 Key 时关闭。
    - STRICT 显式开启时才强制要求 API Key（部署自检用）：缺 Key 则快速失败。
    - ENABLE_SEED 控制是否灌入演示数据：默认仅 dev/demo/test 开启，prod 关闭。
    """
    app_env = _read("APP_ENV", "prod").lower() or "prod"
    if app_env not in ("dev", "demo", "prod", "production", "test"):
        raise ConfigError(f"APP_ENV 非法: {app_env!r}（可选 dev/demo/prod/test）")
    is_prod = app_env in ("prod", "production")

    api_key = _read("ZAI_API_KEY")
    base_url = _read("ZAI_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
    db_path = _read("DB_PATH", "./data/expense.db") or "./data/expense.db"
    strict = _read_bool("STRICT", False)

    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"ZAI_BASE_URL 非法: {base_url!r}")
    # 只有 STRICT 自检才强制 Key；默认 prod 无 Key 时降级运行，保证统计始终可用。
    if strict and not api_key:
        raise ConfigError("严格模式（STRICT=true）必须配置 ZAI_API_KEY，启动已终止。")

    # seed：显式环境变量优先；否则 dev/demo/test 默认开，prod 默认关
    seed_default = not is_prod
    enable_seed = _read_bool("ENABLE_SEED", seed_default)

    # 确保数据库父目录存在（容器内为 /app/data）
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    here = Path(__file__).resolve().parent.parent
    return Settings(
        api_key=api_key,
        base_url=base_url,
        model_text=_read("MODEL_TEXT", "glm-4-flash") or "glm-4-flash",
        model_vision=_read("MODEL_VISION", "glm-4v-plus") or "glm-4v-plus",
        model_audio=_read("MODEL_AUDIO", "glm-asr-2512") or "glm-asr-2512",
        db_path=db_path,
        seed_csv_path=str(here / "demo_data" / "seed_transactions.csv"),
        app_env=app_env,
        enable_seed=enable_seed,
        strict=strict,
        reasoning_effort=_read("REASONING_EFFORT", ""),
    )
