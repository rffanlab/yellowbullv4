"""配置加载与校验。

优先级：环境变量（LB_*）> .env > config.yaml > 内置默认。
密钥（API key）一律走 .env / 环境变量，不进入本模块。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# 运行期数据目录（相对 workdir 的上级，即 cwd 下的 data/）
DATA_DIRS = ("sessions", "artifacts", "audit", "logs")

KNOWN_SECTIONS = ("llm", "safety", "engine", "logging")


class ConfigError(RuntimeError):
    """带友好提示的配置错误（字段 + 原因 + 示例）。"""


class ModelSettings(BaseModel):
    max_tokens: int = 8000
    context_window: int = 128_000


class LLMTimeouts(BaseModel):
    connect: float = 10.0
    read: float = 120.0


class LLMSettings(BaseModel):
    default_model: str = "gpt-4o"
    fallback_chain: list[str] = Field(
        default_factory=lambda: ["gpt-4o", "claude-sonnet-4", "gemini-2.5-pro"]
    )
    per_model: dict[str, ModelSettings] = Field(default_factory=dict)
    timeouts: LLMTimeouts = Field(default_factory=LLMTimeouts)
    max_retries: int = 2

    def model_cfg(self, model: str) -> ModelSettings:
        return self.per_model.get(model, ModelSettings())


class SafetySettings(BaseModel):
    workdir: Path = Path(".")
    allow_paths: list[Path] = Field(default_factory=lambda: [Path(".")])
    require_confirm_write: bool = True
    require_confirm_execute: bool = True


class EngineSettings(BaseModel):
    max_steps: int = 25
    max_runtime_seconds: int = 600
    tool_output_cap_chars: int = 20_000
    loop_threshold: int = 3
    keep_recent_turns: int = 6
    run_python_timeout: int = 60
    web_timeout_seconds: float = 20.0
    web_max_bytes: int = 1_000_000


class LoggingSettings(BaseModel):
    level: str = "INFO"
    dir: Path = Path("data/logs")
    retention_days: int = 14


class Settings(BaseSettings):
    """顶层配置对象。

    注意：本类同时作为 pydantic-settings 的模型（env 前缀 LB_），
    但 YAML 合并由 load_settings() 显式完成，保证错误信息可读。
    """

    model_config = SettingsConfigDict(env_prefix="LB_", extra="ignore")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    engine: EngineSettings = Field(default_factory=EngineSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


def _find_config_file(explicit: str | Path | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise ConfigError(f"配置文件不存在: {p}（请检查路径，或参考 .env.example 与 config/config.yaml）")
        return p
    for p in (Path("config/config.yaml"), Path("config.yaml")):
        if p.is_file():
            return p
    return None


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"无法读取配置文件 {path}: {e}") from e
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"配置文件 {path} YAML 语法错误: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件 {path} 顶层必须是键值对（mapping），当前是 {type(data).__name__}")
    return data


def _friendly_validation_error(
    e: ValidationError, source: str, section: str | None = None
) -> ConfigError:
    lines = []
    for err in e.errors():
        loc_parts = [str(x) for x in err["loc"]]
        # 带节名前缀（如 engine.max_steps），便于用户在 config.yaml 中定位
        loc = ".".join([section, *loc_parts]) if section else (".".join(loc_parts) or "(顶层)")
        lines.append(f"  - 字段 {loc}: {err['msg']}")
    return ConfigError(
        f"配置校验失败（{source}）:\n"
        + "\n".join(lines)
        + "\n完整示例见 config/config.yaml"
    )


def _build_section(
    name: str, model_cls: type, data: dict[str, Any] | None, source: str
):
    """构造单个配置段；校验失败时抛出带节名前缀的友好错误。"""
    try:
        return model_cls(**(data or {}))
    except ValidationError as e:
        raise _friendly_validation_error(e, source, section=name) from e


def load_settings(config_path: str | Path | None = None) -> Settings:
    """加载配置并返回 Settings。

    - 未找到 config.yaml 时使用内置默认（允许"零配置"启动，仅缺 key 时提示）。
    - 任何结构/类型错误都抛 ConfigError，并指出字段与示例位置。
    """
    cfg_file = _find_config_file(config_path)
    yaml_data: dict[str, Any] = {}
    if cfg_file is not None:
        yaml_data = _read_yaml(cfg_file)
        unknown = set(yaml_data) - set(KNOWN_SECTIONS)
        if unknown:
            raise ConfigError(
                f"配置文件 {cfg_file} 含未知配置段: {sorted(unknown)}。"
                f"支持的段: {list(KNOWN_SECTIONS)}（详见 docs/phase1/01-工程骨架与配置.md）"
            )

    source = str(cfg_file) if cfg_file else "内置默认"
    # 按段构造并校验，错误信息带节名前缀（如 engine.max_steps）
    llm = _build_section("llm", LLMSettings, yaml_data.get("llm"), source)
    safety = _build_section("safety", SafetySettings, yaml_data.get("safety"), source)
    engine = _build_section("engine", EngineSettings, yaml_data.get("engine"), source)
    logging = _build_section("logging", LoggingSettings, yaml_data.get("logging"), source)
    settings = Settings(llm=llm, safety=safety, engine=engine, logging=logging)

    # 环境变量覆盖（优先级最高；.env 已在上游 load_dotenv 进 environ）
    env = os.environ
    if env.get("LB_DEFAULT_MODEL"):
        settings.llm.default_model = env["LB_DEFAULT_MODEL"]
    if env.get("LB_WORKDIR"):
        settings.safety.workdir = Path(env["LB_WORKDIR"])
    if env.get("LB_LOG_LEVEL"):
        settings.logging.level = env["LB_LOG_LEVEL"].upper()

    # 路径统一解析为绝对路径（相对路径基于当前工作目录）
    base = Path.cwd()
    settings.safety.workdir = (base / settings.safety.workdir).expanduser().resolve()
    settings.safety.allow_paths = [
        (base / p).expanduser().resolve() for p in settings.safety.allow_paths
    ]
    if settings.safety.workdir not in settings.safety.allow_paths:
        settings.safety.allow_paths.append(settings.safety.workdir)
    settings.logging.dir = (base / settings.logging.dir).expanduser().resolve()
    return settings


def ensure_data_dirs(settings: Settings) -> dict[str, Path]:
    """确保运行期数据目录存在，返回 {名称: 路径}。"""
    data_root = Path.cwd() / "data"
    dirs = {}
    for name in DATA_DIRS:
        p = data_root / name
        p.mkdir(parents=True, exist_ok=True)
        dirs[name] = p
    # 日志目录可能配置在别处
    settings.logging.dir.mkdir(parents=True, exist_ok=True)
    return dirs
