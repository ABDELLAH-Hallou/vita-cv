"""Versioned public provider failures; raw bodies and exceptions stay private."""

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from vita.helpers.env import load_env
from vita.helpers.provider_error_catalog import ACTIONS

TRANSIENT = {"overloaded", "rate_limit", "server_error", "timeout", "connection"}
DIAGNOSTIC_CATEGORIES = {"tls", "response_shape", "response_decode"}

# Public contract for consumers such as Vita Tree. Additive optional fields are
# allowed within v1; changing meanings/required fields requires a new version.
PROVIDER_ERROR_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "code": {"type": "string", "const": "provider_error"},
        "category": {"type": "string", "enum": [key for key in ACTIONS if key not in DIAGNOSTIC_CATEGORIES]},
        **{key: {"type": ["string", "null"]} for key in ("provider", "model", "step")},
        "status": {"type": ["integer", "null"], "minimum": 100, "maximum": 599},
        "retryable": {"type": "boolean"}, "exhausted": {"type": "boolean"},
        **{key: {"type": "integer", "minimum": 0, "maximum": 5} for key in ("attempts", "max_attempts")},
        "retry_after_seconds": {"type": ["number", "null"], "minimum": 0},
        "action": {"type": "string"},
        "retry_stopped": {"type": "string", "enum": ["retry_after_exceeds_delay_cap"]},
    },
    "required": ["schema_version", "code", "category", "provider", "model", "step", "status",
                 "retryable", "exhausted", "attempts", "max_attempts", "retry_after_seconds", "action"],
}


def safe_step(value: str) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,60}", value) else "generation"


def safe_identifier(value, secrets=()) -> str | None:
    """Identifiers are allowlisted tokens, never URLs with queries or arbitrary prose."""
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,159}", value)
            or "://" in value or any(secret and secret in value for secret in secrets)
            or re.search(r"(?:sk-|AIza|Bearer|api[_-]?key|token=)", value, re.IGNORECASE)):
        return None
    return value


def safe_route(route: dict, session: dict | None = None) -> dict:
    session = session or {}
    resolved = session.get("resolved")
    try:
        env = resolved[3] if resolved else load_env()
    except (ValueError, OSError):
        env = {}
    secrets = [str(value) for key, value in env.items()
               if any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))]
    actual = session.get("route", route)
    return {key: safe_identifier(actual.get(key), secrets) for key in ("provider", "model", "reasoning_effort")}


def http_category(status: int | None, body: str = "") -> str:
    if status == 401:
        return "authentication"
    if status == 403:
        return "permission"
    if status in (503, 529):
        return "overloaded"
    if status == 429:
        return "quota_exceeded" if "insufficient_quota" in body or "billing_hard_limit" in body else "rate_limit"
    if status in (408, 504):
        return "timeout"
    if status in (500, 502):
        return "server_error"
    text = body.lower()
    if status in (400, 404, 422) and (any(code in text for code in (
            "model_not_found", "invalid_model", "model_not_available", "not a valid model id"))
            or re.search(r"\bmodel(?:s/[^\s\"]+|[^.!?\n]{0,180})\s+(?:is |was )?(?:not found|does not exist|not supported|not available)", text)):
        return "invalid_model"
    if status == 404:
        return "not_found"
    return "invalid_request" if status in (400, 422) else "provider_error"


def retry_after_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r"\d+", value.strip()):
            # Never turn an unbounded integer header into a huge Python integer.
            return float(value.strip()) if len(value.strip()) < 19 else 1e18
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (parsed - (now or datetime.now(timezone.utc))).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


class ProviderError(RuntimeError):
    def __init__(self, message: str = "", code: str = "provider_error", status: int | None = None,
                 *, retry_after: float | None = None):
        # The supplied message may contain keys, URLs, CLI stderr or candidate data.
        # Never retain it in the public exception, repr, trace or result.
        self.code = http_category(status) if code == "provider_error" and status is not None else code
        if self.code not in ACTIONS:
            self.code = "provider_error"
        self.diagnostic_category = self.code
        # Keep the existing outcome v1 category vocabulary. More precise causes
        # belong to the separate diagnostic contract, not a silent enum change.
        if self.code in DIAGNOSTIC_CATEGORIES:
            self.code = "provider_error"
        self.status = status if type(status) is int and 100 <= status <= 599 else None
        self.retryable = self.code in TRANSIENT
        self.retry_after = retry_after if isinstance(retry_after, (int, float)) and math.isfinite(retry_after) and retry_after >= 0 else None
        super().__init__(ACTIONS[self.diagnostic_category])

    def contract(self, *, step: str, route: dict, attempts: int, max_attempts: int,
                 exhausted: bool = False) -> dict:
        return {"schema_version": 1, "code": "provider_error", "category": self.code,
                "provider": route.get("provider"), "model": route.get("model"), "step": safe_identifier(step),
                "status": self.status, "retryable": self.retryable, "attempts": attempts,
                "max_attempts": max_attempts, "exhausted": exhausted,
                "retry_after_seconds": self.retry_after, "action": str(self)}


def normalize_error(exc: Exception) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, TimeoutError):
        return ProviderError(code="timeout")
    return ProviderError()


class UnsupportedSchema(ProviderError):
    def __init__(self, status: int | None = None):
        super().__init__(code="unsupported_schema", status=status)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_seconds: float = 1.0
    max_seconds: float = 30.0

    @classmethod
    def load(cls):
        env = load_env()
        try:
            attempts = int(env.get("VITA_PROVIDER_MAX_ATTEMPTS", "3"))
            base = float(env.get("VITA_PROVIDER_RETRY_BASE_SECONDS", "1"))
            cap = float(env.get("VITA_PROVIDER_RETRY_MAX_SECONDS", "30"))
            if not (1 <= attempts <= 5 and math.isfinite(base) and math.isfinite(cap) and 0 <= base <= cap <= 30):
                raise ValueError()
            return cls(attempts, base, cap)
        except (ValueError, TypeError, OverflowError):
            raise ProviderError(code="configuration") from None

    def delay(self, error: ProviderError, number: int) -> float | None:
        # Stop rather than retry earlier than the server's requested delay.
        if error.retry_after is not None and error.retry_after > self.max_seconds:
            return None
        return max(min(self.max_seconds, self.base_seconds * 2 ** (number - 1)), error.retry_after or 0)
