"""Security sentinel — redacts secrets before content reaches the LLM.

All regex patterns are pre-compiled for performance.  The sentinel is
intentionally conservative: it is better to over-redact than to leak a key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Compiled patterns ───────────────────────────────────────────────────────

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # AWS access key
    ("AWS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    # GitHub tokens
    ("GITHUB_TOKEN", re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}")),
    # Generic API keys (key=value assignments)
    (
        "GENERIC_KEY",
        re.compile(
            r"(?:api[_\-]?key|apikey|secret[_\-]?key|access[_\-]?token|auth[_\-]?token)"
            r"""\s*[:=]\s*['"]?[A-Za-z0-9_\-/+]{20,}['"]?""",
            re.IGNORECASE,
        ),
    ),
    # Generic password / secret assignment
    (
        "PASSWORD",
        re.compile(
            r"""(?:password|passwd|secret|credential)\s*[:=]\s*['"]?[^\s'"]{8,}['"]?""",
            re.IGNORECASE,
        ),
    ),
    # Private keys (PEM)
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    # JWT tokens
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    # Connection strings (postgres, mysql, mongo)
    (
        "CONN_STRING",
        re.compile(
            r"(?:postgres|mysql|mongodb)(?:\+\w+)?://[^\s]{10,}",
            re.IGNORECASE,
        ),
    ),
    # Bearer tokens in headers
    (
        "BEARER",
        re.compile(
            r"""(?:Authorization|Bearer)\s*[:=]\s*['"]?Bearer\s+[A-Za-z0-9_\-/.]{20,}""",
            re.IGNORECASE,
        ),
    ),
]

_REDACTION = "[REDACTED]"


# ── Result type ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SanitizedResult:
    """Outcome of a sanitization pass."""

    clean_text: str
    redaction_count: int


# ── Public API ──────────────────────────────────────────────────────────────


def sanitize(text: str) -> SanitizedResult:
    """Scan *text* for secret patterns and replace matches with ``[REDACTED]``.

    Returns a :class:`SanitizedResult` with the cleaned text and the number
    of redactions applied.
    """
    count = 0
    result = text

    for _label, pattern in _SECRET_PATTERNS:
        new_result, num = pattern.subn(_REDACTION, result)
        count += num
        result = new_result

    return SanitizedResult(clean_text=result, redaction_count=count)


def sanitize_batch(texts: dict[str, str]) -> tuple[dict[str, str], int]:
    """Sanitize a mapping of ``{key: text}`` and return cleaned dict + total redactions."""
    total = 0
    cleaned: dict[str, str] = {}
    for key, text in texts.items():
        res = sanitize(text)
        cleaned[key] = res.clean_text
        total += res.redaction_count
    return cleaned, total
