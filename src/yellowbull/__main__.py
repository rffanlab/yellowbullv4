"""老黄牛 CLI 入口。

用法：
    lh            进入交互式 TUI
    lh --check    环境自检（依赖/密钥/目录/工具）
    lh --version  打印版本
    lh --config X 指定配置文件
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from typing import Any

from yellowbull import __version__
from yellowbull.config import ConfigError, Settings, ensure_data_dirs, load_settings


def _ensure_console_output() -> None:
    """保证中文在控制台输出不崩溃（对应 01 文档坑 W1-1）。

    编码跟随控制台 / 重定向目标的原生编码：
    - 真实 Windows 终端：自动匹配代码页（GBK 或 UTF-8 都能正常显示中文）；
    - 重定向 / 沙箱捕获：使用系统 ANSI 代码页（本环境为 GBK）。

    因此【不要】强制 UTF-8——强制后在按 GBK 解码的捕获层反而会乱码。
    这里仅用 errors=replace 兜底，避免个别字符编码失败导致崩溃。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


@dataclass
class CheckResult:
    name: str
    ok: bool
    fatal: bool
    detail: str


def _check_python() -> CheckResult:
    ok = sys.version_info >= (3, 11)
    return CheckResult(
        name="Python 版本",
        ok=ok,
        fatal=True,
        detail=f"{sys.version.split()[0]}（要求 >= 3.11）",
    )


def _check_llm_keys() -> CheckResult:
    from dotenv import dotenv_values

    env: dict[str, str | None] = dict(dotenv_values(".env"))
    import os

    for k, v in os.environ.items():
        if v:
            env[k] = v

    providers = {
        "OpenAI": env.get("OPENAI_API_KEY"),
        "Anthropic": env.get("ANTHROPIC_API_KEY"),
        "Google": env.get("GOOGLE_API_KEY"),
        "OpenRouter": env.get("OPENROUTER_API_KEY"),
    }
    configured = [name for name, key in providers.items() if key]
    missing = [name for name, key in providers.items() if not key]
    detail_parts = []
    if configured:
        detail_parts.append("已配置: " + ", ".join(configured))
    if missing:
        detail_parts.append("未配置: " + ", ".join(missing))
    ok = bool(configured)
    return CheckResult(
        name="LLM 密钥（至少 1 家）",
        ok=ok,
        fatal=not ok,
        detail=("；".join(detail_parts) if detail_parts else "未知"),
    )


def _check_workdir(settings: Settings) -> CheckResult:
    wd = settings.safety.workdir
    try:
        probe = wd / ".lh_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return CheckResult(name="工作目录可写", ok=True, fatal=True, detail=str(wd))
    except OSError as e:
        return CheckResult(name="工作目录可写", ok=False, fatal=True, detail=f"{wd}: {e}")


def _check_ripgrep() -> CheckResult:
    rg = shutil.which("rg")
    return CheckResult(
        name="ripgrep（grep 工具加速，可选）",
        ok=rg is not None,
        fatal=False,
        detail=(rg or "未找到，将自动回退纯 Python 实现"),
    )


def _check_data_dirs(settings: Settings) -> CheckResult:
    try:
        dirs = ensure_data_dirs(settings)
        return CheckResult(
            name="数据目录", ok=True, fatal=False, detail=", ".join(str(p) for p in dirs.values())
        )
    except OSError as e:
        return CheckResult(name="数据目录", ok=False, fatal=True, detail=str(e))


def _check_search_keys() -> CheckResult:
    from dotenv import dotenv_values

    import os

    env: dict[str, str | None] = dict(dotenv_values(".env"))
    for k, v in os.environ.items():
        if v:
            env[k] = v
    brave = env.get("BRAVE_SEARCH_API_KEY")
    bing = env.get("BING_SEARCH_API_KEY")
    ok = bool(brave or bing)
    who = "Brave" if brave else ("Bing" if bing else None)
    return CheckResult(
        name="Web 搜索密钥（可选）",
        ok=ok,
        fatal=False,
        detail=(f"已配置: {who}" if who else "未配置（web_search 将提示未配置，不影响其他功能）"),
    )


def run_checks(settings: Settings) -> int:
    results = [
        _check_python(),
        _check_llm_keys(),
        _check_workdir(settings),
        _check_ripgrep(),
        _check_search_keys(),
        _check_data_dirs(settings),
    ]
    print()
    print("老黄牛环境自检")
    print("=" * 60)
    exit_code = 0
    for r in results:
        mark = "OK " if r.ok else "FAIL" if r.fatal else "WARN"
        color = {
            "OK": "\x1b[32m",
            "WARN": "\x1b[33m",
            "FAIL": "\x1b[31m",
        }[mark.split()[0]]
        reset = "\x1b[0m"
        print(f"  [{color}{mark:<4}{reset}] {r.name}: {r.detail}")
        if not r.ok and r.fatal:
            exit_code = 1
    print("=" * 60)
    if exit_code == 0:
        print("自检通过，可以启动老黄牛（运行 lh）")
    else:
        print("存在必须修复的问题：请按上方提示处理（参考 .env.example 配置密钥）")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    _ensure_console_output()
    parser = argparse.ArgumentParser(
        prog="lh",
        description="老黄牛 — 通用型 AI 工作助手（写代码 / 干活 / 找信息）",
    )
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    parser.add_argument("--check", action="store_true", help="环境自检后退出")
    parser.add_argument("--config", default=None, help="指定配置文件路径（默认 config/config.yaml）")
    args: Any = parser.parse_args(argv)

    if args.version:
        print(f"yellowbull {__version__}")
        return 0

    # 先载入 .env 到进程环境（密钥只进环境，不进配置对象）
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    try:
        settings = load_settings(args.config)
    except ConfigError as e:
        print(f"配置错误:\n{e}", file=sys.stderr)
        return 2

    from yellowbull.logging import setup_logging

    setup_logging(settings.logging.level, settings.logging.dir)

    if args.check:
        return run_checks(settings)

    # 交互式 TUI（延迟导入，保证 --version/--check 快速）
    from yellowbull.cli.app import run_app

    return run_app(settings)


if __name__ == "__main__":
    raise SystemExit(main())
