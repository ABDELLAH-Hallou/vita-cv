"""Run one real CLI invocation with transport observation and explicit fixture isolation."""

import hashlib
import io
import json
import math
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from vita.__main__ import main
from vita.helpers import factual_changes, llm, requirements
from vita.helpers.diagnostics import storage_lock
from vita.helpers.provider_errors import ProviderError


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class DispatchBlocked(ProviderError):
    def __init__(self, reason):
        super().__init__(code="configuration")
        self.reason = reason


def reserve(authorization, ledger):
    """The runner is serial; reserve before dispatch, including failed requests."""
    auth = json.loads(Path(authorization).read_text(encoding="utf-8"))
    if auth.get("acknowledge_api_billing") is not True or type(auth.get("max_requests")) is not int or not 1 <= auth["max_requests"] <= 10000:
        raise DispatchBlocked("invalid_authorization")
    if datetime.fromisoformat(auth["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise DispatchBlocked("authorization_expired")
    path = Path(ledger)
    with storage_lock(path.parent):
        count = json.loads(path.read_text(encoding="utf-8"))["requests"] if path.exists() else 0
        if type(count) is not int or count < 0 or count >= auth["max_requests"]:
            raise DispatchBlocked("request_limit_reached_or_invalid_ledger")
        temporary = path.with_suffix(".tmp")
        dump(temporary, {"requests": count + 1})
        os.replace(temporary, path)


def usage_metadata(result):
    """Allowlist numeric usage only; these are provider reports, not audited billing."""
    raw = result.get("usage", result.get("usageMetadata"))
    allowed = {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens",
               "promptTokenCount", "candidatesTokenCount", "totalTokenCount", "thoughtsTokenCount",
               "cachedContentTokenCount", "cache_read_input_tokens", "cache_creation_input_tokens"}
    allowed.update({"cached_tokens", "reasoning_tokens", "audio_tokens", "accepted_prediction_tokens",
                    "rejected_prediction_tokens", "cost", "upstream_inference_cost"})

    def numbers(values, depth=0):
        if not isinstance(values, dict) or depth > 3:
            return {}
        result = {k: v for k, v in values.items()
                  if k in allowed and (type(v) is int or type(v) is float and math.isfinite(v)) and v >= 0}
        for key in ("prompt_tokens_details", "completion_tokens_details", "cost_details"):
            details = numbers(values.get(key), depth + 1)
            if details:
                result[key] = details
        return result

    usage = numbers(raw)
    # Accessible model/snapshot ID is independent of the requested model ID.
    from vita.helpers.provider_errors import safe_identifier
    return {"usage": usage or None, "usage_status": "reported" if usage else "unknown",
            "reported_model": safe_identifier(result.get("modelVersion", result.get("model"))),
            "billing": "provider_reported_cost_not_invoice" if "cost" in usage else "unknown"}


class Response(io.BytesIO):
    status = 200
    headers = {"x-request-id": "synthetic-request"}


def execute(spec):
    fixture = spec["mode"] == "fixture"
    case = spec["case"]
    observed = []
    approvals = []
    dispatch_blocks = []
    original_urlopen = urllib.request.urlopen
    original_run = subprocess.run
    stage = factual_changes.stage
    faults = list(case.get("faults", [])) if spec.get("inject_faults") else []

    def save():
        dump(spec["telemetry"], {"requests": observed, "synthetic_approvals": approvals,
                                 "dispatch_blocks": dispatch_blocks})

    def start(kind, prompt, *, temperature=None, reasoning=None):
        if not fixture:
            try:
                reserve(spec["authorization"], spec["ledger"])
            except DispatchBlocked as exc:
                dispatch_blocks.append({"reason": exc.reason, "transport": kind})
                save()
                raise
        row = {"number": len(observed) + 1, "transport": kind, "provider": case["provider"],
               "started_at": datetime.now(timezone.utc).isoformat(),
               "requested_model": case["model"], "reasoning_effort": reasoning,
               "temperature": temperature, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
               "status": "started", "usage": None, "usage_status": "unknown", "billing": "unknown",
               "reported_model": None}
        observed.append(row)
        save()
        return row, time.monotonic()

    def finish(row, started):
        row["duration_seconds"] = round(time.monotonic() - started, 6)
        save()

    def fault():
        return faults.pop(0) if faults else None

    def http(request, **kwargs):
        data = json.loads(request.data.decode())
        if "contents" in data:
            prompt = data["system_instruction"]["parts"][0]["text"] + "\n" + data["contents"][0]["parts"][0]["text"]
        else:
            prompt = str(data.get("system", "")) + "\n" + "\n".join(m["content"] for m in data["messages"])
        reasoning = data.get("reasoning_effort", data.get("reasoning", {}).get("effort"))
        row, started = start("http", prompt, temperature=data.get("temperature", data.get("generationConfig", {}).get("temperature")), reasoning=reasoning)
        row["wire_model"] = data.get("model") or request.full_url.split("/models/", 1)[-1].split(":generateContent", 1)[0]
        schema = data.get("response_format", {}).get("json_schema", {}).get("schema", data.get("generationConfig", {}).get("responseJsonSchema"))
        row["schema_sha256"] = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest() if schema else None
        try:
            if fixture:
                from scripts.benchmark.fixture_transport import answer, envelope
                failure = fault()
                if failure and failure != "malformed":
                    code = 404 if failure == "invalid_model" else int(failure)
                    body = b'{"error":{"code":"model_not_found"}}' if code == 404 else b'{"error":{"message":"fixture failure"}}'
                    raise urllib.error.HTTPError("https://fixture.invalid", code, "fixture", {"Retry-After": "0"}, io.BytesIO(body))
                result = envelope(case["provider"], case["model"], "{malformed" if failure else answer(prompt))
                raw = json.dumps(result).encode()
                response = Response(raw)
            else:
                with original_urlopen(request, **kwargs) as original:
                    raw = original.read()
                    response = Response(raw)
                    response.status, response.headers = original.status, original.headers
                try:
                    result = json.loads(raw)
                except ValueError:
                    result = {}
            if isinstance(result, dict):
                row.update(usage_metadata(result))
            row.update(status="response", http_status=response.status)
            return response
        except urllib.error.HTTPError as exc:
            row.update(status="http_error", http_status=exc.code)
            raise
        except Exception as exc:
            row.update(status="transport_error", exception_type=type(exc).__name__)
            raise
        finally:
            finish(row, started)

    def process(cmd, **kwargs):
        if Path(str(cmd[0])).name.lower() in ("codex", "codex.exe", "fixture-codex") or "--output-last-message" in cmd:
            row, started = start("codex_cli", kwargs.get("input", ""), reasoning=case.get("reasoning_effort"))
            row["wire_model"] = cmd[cmd.index("--model") + 1] if "--model" in cmd else None
            row["schema_sha256"] = hashlib.sha256(Path(cmd[cmd.index("--output-schema") + 1]).read_bytes()).hexdigest() if "--output-schema" in cmd else None
            try:
                if fixture:
                    from scripts.benchmark.fixture_transport import answer
                    failure = fault()
                    if failure and failure != "malformed":
                        error = "model_not_found" if failure == "invalid_model" else "HTTP status " + failure
                        result = subprocess.CompletedProcess(cmd, 1, "", error)
                    else:
                        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
                            "{malformed" if failure else answer(kwargs["input"]), encoding="utf-8")
                        result = subprocess.CompletedProcess(cmd, 0, "", "")
                else:
                    kwargs["timeout"] = spec["timeout"]
                    result = original_run(cmd, **kwargs)
                row.update(status="response" if result.returncode == 0 else "cli_error", exit_status=result.returncode)
                return result
            finally:
                finish(row, started)
        if cmd[0] == "latexmk" and fixture and not spec["real_pdf"]:
            output = next(s.split("=", 1)[1] for s in cmd if s.startswith("-outdir="))
            name = next(s.split("=", 1)[1] for s in cmd if s.startswith("-jobname="))
            Path(output, name + ".pdf").write_bytes(b"%PDF-1.4\n% synthetic handoff marker, not a rendered document\n")
            return subprocess.CompletedProcess(cmd, 0, "fixture compiler handoff", "")
        if cmd[0] == "latexmk" and spec["real_pdf"]:
            return original_run(cmd, **kwargs)
        if fixture:
            raise AssertionError("Unmocked subprocess in fixture: " + str(cmd[0]))
        return original_run(cmd, **kwargs)

    def approved(context, document):
        if stage(context, document):
            return True
        report = factual_changes.load(context["step"])
        approvals.append({"step": context["step"], "revision": report["revision"], "kind": "synthetic_fixture_only"})
        return factual_changes.decide(context["step"], report["revision"], True)["application_status"] == "applied"

    def no_network(*args, **kwargs):
        raise AssertionError("Fixture transport attempted network access")

    # The seed is a source-reviewed synthetic contract, shared across all judges.
    if spec.get("seed_controls"):
        raw = Path("job.md").read_text(encoding="utf-8")
        proposal = json.loads(Path("requirements.json").read_text(encoding="utf-8"))
        doc = requirements.save_revision(requirements.compile_revision(proposal, raw))
        requirements.approve_revision(doc["revision"], raw)
    with patch.object(urllib.request, "urlopen", http), patch.object(subprocess, "run", process):
        if fixture:
            with patch.object(socket.socket, "connect", no_network), patch.object(socket.socket, "connect_ex", no_network), patch.object(socket, "create_connection", no_network), patch.object(socket, "getaddrinfo", no_network), patch.object(llm, "_find_codex_cli", lambda: "fixture-codex"), patch("vita.commands.ai_step.stage", approved):
                main()
        else:
            main()


if __name__ == "__main__":
    specification = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    sys.argv = ["vita", *specification["argv"]]
    execute(specification)
