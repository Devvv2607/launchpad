"""Structured logging with request IDs and secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEYS = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|refresh|access_token)", re.I
)
# Usage counters that merely contain the word "token" (never secrets).
_SAFE_KEYS = re.compile(r"(tokens(_\w+)?|\w+_tokens|token_(budget|count)s?)", re.I)
# Bearer tokens / common key shapes that might leak inside free-text messages.
_SENSITIVE_VALUES = re.compile(
    r"(Bearer\s+[A-Za-z0-9._\-]+|sk-[A-Za-z0-9_\-]{10,}|gsk_[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_\-]{20,})"
)


def _sensitive(key: str) -> bool:
    return bool(_SENSITIVE_KEYS.search(key)) and not _SAFE_KEYS.fullmatch(key)


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return value
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if _sensitive(str(k)) else _redact(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_redact(v, depth + 1) for v in value)
    if isinstance(value, str):
        return _SENSITIVE_VALUES.sub("[REDACTED]", value)
    return value


def redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict.keys()):
        if _sensitive(key):
            event_dict[key] = "[REDACTED]"
        else:
            event_dict[key] = _redact(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", json: bool = False) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_processor,
    ]
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Route stdlib (uvicorn, sqlalchemy, arq) through the same level.
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(name)s %(message)s")


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
