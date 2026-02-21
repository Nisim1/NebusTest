"""Security sentinel — redacts secrets before content reaches the LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GITHUB_TOKEN", re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}")),
    (
        "GENERIC_KEY",
        re.compile(
            r"(?:api[_\-]?key|apikey|secret[_\-]?key|access[_\-]?token|auth[_\-]?token)"
            r"""\s*[:=]\s*['"]?[A-Za-z0-9_\-/+]{20,}['"]?""",
            re.IGNORECASE,
        ),
    ),
    (
        "PASSWORD",
        re.compile(
            r"""(?:password|passwd|secret|credential)\s*[:=]\s*['"]?[^\s'"]{8,}['"]?""",
            re.IGNORECASE,
        ),
    ),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    (
        "CONN_STRING",
        re.compile(
            r"(?:postgres|mysql|mongodb)(?:\+\w+)?://[^\s]{10,}",
            re.IGNORECASE,
        ),
    ),
    (
        "BEARER",
        re.compile(
            r"""(?:Authorization|Bearer)\s*[:=]\s*['"]?Bearer\s+[A-Za-z0-9_\-/.]{20,}""",
            re.IGNORECASE,
        ),
    ),
]

_REDACTION = "[REDACTED]"


@dataclass(frozen=True, slots=True)
class SanitizedResult:
    clean_text: str
    redaction_count: int


def sanitize(text: str) -> SanitizedResult:
    """Scan text for secret patterns and replace matches with [REDACTED]."""
    count = 0
    result = text

    for _label, pattern in _SECRET_PATTERNS:
        new_result, num = pattern.subn(_REDACTION, result)
        count += num
        result = new_result

    return SanitizedResult(clean_text=result, redaction_count=count)


def sanitize_batch(texts: dict[str, str]) -> tuple[dict[str, str], int]:
    """Sanitize a dict of texts and return cleaned dict + total redaction count."""
    total = 0
    cleaned: dict[str, str] = {}
    for key, text in texts.items():
        res = sanitize(text)
        cleaned[key] = res.clean_text
        total += res.redaction_count
    return cleaned, total
