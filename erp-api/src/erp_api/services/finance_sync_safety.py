from __future__ import annotations

import re

_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(access[_ -]?token|refresh[_ -]?token|auth(?:orization)?[_ -]?code|"
    r"shop[_ -]?cipher)\b\s*(?:[:=]|\bis\s+)?\s*['\"]?[^\s,'\";]+['\"]?"
    r"|\bbearer\s+[^\s,;]+"
)


def safe_error(error: Exception) -> str:
    summary = f"{type(error).__name__}: {error}"
    return _CREDENTIAL_PATTERN.sub("[REDACTED]", summary)[:2000]
