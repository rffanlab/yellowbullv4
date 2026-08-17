"""脱敏单测（WP1 骨架 / WP6 A6 支撑）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from yellowbull.safety.redact import Redactor, make_redactor


def test_sk_key_masked() -> None:
    """sk- 风格 key 被掩码，原始值及特征片段均不残留。"""
    r = Redactor()
    out = r.text("key: sk-abcDEF1234567890xyz")
    assert "sk-abcDEF" not in out
    assert "abcDEF1234567890xyz" not in out
    assert "sk-***" in out


def test_bearer_masked() -> None:
    """Bearer token 被掩码，原始值及特征片段均不残留。"""
    r = Redactor()
    out = r.text("Authorization: Bearer eyJhbGciOi.abcdef123456")
    assert "eyJhbGciOi" not in out
    assert "abcdef123456" not in out


def test_api_key_assignment_masked() -> None:
    """api_key 赋值（含引号）的值被完全掩码，不泄漏任何片段。"""
    r = Redactor()
    out = r.text('api_key = "supersecretvalue123"')
    assert "supersecretvalue123" not in out
    assert "retvalue123" not in out  # 关键：不允许残留密钥片段


def test_short_values_ignored() -> None:
    # 长度 < 8 的值不当敏感值，避免误伤
    r = Redactor(secret_values={"abc"})
    assert r.text("hello abc world") == "hello abc world"


def test_obj_recursive() -> None:
    r = Redactor()
    data = {"headers": {"Authorization": "Bearer abc123456789"}, "list": ["sk-abcdef1234567890123"]}
    out = r.obj(data)
    assert "abc123456789" not in str(out)
    assert "abcdef1234567890123" not in str(out)


def test_env_file_values_masked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test-value-1234567890\n", encoding="utf-8")
    r = make_redactor()
    out = r.text("call with sk-test-value-1234567890 done")
    assert "sk-test-value-1234567890" not in out


def test_empty_and_none_safe() -> None:
    r = Redactor()
    assert r.text("") == ""
    assert r.obj(None) is None
    assert r.obj(42) == 42
