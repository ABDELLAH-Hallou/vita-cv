"""Host-only, explicit run authorization. Never read consent from env or models."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from vita.helpers.structured import TEXT, object_schema, validate

MODES = ("human", "auto", "unattended")
VERSION = "approval-policy/1"
WARNING = ("Unattended approval accepts AI proposals without human review and can publish "
           "inaccurate wording into the local CV. It does not guarantee factual correctness.")
POLICY_SCHEMA = object_schema({
    "version": {"type": "string", "const": VERSION},
    "mode": {"type": "string", "enum": list(MODES)},
})
AUTHORIZATION_SCHEMA = object_schema({
    "policy": POLICY_SCHEMA, "run_id": TEXT, "attempt_id": TEXT,
    "authorized_at": TEXT, "attempt_at": TEXT, "scope_sha256": TEXT,
})
DECISION_SCHEMA = object_schema({
    "policy": POLICY_SCHEMA, "revision": TEXT,
    "source": {"type": "string", "enum": ["explicit_human_review", "unattended_run_policy"]},
    "run_id": TEXT, "attempt_id": TEXT, "authorized_at": TEXT,
    "timestamp": TEXT, "scope_sha256": TEXT,
})


def policy(mode):
    if mode not in MODES:
        raise ValueError("Approval must be human, auto, or unattended")
    return {"version": VERSION, "mode": mode}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _scope():
    # Only hashes leave this helper. Credentials and personal source text never
    # belong in approval provenance. Source snapshots bind the exact CV later.
    files = [Path("job.md"), *(Path(".vita") / name for name in
              ("config.json", "extensions.json", ".env"))]
    values = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
              for p in files}
    values["project"] = str(Path.cwd().resolve())
    from vita.helpers.pipeline_config import load_pipeline_settings
    settings = load_pipeline_settings()
    values["routing"] = {step: route.kwargs() for step, route in settings.routes.items()}
    values["extraction"] = settings.extraction_enabled
    from vita.helpers.fallback import configured
    if policies := configured():
        values["fallback"] = policies
    for path in sorted(Path(".vita/skills").rglob("*")):
        if path.is_file():
            values[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def capture(mode, previous=None):
    """Called only after an explicit CLI/API mode selection, once per attempt."""
    selected = policy(mode)
    if previous is not None:
        assert_authorized(previous, mode)
    now = _now()
    return {"policy": selected, "run_id": previous["run_id"] if previous else uuid.uuid4().hex,
            "attempt_id": uuid.uuid4().hex,
            "authorized_at": previous["authorized_at"] if previous else now,
            "attempt_at": now, "scope_sha256": _scope()}


def validate_authorization(value):
    validate(value, AUTHORIZATION_SCHEMA)
    for key in ("run_id", "attempt_id"):
        if len(value[key]) != 32 or any(c not in "0123456789abcdef" for c in value[key]):
            raise ValueError("Invalid approval run/attempt identity")
    for key in ("authorized_at", "attempt_at"):
        if datetime.fromisoformat(value[key]).utcoffset() is None:
            raise ValueError("Approval timestamps must include a timezone")


def assert_authorized(value, mode="unattended"):
    validate_authorization(value)
    if value["policy"] != policy(mode) or value["scope_sha256"] != _scope():
        raise ValueError("Approval policy or captured job/settings changed; start a new authorized run")


def decision(revision, authorization=None):
    if authorization is None:
        authorization = capture("human")
        source = "explicit_human_review"
    else:
        assert_authorized(authorization)
        source = "unattended_run_policy"
    return {"policy": authorization["policy"], "revision": revision, "source": source,
            **{k: authorization[k] for k in
               ("run_id", "attempt_id", "authorized_at", "scope_sha256")}, "timestamp": _now()}


def validate_decision(value, revision):
    validate(value, DECISION_SCHEMA)
    expected = "unattended" if value["source"] == "unattended_run_policy" else "human"
    validate_authorization({k: value[k] for k in
                            ("policy", "run_id", "attempt_id", "authorized_at", "scope_sha256")} |
                           {"attempt_at": value["timestamp"]})
    if value["revision"] != revision or value["policy"] != policy(expected):
        raise ValueError("Approval provenance does not match the exact revision/policy")
