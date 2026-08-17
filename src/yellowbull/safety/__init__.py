"""安全模块：路径白名单 / 分级权限 / 脱敏。"""

from .redact import Redactor, make_redactor

__all__ = ["Redactor", "make_redactor"]
