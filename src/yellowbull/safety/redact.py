"""密钥脱敏（对应 docs/phase1/06-安全与审计.md §4）。

所有会"落到外面"的文本/对象（日志、审计、异常消息、产物）在输出前
都应经过 Redactor。规则：
- 常见 key 模式：sk-xxx、Bearer xxx、api_key=xxx、Authorization: xxx
- .env 中出现过的值（长度 >= 8）视为敏感值，一律掩码
- 进程环境中 key/token/secret/password 类变量的值同样掩码
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# 值匹配统一支持三种形态：双引号 "xxx"、单引号 'xxx'、裸值 \S+
_VALUE = r"(\"[^\"]*\"|'[^']*'|\S+)"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI 风格 key：sk-xxx（保留 sk- 前缀便于识别来源）
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    # Bearer token：Bearer xxx（xxx 为整个非空白 token，含 JWT/sk- 等）
    (re.compile(r"\bBearer\s+\S+"), "Bearer ***"),
    # key/value 赋值：api_key=xxx、token: "xxx"、password: xxx 等（支持引号）
    (
        re.compile(
            r"(?i)\b(api[_\-]?key|apikey|token|secret|password|passwd|access[_\-]?key)"
            r"(\s*[:=]\s*)"
            + _VALUE
        ),
        r"\1\2***",
    ),
    # Authorization 头（支持引号）
    (
        re.compile(r"(?i)\b(authorization)(\s*[:=]\s*)" + _VALUE),
        r"\1\2***",
    ),
]

_SENSITIVE_ENV_RE = re.compile(r"(?i)(key|token|secret|password|passwd)")


class Redactor:
    """脱敏器：text() 处理字符串，obj() 递归处理 dict/list。"""

    def __init__(self, secret_values: set[str] | None = None) -> None:
        self._values = {v for v in (secret_values or set()) if v and len(v) >= 8}

    def text(self, s: str) -> str:
        if not s:
            return s
        for pattern, repl in _PATTERNS:
            s = pattern.sub(repl, s)
        # 长值优先替换，避免短值先替换导致长值残留
        for v in sorted(self._values, key=len, reverse=True):
            if v in s:
                s = s.replace(v, "***")
        return s

    def obj(self, o: Any) -> Any:
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, dict):
            return {k: self.obj(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [self.obj(v) for v in o]
        return o


def _values_from_env_file(path: Path) -> set[str]:
    values: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            _, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            if val:
                values.add(val)
    except OSError:
        pass
    return values


def make_redactor() -> Redactor:
    """构建默认脱敏器：载入 .env 值 + 进程环境中的敏感值。"""
    values: set[str] = set()
    env_file = Path(".env")
    if env_file.is_file():
        values |= _values_from_env_file(env_file)
    for k, v in os.environ.items():
        if _SENSITIVE_ENV_RE.search(k) and v:
            values.add(v)
    return Redactor(values)
