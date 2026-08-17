"""配置系统单测（WP1 DoD：默认值/覆盖/友好报错）。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from yellowbull.config import ConfigError, Settings, load_settings


def test_defaults_without_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    s = load_settings()
    assert s.llm.default_model == "gpt-4o"
    assert len(s.llm.fallback_chain) >= 2
    assert s.engine.max_steps == 25
    assert s.safety.require_confirm_write is True
    assert s.safety.workdir == tmp_path.resolve()


def test_yaml_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        textwrap.dedent(
            """
            llm:
              default_model: claude-sonnet-4
              fallback_chain: [claude-sonnet-4, gpt-4o]
            engine:
              max_steps: 10
            logging:
              level: DEBUG
            """
        ),
        encoding="utf-8",
    )
    s = load_settings()
    assert s.llm.default_model == "claude-sonnet-4"
    assert s.llm.fallback_chain == ["claude-sonnet-4", "gpt-4o"]
    assert s.engine.max_steps == 10
    assert s.logging.level == "DEBUG"


def test_unknown_section_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("foo: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="未知配置段.*foo"):
        load_settings()


def test_type_error_friendly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("engine:\n  max_steps: not_a_number\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="engine.max_steps"):
        load_settings()


def test_explicit_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="不存在"):
        load_settings(tmp_path / "nope.yaml")


def test_bad_yaml_syntax(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("llm: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        load_settings()


def test_env_override_default_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LB_DEFAULT_MODEL", "gemini-2.5-pro")
    s = load_settings()
    assert s.llm.default_model == "gemini-2.5-pro"


def test_model_cfg_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    s = load_settings()
    cfg = s.llm.model_cfg("unknown-model")
    assert cfg.max_tokens > 0


def test_settings_is_pydantic_settings_subclass() -> None:
    # 哨兵：Settings 保留 BaseSettings 能力（env 前缀 LB_）
    from pydantic_settings import BaseSettings

    assert issubclass(Settings, BaseSettings)


def test_validationerror_mapping() -> None:
    # 确保 ValidationError 分支可被友好包装（防回归）
    with pytest.raises(ValidationError):
        load_settings.__globals__["LLMSettings"](default_model=123)  # type: ignore[arg-type]
