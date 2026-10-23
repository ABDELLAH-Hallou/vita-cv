"""Bounded format recovery with authoritative host validation and private traces."""

import hashlib
import inspect
import json
import uuid
from pathlib import Path

from vita.helpers.provider_errors import ProviderError, UnsupportedSchema
from vita.helpers.structured import json_text, parse_json, validate, write_artifact

MAX_ATTEMPTS = 3  # Includes a rejected native-schema request, if any.


class StructuredOutputError(RuntimeError):
    def __init__(self, code: str, action: str, path: Path):
        super().__init__(f"{code}: {action} Details: {path}")
        self.code = code
        self.path = path


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


def run_structured(*, step: str, generate, system: str, prompt: str, route: dict,
                   schema: dict, finalize, save, session: dict | None = None) -> dict:
    """Save only validated values. All retries keep the original evidence/context.

    Trace files contain hashes and categories, not CVs, model prose, API bodies,
    or credentials. The immutable run ID distinguishes reruns from format retries.
    """
    run_id = uuid.uuid4().hex
    path = Path(".vita/results/attempts") / f"{step}-{run_id}.json"
    latest = Path(".vita/results") / f"{step}.outcome.json"
    record = {"schema_version": 1, "run_id": run_id, "step": step, "status": "running",
              "max_attempts": MAX_ATTEMPTS, "attempts": [], "error": None,
              "input_sha256": digest(system + "\n" + prompt)}
    session = session if session is not None else {}
    native = accepts_keyword(generate, "response_schema")
    supports_session = accepts_keyword(generate, "session")
    original_prompt = prompt + "\n\nRequired JSON output schema:\n" + json_text(schema)
    repair = ""

    def persist():
        write_artifact(path, json_text(record))
        write_artifact(latest, json_text(record))

    def fail(code, action):
        record.update(status="failed", error={"code": code, "action": action})
        persist()
        raise StructuredOutputError(code, action, path)

    persist()
    for number in range(1, MAX_ATTEMPTS + 1):
        kwargs = dict(route)
        session["mode"] = "schema_requested" if native else "validated_prompt"
        if native:
            kwargs["response_schema"] = schema
        if supports_session:
            kwargs["session"] = session
        attempt = {"number": number, "category": "started", "mode": session["mode"],
                   "route": {"provider": route.get("provider"), "model": route.get("model"),
                             "reasoning_effort": None}}
        record["attempts"].append(attempt)
        persist()
        try:
            session["request"] = {"attempt": number, "prompt_sha256": digest(original_prompt + repair)}
            response = generate(system, original_prompt + repair, **kwargs)
        except UnsupportedSchema:
            attempt.update(category="unsupported_schema", mode=session["mode"])
            attempt["route"] = dict(session.get("route", attempt["route"]))
            if not native:
                fail("provider_error", "The provider rejected output formatting even in prompt mode. "
                     "Check endpoint support and rerun this step.")
            native = False
            repair = "\n\nNative schema output is unavailable. Return the same required JSON object as text."
            persist()
            continue
        except Exception as exc:
            attempt.update(category=exc.code if isinstance(exc, ProviderError) else "provider_error",
                           mode=session["mode"])
            attempt["route"] = dict(session.get("route", attempt["route"]))
            if isinstance(exc, ProviderError) and exc.status is not None:
                attempt["http_status"] = exc.status
            fail("provider_error", "Check provider credentials, model access, CLI installation, and endpoint support; "
                 "then rerun this step. Provider failures are not retried as format errors.")
        attempt.update(mode=session["mode"], route=dict(session.get("route", attempt["route"])))
        if isinstance(response, str):
            attempt.update(response_sha256=digest(response), response_chars=len(response))
        try:
            if not isinstance(response, str) or not response.strip():
                raise ValueError("Empty response")
            data = parse_json(response)
        except (ValueError, RecursionError) as exc:
            attempt["category"] = "invalid_json"
            if isinstance(exc, json.JSONDecodeError):
                attempt["location"] = {"line": exc.lineno, "column": exc.colno, "offset": exc.pos}
        else:
            try:
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
            f"\n\nFORMAT RETRY {number + 1}/{MAX_ATTEMPTS}: The previous response was rejected "
            f"({attempt['category']}). Return a fresh, complete JSON object matching the schema. "
            + (f"Host validation: {attempt['detail']}. " if "detail" in attempt else "")
            + "Check quoting, commas, required fields, types, ranges, job IDs, and locked criteria. "
            "Use only the original supplied CV/JD evidence. Do not invent candidate facts or "
            "requirements to satisfy validation. Do not include commentary or change the task."
        )
    fail("structured_output_invalid", f"No valid structured output after {MAX_ATTEMPTS} attempts. "
         "Check the schema and supplied job criteria, update the provider/CLI if needed, and rerun this step. "
         "Existing assessments and CV sources were not replaced by an invalid response.")
