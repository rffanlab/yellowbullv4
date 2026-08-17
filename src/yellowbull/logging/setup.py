"""日志初始化：控制台（rich）+ 按天文件，统一过脱敏过滤器。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from yellowbull.safety.redact import Redactor, make_redactor


class RedactFilter(logging.Filter):
    """把日志消息中命中的密钥替换为 ***（联动验收 A6）。"""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self.redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            redacted = self.redactor.text(msg)
            if redacted != msg:
                record.msg = redacted
                record.args = ()
        except Exception:  # 脱敏失败不能影响业务
            pass
        return True


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> logging.Logger:
    """初始化根日志。重复调用安全（先清空 handlers）。"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    redactor = make_redactor()

    # 控制台
    try:
        from rich.logging import RichHandler

        console: logging.Handler = RichHandler(
            show_path=False, rich_tracebacks=True, markup=False
        )
        console.setFormatter(logging.Formatter("%(message)s"))
    except ImportError:  # rich 缺失时降级
        console = logging.StreamHandler()
        console.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    console.addFilter(RedactFilter(redactor))
    root.addHandler(console)

    # 文件（按天）
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(
                log_dir / f"yellowbull-{datetime.now():%Y%m%d}.log", encoding="utf-8"
            )
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S",
                )
            )
            file_handler.addFilter(RedactFilter(redactor))
            root.addHandler(file_handler)
        except OSError:
            root.warning("日志目录不可写，跳过文件日志: %s", log_dir)

    # 降低第三方库噪音
    for noisy in ("httpx", "httpcore", "litellm", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return root
