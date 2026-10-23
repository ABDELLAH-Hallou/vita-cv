"""Bounded format recovery with authoritative host validation and private traces."""

import hashlib
import inspect
import json
import time
import uuid
from pathlib import Path

from vita.helpers.provider_errors import (
    ProviderError,
    RetryPolicy,
    UnsupportedSchema,
    normalize_error,
    safe_route,
    safe_step,
)
from vita.helpers.structured import json_text, parse_json, validate, write_artifact

MAX_ATTEMPTS = 3  # Default shared budget: transport, schema negotiation and format.


class StructuredOutputError(RuntimeError):
    def __init__(self, code: str, action: str, path: Path, error: dict | None = None):
        super().__init__(f"{code}: {action} Details: {path}")
        self.code = code
        self.path = path
        self.error = error


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def accepts_keyword(function, keyword: str) -> bool:
    """Negotiate old adapters before calling; never retry an internal TypeError."""
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
    parameter = parameters.get(keyword)
    return (parameter is not None and parameter.kind != parameter.POSITIONAL_ONLY) or any(
        item.kind == item.VAR_KEYWORD for item in parameters.values()
    )


def run_text(*, step: str, generate, system: str, prompt: str, route: dict,
             session: dict | None = None) -> str:
    """Text generation uses the same transient-error budget and public outcomes."""
    return run_structured(step=step, generate=generate, system=system, prompt=prompt,
                          route=route, schema=None, finalize=lambda value: value,
                          save=lambda value: None, session=session)


def record_provider_failure(step: str, exc: ProviderError, route: dict) -> dict:
    """A routing failure before generation has zero attempts, not a lost outcome."""
    run_id = uuid.uuid4().hex
    step = safe_step(step)
    error = exc.contract(step=step, route=safe_route(route), attempts=0, max_attempts=0)
    record = {"schema_version": 1, "run_id": run_id, "step": step, "status": "failed",
              "max_attempts": 0, "attempt_count": 0, "attempts": [], "error": error}
    write_artifact(Path(".vita/results/attempts") / f"{step}-{run_id}.json", json_text(record))
    write_artifact(Path(".vita/results") / f"{step}.outcome.json", json_text(record))
    return record


def run_structured(*, step: str, generate, system: str, prompt: str, route: dict,
                   schema: dict | None, finalize, save, session: dict | None = None):
    """Save only validated values. All retries keep the original evidence/context.

    Trace files contain hashes and categories, not CVs, model prose, API bodies,
    or credentials. The immutable run ID distinguishes reruns from format retries.
    """
    step = safe_step(step)
    run_id = uuid.uuid4().hex
    route = dict(route)
    path = Path(".vita/results/attempts") / f"{step}-{run_id}.json"
    latest = Path(".vita/results") / f"{step}.outcome.json"
    record = {"schema_version": 1, "run_id": run_id, "step": step, "status": "running",
              "max_attempts": MAX_ATTEMPTS, "attempts": [], "error": None,
              "input_sha256": digest(system + "\n" + prompt)}
    session = session if session is not None else {}
    native = schema is not None and accepts_keyword(generate, "response_schema")
    supports_session = accepts_keyword(generate, "session")
    original_prompt = (prompt + "\n\nRequired JSON output schema:\n" + json_text(schema)
                       if schema is not None else prompt)
    repair = ""

    def persist():
        record["attempt_count"] = len(record["attempts"])
        write_artifact(path, json_text(record))
        write_artifact(latest, json_text(record))

    def fail(code, action, error=None):
        record.update(status="failed", error=error or {"code": code, "action": action})
        persist()
        raise StructuredOutputError(code, action, path, record["error"])

    persist()
    try:
        policy = RetryPolicy.load()
    except Exception as exc:
        error = normalize_error(exc).contract(step=step, route=safe_route(route, session),
                                               attempts=0, max_attempts=0)
        fail("provider_error", error["action"], error)
    record["max_attempts"] = policy.max_attempts
    for number in range(1, policy.max_attempts + 1):
        kwargs = dict(route)
        session["mode"] = "schema_requested" if native else "validated_prompt"
        if native:
            kwargs["response_schema"] = schema
        if supports_session:
            kwargs["session"] = session
        attempt = {"number": number, "category": "started", "mode": session["mode"],
                   "route": safe_route(route, session)}
        record["attempts"].append(attempt)
        persist()
        try:
            session["request"] = {"attempt": number, "prompt_sha256": digest(original_prompt + repair)}
            response = generate(system, original_prompt + repair, **kwargs)
        except UnsupportedSchema as exc:
            attempt.update(category="unsupported_schema", mode=session["mode"])
            attempt["route"] = safe_route(route, session)
            attempt["error"] = exc.contract(step=step, route=attempt["route"], attempts=number,
                                             max_attempts=policy.max_attempts, exhausted=number == policy.max_attempts)
            if not native or number == policy.max_attempts:
                fail("provider_error", str(exc), attempt["error"])
            native = False
            repair = "\n\nNative schema output is unavailable. Return the same required JSON object as text."
            persist()
            continue
        except Exception as exc:
            error = normalize_error(exc)
            attempt.update(category=error.code, mode=session["mode"], route=safe_route(route, session))
            attempt["error"] = error.contract(step=step, route=attempt["route"], attempts=number,
                                               max_attempts=policy.max_attempts, exhausted=number == policy.max_attempts)
            if error.status is not None:
                attempt["http_status"] = error.status
            if error.retryable and number < policy.max_attempts:
                delay = policy.delay(error, number)
                if delay is not None:
                    attempt["retry_delay_seconds"] = delay
                    persist()
                    time.sleep(delay)
                    # Keep any previous format-repair instruction unchanged.
                    continue
                attempt["error"]["retry_stopped"] = "retry_after_exceeds_delay_cap"
                attempt["error"]["action"] += " Retry-After exceeds the configured wait cap; rerun after that interval."
            fail("provider_error", attempt["error"]["action"], attempt["error"])
        attempt.update(mode=session["mode"], route=safe_route(route, session))
        if isinstance(response, str):
            attempt.update(response_sha256=digest(response), response_chars=len(response))
        if schema is None and (not isinstance(response, str) or not response.strip()):
            error = ProviderError(code="empty_response")
            attempt.update(category=error.code)
            contract = error.contract(step=step, route=attempt["route"], attempts=number,
                                      max_attempts=policy.max_attempts)
            fail("provider_error", str(error), contract)
        try:
            if not isinstance(response, str) or not response.strip():
                raise ValueError("Empty response")
            data = parse_json(response) if schema is not None else response
        except (ValueError, RecursionError) as exc:
            attempt["category"] = "invalid_json"
            if isinstance(exc, json.JSONDecodeError):
                attempt["location"] = {"line": exc.lineno, "column": exc.colno, "offset": exc.pos}
        else:
            try:
                if schema is not None:
                    validate(data, schema)
            except (ValueError, TypeError, RecursionError) as exc:
                attempt["category"] = "schema_error"
                # These host validator messages contain schema paths, never values.
                if type(exc) is ValueError:
                    attempt["detail"] = str(exc)
            else:
                try:
                    value = finalize(data)
                except (ValueError, TypeError, KeyError, RecursionError) as exc:
                    attempt["category"] = "validation_error"
                    if type(exc) is ValueError:
                        attempt["detail"] = str(exc)
                else:
                    attempt["category"] = "valid"
                    persist()
                    try:
                        save(value)
                    except (OSError, ValueError, TypeError):
                        fail("artifact_error", "Validated output could not be saved. Check output-directory access "
                             "and rerun this step; no additional model call was made.")
                    record.update(status="success", recovered=number > 1)
                    persist()
                    return value
        persist()
        repair = (
            f"\n\nFORMAT RETRY {number + 1}/{policy.max_attempts}: The previous response was rejected "
            f"({attempt['category']}). Return a fresh, complete JSON object matching the schema. "
            + (f"Host validation: {attempt['detail']}. " if "detail" in attempt else "")
            + "Check quoting, commas, required fields, types, ranges, job IDs, and locked criteria. "
            "Use only the original supplied CV/JD evidence. Do not invent candidate facts or "
            "requirements to satisfy validation. Do not include commentary or change the task."
        )
    fail("structured_output_invalid", f"No valid structured output after {policy.max_attempts} attempts. "
         "Check the schema and supplied job criteria, update the provider/CLI if needed, and rerun this step. "
         "Existing assessments and CV sources were not replaced by an invalid response.")
