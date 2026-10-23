"""Private developer journal. No provider/configuration imports or public export.

Candidate content is intentional in local mode. Credentials are removed before
any write; this is secret redaction, not anonymization of a candidate document.
The owner supplies bounded, locked storage and correlation context.
"""

import inspect
import json
import math
import re
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus

VERSION = 1
ARTIFACT_LIMIT = 2 * 1024 * 1024
REDACTED = "[CREDENTIAL_REDACTED]"
HIDDEN = "[PROVIDER_INTERNAL_REASONING_OMITTED]"


def sensitive(key):
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return (
        normalized
        in {
            "key",
            "authorization",
            "proxyauthorization",
            "cookie",
            "setcookie",
            "credential",
            "credentials",
        }
        or any(
            word in normalized
            for word in (
                "apikey",
                "accesstoken",
                "refreshtoken",
                "authtoken",
                "password",
                "secret",
                "clienttoken",
            )
        )
        or normalized.endswith("token")
    )


def redact_text(value, secrets):
    # Longest first avoids partial replacement of overlapping credentials.
    variants = {
        item
        for secret in secrets
        if secret
        for item in (secret, quote(secret, safe=""), quote_plus(secret), json.dumps(secret)[1:-1])
    }
    for secret in sorted(variants, key=len, reverse=True):
        value = value.replace(secret, REDACTED)
    value = re.sub(r"(?i)(Bearer\s+)[^\s\"'<>;,}]+", lambda m: m[1] + REDACTED, value)
    value = re.sub(
        r"(?i)([?&](?:key|api[_-]?key|access[_-]?token|token|secret)=)[^&#\s\"']*",
        lambda m: m[1] + REDACTED,
        value,
    )
    value = re.sub(r"(?i)(https?://)[^\s/@]+@", lambda m: m[1] + REDACTED + "@", value)
    value = re.sub(
        r"(?is)((?:api[_-]?key|(?:access|refresh|auth)[_-]?token|token|password|secret|authorization|cookie|set[_-]?cookie)[ \t]{0,32}[\"']?[ \t]{0,32}[:=][ \t]{0,32})([\"'])(.*?)(?:\2|$)",
        lambda m: m[1] + m[2] + REDACTED + m[2],
        value,
    )
    value = re.sub(
        r"(?i)((?:api[_-]?key|(?:access|refresh|auth)[_-]?token|token|password|secret|authorization|cookie|set[_-]?cookie)[ \t]{0,32}[\"']?[ \t]{0,32}[:=][ \t]{0,32})[^\s\"'&,;]+",
        lambda m: m[1] + REDACTED,
        value,
    )
    value = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{12,})", REDACTED, value)
    value = re.sub(
        r"(?im)^([ \t]*(?:Authorization|Proxy-Authorization|Cookie|Set-Cookie)[ \t]*:[ \t]*).*$",
        lambda m: m[1] + REDACTED,
        value,
    )
    return value


def redact(value, secrets, depth=0):
    if depth > 40:
        return "[DEPTH_LIMIT]"
    if isinstance(value, (bytes, bytearray)):
        return redact_text(value.decode("utf-8", errors="replace"), secrets)
    if isinstance(value, dict):
        if value.get("thought") is True:
            return {"thought": True, "text": HIDDEN}
        output = {}
        for key, item in value.items():
            label = redact_text(str(key), secrets)
            if sensitive(key):
                output[label] = REDACTED
            elif key in ("reasoning_content", "chain_of_thought") or (
                key == "reasoning" and isinstance(item, str)
            ):
                output[label] = HIDDEN
            else:
                output[label] = redact(item, secrets, depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        output, hide_next = [], False
        for item in value:
            inline_secret = (
                isinstance(item, str)
                and item.startswith("--")
                and "=" in item
                and sensitive(item.split("=", 1)[0])
            )
            output.append(
                REDACTED
                if hide_next
                else item.split("=", 1)[0] + "=" + REDACTED
                if inline_secret
                else redact(item, secrets, depth + 1)
            )
            hide_next = (
                isinstance(item, str)
                and item.startswith("--")
                and sensitive(item.split("=", 1)[0])
                and "=" not in item
            )
        return output
    if isinstance(value, str):
        return redact_text(value, secrets)
    if value is None or type(value) in (bool, int, float):
        return str(value) if type(value) is float and not math.isfinite(value) else value
    # Never serialize arbitrary object reprs (sessions/adapters can hold secrets).
    return f"<{type(value).__module__}.{type(value).__qualname__}>"


def component(function=None):
    if function is not None:
        return {
            "module": function.__module__,
            "function": function.__qualname__,
            "file": function.__code__.co_filename,
            "line": function.__code__.co_firstlineno,
        }
    frame = inspect.currentframe()
    frame = frame.f_back if frame else None
    while frame and frame.f_globals.get("__name__") in (__name__, "vita.helpers.diagnostics"):
        frame = frame.f_back
    return (
        {
            "module": frame.f_globals.get("__name__"),
            "function": frame.f_code.co_name,
            "file": frame.f_code.co_filename,
            "line": frame.f_lineno,
        }
        if frame
        else {}
    )


class Journal:
    def __init__(self, owner, package_version):
        self.owner = owner
        self.prefix = f"journal/{owner.process_id}"
        self.refs = []
        self.number = 0
        self.configuration = []
        self.artifact(
            "runtime",
            {
                "journal_version": VERSION,
                "mode": "local",
                "product_version": package_version,
                "python_version": sys.version,
                "python_executable": sys.executable,
                "platform": sys.platform,
                "working_directory": str(Path.cwd()),
                "project_root": str(owner.root),
                "package_directory": str(Path(__file__).parent.parent.resolve()),
                "argv": sys.argv,
                "content_policy": "candidate-content-local-credentials-redacted",
                "artifact_limit_bytes": ARTIFACT_LIMIT,
            },
            scoped=False,
        )
        self.record(
            "journal.started",
            component=component(),
            message="Local prompts, outputs, configuration and errors are retained; credentials are redacted.",
        )

    def scope(self):
        context = self.owner.local_context()
        return f"steps/{context['step_id'] or 'workflow'}/attempts/{context['attempt_id'] or 'preflight'}"

    def artifact(self, kind, content, *, scoped=True, text=False):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,100}", kind):
            raise ValueError("Invalid journal artifact name")
        if text and isinstance(content, str):
            # Preserve original formatting when JSON redaction does not change it.
            try:

                def unique(pairs):
                    result = {}
                    for key, item in pairs:
                        if key in result:
                            raise ValueError("Duplicate JSON field")
                        result[key] = item
                    return result

                def invalid_constant(value):
                    raise ValueError("Non-finite JSON")

                parsed = json.loads(
                    content, object_pairs_hook=unique, parse_constant=invalid_constant
                )
                cleaned = redact(parsed, self.owner.privacy.secrets)
                data = (
                    redact_text(content, self.owner.privacy.secrets)
                    if parsed == cleaned
                    else json.dumps(cleaned, ensure_ascii=False, indent=2)
                )
            except (ValueError, RecursionError):
                data = redact_text(content, self.owner.privacy.secrets)
        else:
            data = json.dumps(
                redact(content, self.owner.privacy.secrets),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        encoded = data.encode("utf-8", errors="replace")
        original_bytes = len(encoded)
        truncated = original_bytes > ARTIFACT_LIMIT
        if truncated:
            data = encoded[:ARTIFACT_LIMIT].decode("utf-8", errors="ignore")
            if not text:
                data = json.dumps(
                    {
                        "capture_status": "truncated",
                        "original_bytes": original_bytes,
                        "preview": data[: ARTIFACT_LIMIT // 2],
                    },
                    ensure_ascii=False,
                )
            else:
                data += f"\n[TRUNCATED: original {original_bytes} redacted bytes; limit {ARTIFACT_LIMIT}]\n"
            encoded = data.encode("utf-8")
        name = f"{self.scope()}/{kind}" if scoped else kind
        relative = f"{self.prefix}/{name}.{'txt' if text else 'json'}"
        if self.owner.local_write(relative, encoded):
            context = self.owner.local_context()
            ref = {
                "kind": kind,
                "path": relative,
                "step_id": context["step_id"],
                "attempt_id": context["attempt_id"],
                "bytes": len(encoded),
                "original_redacted_bytes": original_bytes,
                "truncated": truncated,
            }
            self.refs = [item for item in self.refs if item["path"] != relative] + [ref]
            self.owner.local_write(
                f"{self.prefix}/index.json",
                json.dumps(
                    {"journal_version": VERSION, "artifacts": self.refs}, ensure_ascii=True
                ).encode(),
            )
            self.record(
                "artifact.saved",
                component=component(),
                kind=kind,
                path=relative,
                bytes=len(encoded),
                truncated=truncated,
                original_redacted_bytes=original_bytes,
            )
            return relative
        return None

    def record(self, event, *, level="DEBUG", component=None, **fields):
        self.number += 1
        row = {
            "journal_version": VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sequence": self.number,
            "level": level,
            "event": event,
            **self.owner.local_context(),
            "component": component or {},
            "details": redact(fields, self.owner.privacy.secrets),
        }
        row["component"] = redact(row["component"], self.owner.privacy.secrets)
        encoded = (json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n").encode()
        self.owner.local_write(f"{self.prefix}/events.jsonl", encoded, append=True)
        source = row["component"]
        location = (
            f"{source.get('module', '')}.{source.get('function', '')}:{source.get('line', '')}"
        )
        line = (
            f"{row['timestamp']} {level:5} step={row['step'] or 'operation'} attempt={row['attempt_id'] or '-'} {location} {event} "
            + json.dumps(row["details"], ensure_ascii=True)
            + "\n"
        )
        self.owner.local_write(f"{self.prefix}/execution.log", line.encode(), append=True)
        if event.startswith("configuration."):
            self.configuration.append(row)
            self.artifact("configuration", {"events": self.configuration[-500:]}, scoped=False)

    def exception(self, phase, exc, **details):
        text = "".join(
            traceback.TracebackException.from_exception(exc, capture_locals=False).format(
                chain=True
            )
        )
        reason = getattr(exc, "reason", None)
        if reason is not None:
            text += f"\nUnderlying reason ({type(reason).__name__}): {reason}\n"
        attributes = {
            key: getattr(exc, key)
            for key in ("cmd", "timeout", "stdout", "stderr", "returncode", "errno", "filename")
            if getattr(exc, key, None) is not None
        }
        if attributes:
            text += (
                "\nException attributes:\n"
                + json.dumps(
                    redact(attributes, self.owner.privacy.secrets), ensure_ascii=False, indent=2
                )
                + "\n"
            )
        path = self.artifact("exception-" + uuid.uuid4().hex, text, text=True)
        self.record(
            "exception",
            level="ERROR",
            component=component(),
            phase=phase,
            exception_type=type(exc).__name__,
            message=str(exc),
            traceback=path,
            **details,
        )

    def capture(self, kind, content, exists):
        if kind == "generated-prompt":
            self.record(
                "prompt.generated",
                component=component(),
                execution_mode="external_instructions_only",
                provider_called=False,
                message="Generated prompt only; no external provider response has been observed.",
            )
        if kind == "request" and content is not None:
            for label, value in content:
                self.artifact(
                    "system-prompt" if label == "system" else "user-prompt", value, text=True
                )
        elif content is not None:
            self.artifact(
                {
                    "response": "model-output",
                    "http_response": "http-response-body",
                    "provider_error": "provider-error-body",
                }.get(kind, kind),
                content,
                text=isinstance(content, str),
            )
        elif exists is not None:
            self.record(
                "capture.unavailable", component=component(), kind=kind, content_exists=exists
            )
