"""Explicit operation routing policy. Adapters never select a backup."""

import contextvars
import re
from contextlib import contextmanager

from vita.helpers.env import load_env
from vita.helpers.provider_errors import TRANSIENT, safe_route

VERSION = "provider-fallback/1"
PREFIXES = {"extract": "EXTRACTION", "requirements": "EXTRACTION", "analyze": "ANALYSIS",
            "adapt": "ADAPT", "review": "REVIEW", "cover": "COVER"}
ALLOWED = TRANSIENT | {"authentication", "permission", "invalid_model", "quota_exceeded"}
REASONING = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
_OVERRIDE = contextvars.ContextVar("vita_operation_fallback", default=None)
_PARENT = contextvars.ContextVar("vita_operation_parent", default=None)


def disabled():
    return {"version": VERSION, "enabled": False}


def validate_policy(value):
    if not isinstance(value, dict) or value.get("version") != VERSION or type(value.get("enabled")) is not bool:
        raise ValueError("Invalid fallback policy version/enabled flag")
    if not value["enabled"]:
        if value != disabled():
            raise ValueError("Disabled fallback policy must not carry routing fields")
        return value
    if set(value) != {"version", "enabled", "backup", "categories"}:
        raise ValueError("Invalid fallback policy fields")
    route = value["backup"]
    from vita.helpers.llm import _DEFAULT_MODELS
    public = safe_route(route) if isinstance(route, dict) else {}
    if (not isinstance(route, dict) or set(route) - {"provider", "model", "reasoning_effort"}
            or route.get("provider") not in _DEFAULT_MODELS
            or not isinstance(route.get("model"), str) or not route["model"].strip()
            or public["provider"] != route["provider"]
            or public["model"] != route["model"]):
        raise ValueError("Fallback requires an exact supported provider and safe model ID")
    if "reasoning_effort" in route and (route["provider"] not in ("codex", "openai", "openrouter")
                                         or route["reasoning_effort"] not in REASONING):
        raise ValueError("Unsupported fallback reasoning setting/provider")
    categories = value["categories"]
    if not isinstance(categories, list) or not categories or any(c not in ALLOWED for c in categories):
        raise ValueError("Unsupported fallback error category; validation/approval/source failures are never eligible")
    return value


def load_policy(step, env=None):
    step = step.removesuffix("-qualitative")
    if step not in PREFIXES:
        return disabled()  # Exact diagnostics and discovery never inherit fallback.
    override = _OVERRIDE.get()
    if env is None and override is not None and override[0] == step:
        return validate_policy(override[1])
    env = load_env() if env is None else env
    prefix = PREFIXES[step]
    def setting(suffix, default=""):
        inherited = env.get(f"ANALYSIS_FALLBACK_{suffix}") if prefix == "REVIEW" else None
        return env.get(f"{prefix}_FALLBACK_{suffix}", inherited if inherited is not None else env.get(f"VITA_FALLBACK_{suffix}", default)).strip()
    enabled = setting("ENABLED", "false").lower()
    if enabled not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        raise ValueError("FALLBACK_ENABLED must be true or false")
    if enabled in ("false", "0", "no", "off"):
        return disabled()
    route = {"provider": setting("PROVIDER").lower(), "model": setting("MODEL")}
    if setting("REASONING_EFFORT"):
        route["reasoning_effort"] = setting("REASONING_EFFORT")
    return validate_policy({"version": VERSION, "enabled": True, "backup": route,
                            "categories": sorted({c.strip() for c in setting("CATEGORIES", ",".join(sorted(TRANSIENT))).split(",")})})


def configured():
    """Only enabled policies enter new scope hashes; legacy disabled hashes survive."""
    env = load_env()
    return {step: policy for step in PREFIXES
            if (policy := load_policy(step, env))["enabled"]}


@contextmanager
def operation_policy(step, policy, parent_run_id=None):
    token = _OVERRIDE.set((step, validate_policy(policy))) if policy is not None else None
    parent = _PARENT.set(parent_run_id)
    try:
        yield
    finally:
        if token is not None:
            _OVERRIDE.reset(token)
        _PARENT.reset(parent)


def parent_run_id():
    value = _PARENT.get()
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) else None


def outcome_view(step):
    try:
        return _outcome_view(step)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("Invalid operation outcome; inspect/restore the private record before resuming") from None


def _outcome_view(step):
    """Public subset only; never forward unknown fields from a private record."""
    from pathlib import Path

    from vita.helpers.provider_error_catalog import ACTIONS
    from vita.helpers.structured import parse_json
    path = Path(f".vita/results/{step}.outcome.json")
    if not path.exists():
        return None
    data = parse_json(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("attempts"), list):
        raise ValueError("Unsupported operation record")
    def identity(value):
        return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) else None
    attempts = []
    for item in data.get("attempts", [])[:5]:
        error = item.get("error", {})
        category = item.get("category")
        attempts.append({"number": item.get("number") if type(item.get("number")) is int else None,
                         "attempt_id": identity(item.get("attempt_id")),
                         "parent_attempt_id": identity(item.get("parent_attempt_id")),
                         "kind": item.get("kind") if item.get("kind") in ("initial", "retry", "fallback") else None,
                         "requested": safe_route(item.get("requested", {})),
                         "effective": safe_route(item.get("route", {})),
                         "category": category if category in {*ACTIONS, "valid", "started", "invalid_json", "schema_error", "validation_error"} else "provider_error",
                         "retryable": error.get("retryable") is True,
                         "status": error.get("status") if type(error.get("status")) is int else None,
                         "fallback_reason": item.get("fallback_reason") if item.get("fallback_reason") in ALLOWED else None})
    result = {"run_id": identity(data.get("run_id")), "parent_run_id": identity(data.get("parent_run_id")),
              "status": data.get("status") if data.get("status") in ("success", "failed", "running") else "failed",
              "attempts": attempts, "cache_reused": data.get("cache", {}).get("status") == "hit"}
    error = data.get("error") or {}
    category = error.get("category", error.get("code"))
    if error:
        result["error"] = {"category": category if category in {*ACTIONS, "source_conflict", "artifact_error", "structured_output_invalid"} else "provider_error",
                           "retryable": error.get("retryable") is True}
    if data.get("routing"):
        routing = data["routing"]
        result["routing"] = {"version": VERSION, "requested": safe_route(routing.get("requested", {})),
                             "effective": safe_route(routing.get("effective") or {}),
                             "chain": [safe_route(route) for route in routing.get("chain", [])[:2]]}
    return result


def input_fingerprint(step):
    import hashlib
    from pathlib import Path

    from vita.helpers.approval import _scope
    from vita.helpers.candidate_evidence import capture_candidate_sources, stable_hash
    value = {"scope": _scope()}
    if step not in ("extract", "requirements"):
        value["sources"] = capture_candidate_sources()["sha256"]
    if step == "cover":
        from vita.helpers.config import load_config
        target = Path(load_config().get("cover_tex_entry", "cover-letter.tex"))
        value["target"] = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    return stable_hash(value)


def capabilities():
    return {"schema_version": 1, "version": VERSION, "default_enabled": False, "max_backups": 1,
            "budget": "shared VITA_PROVIDER_MAX_ATTEMPTS (1..5)",
            "shared_attempt_budget": {"variable": "VITA_PROVIDER_MAX_ATTEMPTS", "default": 3, "minimum": 1, "maximum": 5},
            "global_prefix": "VITA_FALLBACK_", "stage_prefixes": {s: p + "_FALLBACK_" for s, p in PREFIXES.items()},
            "reasoning_values": sorted(REASONING),
            "default_categories": sorted(TRANSIENT), "allowed_categories": sorted(ALLOWED),
            "amend_command": "vita fallback amend STEP --provider PROVIDER --model MODEL --dry-run --json",
            "exact_generation_checks": True}
