"""Local diagnostics v1. Only the privacy boundary may construct persisted data.

No collector, database, provider call, business-output write or retry lives here.
Raw strings/exception messages are deliberately not a logging interface.
"""

import atexit
import contextvars
import functools
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from vita import __version__

VERSION = 1
CAPTURE_STATUSES = ("captured", "redacted", "disabled", "suppressed", "truncated", "unavailable")
PHASES = ("workflow", "step", "configuration", "context", "prompt", "provider_request", "decoding", "validation", "persistence")
EVENTS = ("span_start", "span_end", "attempt", "retry", "route", "capture", "error", "cache")
CATEGORIES = ("configuration", "authentication", "permission", "overloaded", "rate_limit", "server_error",
              "timeout", "connection", "tls", "invalid_model", "quota_exceeded", "invalid_request", "not_found",
              "unsupported_schema", "refusal", "incomplete_response", "empty_response", "provider_error",
              "response_shape", "response_decode", "invalid_json", "schema_error", "validation_error",
              "artifact_error", "unclassified", "interrupted")
PROVIDERS = ("openai", "openrouter", "gemini", "google", "codex", "anthropic", "groq", "mistral", "deepseek", "xai", "together", "perplexity", "cohere")
_CURRENT = contextvars.ContextVar("vita_diagnostic_trace", default=None)
_SPAN = contextvars.ContextVar("vita_diagnostic_span", default=None)
_STEP = contextvars.ContextVar("vita_diagnostic_step", default=None)
_PACKAGE = Path(__file__).resolve().parents[1]
_IO_LOCK = threading.RLock()
_LOCK_PAUSE = time.sleep  # Independent of provider backoff hooks used in fixtures.
ARTIFACT_LIMIT = 16384
EVENT_LIMIT = 262144
EVENT_FILES = 4
PROCESS_LIMIT = 2 * 1024 * 1024
TOTAL_LIMIT = 50 * 1024 * 1024
TRACE_LIMIT = 100
RETENTION_SECONDS = 7 * 86400


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def project_root() -> Path:
    explicit = os.environ.get("VITA_PROJECT_ROOT")
    if explicit:
        path = Path(explicit)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("invalid project root")
        return path.resolve()
    start = Path.cwd().resolve()
    return next((p for p in (start, *start.parents) if (p / ".vita").is_dir()), start)


def project_settings(root):
    values = {}
    try:
        for line in (root / ".vita/.env").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or key.startswith("#"):
                continue
            value = value.strip()
            if value.startswith(("\"", "'")):
                end = value.find(value[0], 1)
                if end < 0:
                    continue
                value = value[1:end]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            values[key] = value
    except (OSError, UnicodeError):
        # Missing/unreadable project settings cannot enable content capture.
        pass
    return values


def destination(root: Path) -> Path:
    override = os.environ.get("VITA_DIAGNOSTICS_DIR", project_settings(root).get("VITA_DIAGNOSTICS_DIR"))
    path = Path(override) if override else root / ".vita/logs/traces"
    if not path.is_absolute():
        raise ValueError("diagnostics destination must be absolute")
    return path.resolve()


def trace_context(value):
    match = re.fullmatch(r"00-([0-9a-f]{32})-([0-9a-f]{16})-(00|01)", value or "")
    if match and int(match[1], 16) and int(match[2], 16):
        return match[1], match[2], match[3]
    return uuid.uuid4().hex, None, "01"


def _json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".diagnostic-")
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class PrivacyBoundary:
    """Source-aware, content-free defaults. Regex alone is not anonymization."""

    def __init__(self, root: Path):
        self.secrets = set()
        self.add_secrets(os.environ)
        self.add_secrets(project_settings(root))
        self.add_secrets(project_settings(Path.cwd()))

    def add_secrets(self, values):
        for key, value in values.items():
            if any(s in key.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and isinstance(value, str) and value:
                self.secrets.add(value)

    def token(self, value):
        if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}", value)
                or "://" in value or any(s in value for s in self.secrets)
                or re.search(r"sk-|AIza|Bearer|@|api[_-]?key", value, re.IGNORECASE)):
            return None
        return value

    def details(self, raw):
        result = {}
        for key, value in raw.items():
            if key in ("attempt", "attempts", "max_attempts", "http_status", "line", "column", "offset", "bytes", "chars"):
                if type(value) is int and 0 <= value <= 10 ** 12:
                    result[key] = value
            elif key in ("duration_ms", "delay_seconds", "retry_after_seconds"):
                if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10 ** 18:
                    result[key] = round(value, 3)
            elif key in ("requested_provider", "effective_provider"):
                result[key] = value if value in PROVIDERS else None
            elif key in ("requested_model", "effective_model", "reasoning"):
                result[key] = self.token(value)
            elif key in ("prompt_sha256", "schema_sha256", "adapter_sha256", "request_id_sha256"):
                if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
                    result[key] = value
            elif key == "outcome_run_id":
                if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value):
                    result[key] = value
            elif key == "category":
                result[key] = value if value in CATEGORIES else "unclassified"
            elif key in ("retryable", "credential_present", "response_exists", "http_response_exists", "reused"):
                if type(value) is bool or value is None:
                    result[key] = value
            elif key == "credential_variable":
                if value in {p.upper() + "_API_KEY" for p in PROVIDERS}:
                    result[key] = value
            elif key in ("credential_origin", "provider_origin", "model_origin", "reasoning_origin"):
                result[key] = value if value in ("process", "project_env", "extensions", "explicit", "default", "cli_inherited", "absent", "unreported") else "unreported"
            elif key == "provider_code":
                result[key] = value if value in ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND", "INVALID_ARGUMENT", "model_not_found", "invalid_model", "invalid_api_key", "insufficient_quota", "rate_limit_exceeded") else "unclassified"
            elif key == "location":
                fields = {"schema_version", "overall_score", "category_scores", "executive_summary", "strengths", "gaps", "recommendations", "metrics", "criteria", "id", "job_id", "category", "criterion", "importance", "status", "evidence", "evidence_kind", "evidence_refs", "feedback", "source_id", "quote", "line_start", "line_end", "matched_count", "partial_count", "missing_count", "total_count", "source_sha256", "jobs", "title", "company", "location", "requirements", "answer"}
                if isinstance(value, str) and re.fullmatch(r"\$(?:\.[a-z_]{1,40}|\[\d{1,6}\]){0,12}", value) and all(p in fields for p in re.findall(r"\.([a-z_]+)", value)):
                    result[key] = value
            elif key == "exception_type":
                result[key] = value if value in ("RuntimeError", "AttributeError", "IndexError", "RecursionError", "ValueError", "TypeError", "KeyError", "OSError", "PermissionError", "FileNotFoundError", "TimeoutError", "JSONDecodeError", "UnicodeDecodeError", "HTTPError", "URLError", "SSLError", "SSLCertVerificationError", "ProviderError", "UnsupportedSchema", "StructuredOutputError", "KeyboardInterrupt", "SystemExit") else "unclassified_exception"
        return result

    def shape(self, value, depth=0):
        if depth > 6:
            return {"capture_status": "truncated"}
        if isinstance(value, dict):
            if value.get("thought") is True or value.get("type") in ("thinking", "reasoning"):
                return {"capture_status": "suppressed"}
            # Keys may also be personal. Keep only a fixed vocabulary, never
            # echo arbitrary source keys, model prose or hidden reasoning.
            public = {"error", "code", "status", "message", "choices", "candidates", "content", "parts", "text", "finish_reason", "finishReason", "refusal", "model", "schema_version", "overall_score", "category_scores", "metrics", "criteria", "id", "evidence", "strengths", "gaps", "recommendations", "jobs", "title", "company"}
            return {"type": "object", "fields": [{"field": k if k in public else "[REDACTED_FIELD]",
                    "value": self.shape(v, depth + 1) if k not in ("thought", "reasoning", "reasoning_content", "chain_of_thought") else {"capture_status": "suppressed"}}
                    for k, v in list(value.items())[:30]], "field_count": len(value)}
        if isinstance(value, list):
            return {"type": "array", "length": len(value), "items": [self.shape(v, depth + 1) for v in value[:10]]}
        return {"type": type(value).__name__ if type(value) in (str, int, float, bool, type(None)) else "unknown",
                "value": "[REDACTED]", "chars": len(value) if isinstance(value, str) else None}

    def schema_view(self, schema, depth=0):
        if not isinstance(schema, dict) or depth > 10:
            return {"capture_status": "suppressed"}
        types = schema.get("type", [])
        types = types if isinstance(types, list) else [types]
        result = {"type": [t for t in types if t in ("string", "object", "array", "number", "integer", "boolean", "null")]}
        fields = {"schema_version", "overall_score", "category_scores", "executive_summary", "strengths", "gaps", "recommendations", "metrics", "criteria", "id", "job_id", "category", "criterion", "importance", "status", "evidence", "evidence_kind", "evidence_refs", "feedback", "source_id", "quote", "line_start", "line_end", "matched_count", "partial_count", "missing_count", "total_count", "source_sha256", "jobs", "title", "company", "location", "date_posted", "hard_skills", "soft_skills", "requirements", "must_have", "nice_to_have", "responsibilities", "summary"}
        if isinstance(schema.get("properties"), dict):
            result["properties"] = [{"field": k if k in fields else "[CUSTOM_FIELD]", "schema": self.schema_view(v, depth + 1)} for k, v in list(schema["properties"].items())[:100]]
        if "items" in schema:
            result["items"] = self.schema_view(schema["items"], depth + 1)
        result["required_count"] = len(schema.get("required", [])) if isinstance(schema.get("required", []), list) else 0
        return result


class Trace:
    def __init__(self):
        self.trace_id, self.parent_id, self.flags = trace_context(os.environ.get("VITA_TRACEPARENT"))
        self.process_id = uuid.uuid4().hex
        self.path = None
        self.capture = os.environ.get("VITA_DIAGNOSTIC_CONTENT", "off") == "sanitized"
        self.failed_logging = False
        self.warned = False
        self.sequence = self.rotation = 0
        self.failure = None
        self.route = {}
        self.response_exists = None
        self.attempt_id = None
        self.refs = []
        self.active = []
        self.closed = False
        self.sizes = {}
        self.reservation = None
        self.workflow_id = uuid.uuid4().hex
        self.privacy = PrivacyBoundary(Path.cwd())
        try:
            self.root = project_root()
            self.capture = os.environ.get("VITA_DIAGNOSTIC_CONTENT", project_settings(self.root).get("VITA_DIAGNOSTIC_CONTENT", "off")) == "sanitized"
            self.privacy = PrivacyBoundary(self.root)
            self.base = destination(self.root)
            self.path = self.base / self.trace_id
            self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                self.base.chmod(0o700)
                self.path.chmod(0o700)
            with _IO_LOCK, storage_lock(self.base):
                ignore = self.base / ".gitignore"
                if ignore.is_symlink():
                    raise OSError("unsafe diagnostics ignore path")
                prior = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
                rules = "/" + "[0-9a-f]" * 32 + "/\n/.reserve-*.json\n/.storage.lock\n"
                if rules not in prior:
                    _atomic(ignore, (prior.rstrip() + "\n" + rules).encode())
                enforce_storage(self.base, self.trace_id, PROCESS_LIMIT)
                self.reservation = self.base / f".reserve-{self.process_id}.json"
                _atomic(self.reservation, (_json({"bytes": PROCESS_LIMIT, "trace_id": self.trace_id}) + "\n").encode())
            self._write("manifest.json", {"schema_version": VERSION, "trace_id": self.trace_id,
                        "product": "vita-cv", "product_version": __version__, "ownership": "project",
                        "trace_context_status": "accepted" if self.parent_id else "rejected" if os.environ.get("VITA_TRACEPARENT") else "generated",
                        "process_manifests": "process-*.json", "events": "events-*.jsonl",
                        "artifact_limit_bytes": ARTIFACT_LIMIT, "content_policy": "source-aware-structure-only"})
            self.state("running")
            atexit.register(self.abandon)
        except (OSError, ValueError, RuntimeError):
            self.warning()

    def warning(self):
        self.failed_logging = True
        if not self.warned:
            print("VITA diagnostics could not be fully saved (access, quota or configuration). The operation/retry policy is unchanged.", file=sys.stderr)
            self.warned = True

    def _write(self, name, value):
        # All callers supply records constructed by this module's boundary.
        if self.path is None or self.failed_logging:
            return False
        try:
            data = (_json(value) + "\n").encode()
            with _IO_LOCK, storage_lock(self.base):
                if self.path.is_symlink() or (self.path / "artifacts").is_symlink():
                    raise OSError("unsafe diagnostic path")
                if sum(self.sizes.values()) - self.sizes.get(name, 0) + len(data) > PROCESS_LIMIT:
                    raise OSError("process diagnostic quota reached")
                _atomic(self.path / name, data)
                self.sizes[name] = len(data)
            return True
        except (OSError, ValueError, RuntimeError):
            self.warning()
            return False

    def state(self, status):
        return self._write(f"process-{self.process_id}.json", {
            "schema_version": VERSION, "trace_id": self.trace_id, "process_id": self.process_id,
            "product_version": __version__,
            "status": status, "updated_at": now(), "active_spans": list(self.active),
            "failure": self.failure, "capture_enabled": self.capture,
            "diagnostic_artifacts": self.refs[-100:], "logging_complete": not self.failed_logging})

    def event(self, event_type, phase, status="ok", **details):
        if event_type not in EVENTS or phase not in PHASES or self.failed_logging:
            return
        self.sequence += 1
        event = {"schema_version": VERSION, "trace_id": self.trace_id, "process_id": self.process_id,
                 "workflow_id": self.workflow_id, "step": (_STEP.get() or (None, None))[0],
                 "step_id": (_STEP.get() or (None, None))[1],
                 "attempt_id": self.attempt_id,
                 "sequence": self.sequence, "timestamp": now(), "event": event_type, "phase": phase,
                 "span_id": _SPAN.get(), "parent_span_id": self.active[-1]["parent_span_id"] if self.active else self.parent_id,
                 "status": status if status in ("ok", "error", "running", "interrupted") else "error",
                 "details": self.privacy.details(details)}
        try:
            line = (_json(event) + "\n").encode()
            with _IO_LOCK, storage_lock(self.base):
                name = self.path / f"events-{self.process_id}-{self.rotation}.jsonl"
                if name.exists() and name.stat().st_size + len(line) > EVENT_LIMIT:
                    self.rotation += 1
                    name = self.path / f"events-{self.process_id}-{self.rotation}.jsonl"
                    if self.rotation >= EVENT_FILES:
                        old = f"events-{self.process_id}-{self.rotation - EVENT_FILES}.jsonl"
                        (self.path / old).unlink(missing_ok=True)
                        self.sizes.pop(old, None)
                if sum(self.sizes.values()) + len(line) > PROCESS_LIMIT:
                    raise OSError("process diagnostic quota reached")
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "ab") as stream:
                    stream.write(line)
                    stream.flush()
                self.sizes[name.name] = self.sizes.get(name.name, 0) + len(line)
        except (OSError, ValueError, RuntimeError):
            self.warning()

    def artifact(self, kind, content=None, *, exists=None):
        if kind not in ("request", "response", "http_response", "provider_error", "schema", "instructions"):
            return None
        status, reason, safe = "unavailable", "not_observed", None
        if kind == "request":
            status, reason = "redacted", "sensitive_sections_replaced"
            safe = {"sections": [{"label": label if label in ("system", "user") else "sensitive_section", "content": "[SENSITIVE_CONTENT]", "chars": len(text), "lines": text.count("\n") + 1}
                                  for label, text in content], "exact_prompt_captured": False}
        elif kind == "instructions":
            status, reason = "captured", "host_safe_summary"
            safe = {"source": "diagnostic-summary-not-exact-prompt", "instructions": ["Use the supplied evidence only.", "Follow the host output contract and validation."]}
        elif kind == "schema":
            status, reason = "redacted", "schema_structure_only"
            safe = self.privacy.schema_view(content)
        elif exists is False:
            reason = "no_model_response_produced" if kind == "response" else "no_http_response"
        elif content is not None:
            if not self.capture:
                status, reason = "disabled", "content_capture_off"
            elif isinstance(content, (dict, list)):
                status, reason, safe = "redacted", "all_source_values_removed", self.privacy.shape(content)
            else:
                try:
                    parsed = json.loads(content) if len(content) <= ARTIFACT_LIMIT * 8 else None
                    if parsed is not None:
                        status, reason, safe = "redacted", "all_source_values_removed", self.privacy.shape(parsed)
                    else:
                        status, reason = "suppressed", "cannot_establish_safe_structure"
                except (ValueError, TypeError, RecursionError):
                    status, reason = "suppressed", "cannot_establish_safe_structure"
        reference = {"id": uuid.uuid4().hex, "kind": kind, "capture_status": status,
                     "step_id": (_STEP.get() or (None, None))[1], "attempt_id": self.attempt_id,
                     "reason": reason, "content_exists": exists, "path": None, "bytes": 0}
        if safe is not None:
            payload = {"schema_version": VERSION, "kind": kind, "capture_status": status, "data": safe}
            if len(_json(payload).encode()) > ARTIFACT_LIMIT:
                reference.update(capture_status="truncated", reason="artifact_size_limit")
                payload = {"schema_version": VERSION, "kind": kind, "capture_status": "truncated",
                           "data": {"content": "[SUPPRESSED_SIZE_LIMIT]"}}
            name = f"artifacts/{self.process_id}-{reference['id']}.json"
            if self._write(name, payload):
                reference.update(path=name, bytes=len((_json(payload) + "\n").encode()))
            else:
                reference.update(capture_status="unavailable", reason="logging_failure")
        self.refs.append(reference)
        self.event("capture", "prompt" if kind in ("request", "schema", "instructions") else "decoding")
        self.state("running")
        return reference

    def error(self, phase, exc=None, **details):
        category = details.get("category") or getattr(exc, "diagnostic_category", getattr(exc, "code", "unclassified"))
        if category == "provider_error":
            category = "unclassified"
        details.update(category=category, exception_type=type(exc).__name__ if exc is not None else None)
        if isinstance(exc, ValueError):
            location = re.match(r"^(\$(?:\.[a-z_]{1,40}|\[\d{1,6}\]){0,12}):", str(exc))
            if location:
                details["location"] = location[1]
        self.event("error", phase, "error", **details)
        if self.failure is not None and self.failure["phase"] == phase:
            cleaned = self.privacy.details(details)
            if cleaned.get("category") == "unclassified" and self.failure["details"].get("category") != "unclassified":
                cleaned.pop("category", None)
            self.failure["details"].update(cleaned)
        if self.failure is None:
            frames = []
            if exc is not None:
                for frame in traceback.extract_tb(exc.__traceback__)[-8:]:
                    try:
                        module = Path(frame.filename).resolve().relative_to(_PACKAGE).as_posix()
                    except ValueError:
                        module = "external"
                    # No source line, function arguments, locals or external paths.
                    frames.append({"module": module, "line": frame.lineno})
            self.failure = {"phase": phase, "details": self.privacy.details(details), "frames": frames}
            self.state("running")

    def close(self, status):
        if not self.closed:
            self.state(status)
            self.closed = True
            if self.reservation:
                try:
                    self.reservation.unlink(missing_ok=True)
                except OSError:
                    self.warning()
            atexit.unregister(self.abandon)

    def abandon(self):
        self.close("incomplete")

    def explain(self):
        from vita.helpers.provider_error_catalog import ACTIONS
        failure = self.failure or {"phase": "step", "details": {"category": "unclassified"}}
        route = self.route
        details = failure["details"]
        action = ACTIONS.get(details.get("category"), "Inspect the recorded phase, exception type and validation location; the cause is unclassified. Previously discarded content cannot be reconstructed.")
        print(f"Failed phase: {failure['phase']}; provider/model: {route.get('effective_provider') or 'unreported'}/{route.get('effective_model') or 'unreported'}; "
              f"category: {details.get('category', 'unclassified')}; HTTP: {details.get('http_status', 'unavailable')}.\n"
              f"Trace: {self.trace_id}\nDiagnostics: {self.path or 'unavailable'}\n"
              f"Model response: { {True: 'observed', False: 'not produced', None: 'unknown'}.get(self.response_exists)}; "
              f"sanitized content capture: {'enabled' if self.capture else 'disabled'}. "
              f"{action}\nInspect with vita diagnostics inspect {self.trace_id}.", file=sys.stderr)


@contextmanager
def storage_lock(base):
    """Cross-process quota/rotation lock. Contention degrades diagnostics only."""
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = base / ".storage.lock"
    if lock.is_symlink():
        raise OSError("unsafe lock path")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        # Windows permits locking beyond EOF. Do not initialize a byte before
        # acquiring its lock: another process may already own that byte.
        for _ in range(200):
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, PermissionError):
                _LOCK_PAUSE(0.01)
        else:
            raise OSError("diagnostic lock contention")
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def enforce_storage(base, current, incoming):
    traces = [p for p in base.iterdir() if p.is_dir() and re.fullmatch(r"[0-9a-f]{32}", p.name) and not p.is_symlink()]
    removable = []
    reservations = [json.loads(p.read_text()) for p in base.glob(".reserve-*.json") if not p.is_symlink()]
    reserved_traces = {r["trace_id"] for r in reservations}
    size = sum(r["bytes"] for r in reservations)
    for path in traces:
        files = [p for p in path.rglob("*") if p.is_file() and not p.is_symlink()]
        total = sum(p.stat().st_size for p in files)
        size += total
        # Active/incomplete traces are never removed automatically. Hard quota
        # stops capture if completed traces cannot make enough room.
        states = [json.loads(p.read_text()) for p in files if re.fullmatch(r"process-[0-9a-f]{32}\.json", p.name)]
        if path.name != current and path.name not in reserved_traces and states and all(s.get("status") in ("success", "failed", "interrupted") for s in states):
            removable.append((path.stat().st_mtime, path, total))
    for timestamp, path, total in sorted(removable):
        if size + incoming > TOTAL_LIMIT or len(traces) > TRACE_LIMIT or time.time() - timestamp > RETENTION_SECONDS:
            # Resolved targets must stay directly inside the chosen store.
            if path.resolve().parent == base.resolve():
                shutil.rmtree(path)
                size -= total
                traces.remove(path)
    if size + incoming > TOTAL_LIMIT or len(traces) > TRACE_LIMIT:
        raise OSError("diagnostic quota reached")


def current():
    return _CURRENT.get()


@contextmanager
def span(phase, **details):
    trace = current()
    if trace is None:
        yield {"status": "ok"}
        return
    span_id = uuid.uuid4().hex[:16]
    parent = _SPAN.get() or trace.parent_id
    token = _SPAN.set(span_id)
    trace.active.append({"span_id": span_id, "parent_span_id": parent, "phase": phase})
    trace.event("span_start", phase, "running", **details)
    trace.state("running")
    started = time.monotonic()
    status = "ok"
    outcome = {"status": "ok"}
    try:
        yield outcome
    except BaseException as exc:
        status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "error"
        trace.error(phase, exc, **details)
        raise
    finally:
        trace.event("span_end", phase, status if status != "ok" else outcome["status"], duration_ms=(time.monotonic() - started) * 1000, **details)
        trace.active.pop()
        trace.state("running")
        _SPAN.reset(token)


def phase(name):
    def decorate(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            with span(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def diagnosed(kind="step", name=None):
    def decorate(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            owner = current() is None
            trace = current() or Trace()
            context = _CURRENT.set(trace)
            selected = name or kwargs.get("step") or (args[0] if args and isinstance(args[0], str) else None)
            selected = selected if selected in ("extract", "requirements", "analyze", "adapt", "review", "cover", "analyze-qualitative", "review-qualitative", "provider-check", "provider-discovery") else "operation"
            prior_step = _STEP.get()
            if kind == "step" and (prior_step is None or prior_step[0] != selected):
                trace.failure = None
                trace.route = {}
                trace.response_exists = None
                trace.attempt_id = None
            step_context = _STEP.set((selected, uuid.uuid4().hex)) if kind == "step" else None
            status = "failed"
            try:
                with span(kind) as outcome:
                    value = function(*args, **kwargs)
                    if value is False:
                        outcome["status"] = "error"
                        if trace.failure is None:
                            trace.error(kind, category="unclassified")
                status = "failed" if value is False else "success"
                if status == "failed" and owner:
                    trace.explain()
                return value
            except BaseException as exc:
                status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
                if owner:
                    trace.explain()
                raise
            finally:
                if owner:
                    trace.close(status)
                if step_context is not None:
                    _STEP.reset(step_context)
                _CURRENT.reset(context)
        return wrapped
    return decorate


def emit(event_type, phase, **details):
    if current():
        current().event(event_type, phase, **details)


def failure(phase, exc=None, **details):
    if current():
        current().error(phase, exc, **details)


def capture(kind, content=None, *, exists=None):
    if current() and not current().failed_logging:
        return current().artifact(kind, content, exists=exists)
    return None


def validation_detail(exc):
    """Keep the legacy detail string without copying arbitrary exception prose."""
    text = str(exc) if type(exc) is ValueError else ""
    matched = re.fullmatch(r"(\$(?:\.[a-z_]+|\[\d+\])*): (missing required or unexpected fields|number outside allowed range|empty text|invalid enum value|unsupported schema/rubric version|too few items|expected (?:string|number|integer|object|array|boolean))", text)
    if matched:
        boundary = current().privacy if current() else PrivacyBoundary(Path.cwd())
        location = boundary.details({"location": matched[1]}).get("location", "$")
        return location + ": " + matched[2]
    return "Host validation rejected job identifiers, source provenance, evidence, or locked criteria."


def routing(requested_provider, requested_model, resolved, origins=None):
    trace = current()
    if trace is None:
        return
    provider, model, config, env = resolved
    trace.privacy.add_secrets(env)
    route = trace.privacy.details({"requested_provider": requested_provider, "requested_model": requested_model,
                                  "effective_provider": provider, "effective_model": model,
                                  "reasoning": config.get("reasoning_effort"), **(origins or {})})
    trace.route.update(route)
    trace.event("route", "configuration", **route)
    key = f"{provider.upper()}_API_KEY"
    if provider == "google" and not env.get(key):
        key = "GEMINI_API_KEY"
    origin = "process" if os.environ.get(key) else "project_env" if env.get(key) else "absent"
    trace.event("route", "configuration", credential_present=None if provider == "codex" else bool(env.get(key)), credential_variable=key,
                credential_origin="cli_inherited" if provider == "codex" else origin,
                adapter_sha256=sha((_PACKAGE / "helpers/llm.py").read_text(encoding="utf-8")))


def http_metadata(status, headers, body=None, *, rejected=False):
    trace = current()
    if trace is None:
        return
    details = {"http_status": status, "http_response_exists": True}
    for name in ("x-request-id", "request-id", "x-goog-request-id", "x-amzn-requestid"):
        value = headers.get(name) if headers else None
        if isinstance(value, str):
            details["request_id_sha256"] = sha(value)
            break
    if rejected:
        trace.response_exists = False
        capture("response", exists=False)
        try:
            parsed = json.loads(body)
            error = parsed.get("error", {})
            details["provider_code"] = (error.get("code") if isinstance(error.get("code"), str) else error.get("status")) if isinstance(error, dict) else None
        except (ValueError, TypeError, AttributeError):
            details["provider_code"] = "unclassified"
        capture("provider_error", body, exists=True)
    else:
        capture("http_response", body, exists=True)
    trace.event("route", "provider_request", **details)


def inspect_trace(trace_id, root=None):
    """Read only this contract's technical vocabulary, including incomplete runs."""
    if not re.fullmatch(r"[0-9a-f]{32}", trace_id):
        raise ValueError("Expected a 32-character lowercase hexadecimal trace ID")
    root = root or project_root()
    path = destination(root) / trace_id
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Trace not found at the configured diagnostics destination")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != VERSION or manifest.get("trace_id") != trace_id:
        raise ValueError("Unsupported or inconsistent diagnostics contract")
    privacy = PrivacyBoundary(root)
    result = {"schema_version": VERSION, "trace_id": trace_id, "processes": [], "events": [], "artifacts": []}
    for file in sorted(path.iterdir()):
        if file.is_symlink() or not file.is_file() or file.stat().st_size > EVENT_LIMIT * 2:
            continue
        if re.fullmatch(r"process-[0-9a-f]{32}\.json", file.name):
            data = json.loads(file.read_text(encoding="utf-8"))
            if data.get("schema_version") != VERSION or data.get("trace_id") != trace_id:
                raise ValueError("Unsupported process contract")
            status = data.get("status")
            failure = data.get("failure") or {}
            result["processes"].append({"process_id": file.stem.removeprefix("process-"),
                "status": status if status in ("success", "failed", "interrupted", "incomplete") else "incomplete_or_running",
                "failed_phase": failure.get("phase") if failure.get("phase") in PHASES else None,
                "failure": privacy.details(failure.get("details", {})),
                "capture_enabled": data.get("capture_enabled") is True})
            for ref in data.get("diagnostic_artifacts", [])[:100]:
                if not isinstance(ref, dict):
                    continue
                result["artifacts"].append({"kind": ref.get("kind") if ref.get("kind") in ("request", "response", "http_response", "provider_error", "schema", "instructions") else "unknown",
                    "capture_status": ref.get("capture_status") if ref.get("capture_status") in CAPTURE_STATUSES else "unavailable",
                    "content_exists": ref.get("content_exists") if type(ref.get("content_exists")) is bool else None,
                    "path": ref.get("path") if isinstance(ref.get("path"), str) and re.fullmatch(r"artifacts/[0-9a-f]{32}-[0-9a-f]{32}\.json", ref["path"]) else None})
        elif re.fullmatch(r"events-[0-9a-f]{32}-\d+\.jsonl", file.name):
            for line in file.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    result.setdefault("incomplete_event_files", []).append(file.name)
                    break
                if item.get("event") not in EVENTS or item.get("phase") not in PHASES:
                    continue
                if item.get("schema_version") != VERSION or item.get("trace_id") != trace_id:
                    raise ValueError("Unsupported event contract")
                result["events"].append({"event": item["event"], "phase": item["phase"],
                    "sequence": item.get("sequence") if type(item.get("sequence")) is int and 0 <= item["sequence"] <= 10 ** 12 else None,
                    "timestamp": item.get("timestamp") if isinstance(item.get("timestamp"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00", item["timestamp"]) else None,
                    "step": item.get("step") if item.get("step") in ("operation", "extract", "requirements", "analyze", "adapt", "review", "cover", "analyze-qualitative", "review-qualitative", "provider-check", "provider-discovery") else None,
                    "status": item.get("status") if item.get("status") in ("ok", "error", "running", "interrupted") else "error",
                    "details": privacy.details(item.get("details", {})),
                    **{key: item.get(key) if isinstance(item.get(key), str) and re.fullmatch(r"[0-9a-f]{16}|[0-9a-f]{32}", item[key]) else None
                       for key in ("trace_id", "span_id", "parent_span_id", "workflow_id", "process_id", "step_id", "attempt_id")}})
    return result


def export_trace(trace_id, output):
    """Export a re-sanitized technical bundle, never blindly zip local files."""
    import zipfile
    summary = inspect_trace(trace_id)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", _json(summary) + "\n")
            archive.writestr("README.txt", "Vita diagnostics v1 technical export. Artifact bodies are excluded; capture statuses and event correlation are in diagnostics.json. No raw prompts, candidate text or hidden reasoning are exported.\n")
    return summary
