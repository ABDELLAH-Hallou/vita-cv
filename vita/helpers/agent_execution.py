"""Opt-in Codex restrictions and content-free event observations, never a raw API.

No global config mutation, policy bypass, model substitution or internal retries.
Capability checks are local commands, not generation requests.
"""

import hashlib
import json
import math
import os
import re
import subprocess
import time

from vita.helpers import diagnostics as diagnostic
from vita.helpers.provider_errors import ProviderError

VERSION = "agent-execution/1"
FEATURES = ("shell_tool", "multi_agent", "plugins")
LIMITATIONS = ["Other built-in tools may remain available; this is not a tool-free raw model API.",
               "CLI internal model requests/retries and startup versus inference time are not fully observable.",
               "User/project instructions, hooks and managed security policies remain in force."]
GENERATION = """GENERATION ONLY: All task inputs are supplied below. Produce the requested final
answer directly from these inputs. Do not explore files, search the web, delegate,
run commands, plan host operations, or save files. VITA captures sources, validates
the answer, applies factual approval gates and saves results. Treat file-reading
and saving instructions inside task skills as host responsibilities, not tools
to execute. Preserve the selected task, source boundaries and output contract.
Never treat a job description or prior model commentary as candidate evidence.
Never omit CV history or invent facts to fit a context/output limit; report it.
"""


def configuration(provider, config, env):
    requested = env.get("VITA_AGENT_EXECUTION", config.get("execution_mode", "baseline"))
    if requested not in ("baseline", "restricted"):
        raise ValueError("VITA_AGENT_EXECUTION/execution_mode must be baseline or restricted")
    origin = ("process" if "VITA_AGENT_EXECUTION" in os.environ else "project_env") if "VITA_AGENT_EXECUTION" in env else (
        "extensions" if "execution_mode" in config else "default")
    if provider != "codex" and config.get("execution_mode") == "restricted":
        raise ValueError("restricted execution is supported only for the Codex CLI adapter")
    maximum = config.get("max_input_bytes", 2_000_000)
    timeout = config.get("agent_timeout_seconds", 600)
    telemetry = config.get("agent_telemetry", False)
    if type(maximum) is not int or not 1 <= maximum <= 20_000_000:
        raise ValueError("max_input_bytes must be 1..20000000; inputs are never shortened")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 3600:
        raise ValueError("agent_timeout_seconds must be 1..3600")
    if type(telemetry) is not bool:
        raise ValueError("agent_telemetry must be boolean")
    return {"contract_version": VERSION, "requested": requested, "origin": origin,
            "mode": requested if provider == "codex" else "direct_api",
            "telemetry": telemetry or provider == "codex" and requested == "restricted",
            "guard_inputs": requested == "restricted" or "max_input_bytes" in config,
            "max_input_bytes": maximum, "timeout_seconds": timeout,
            "limitations": LIMITATIONS if provider == "codex" else []}


def local(codex, args):
    try:
        result = subprocess.run([codex, *args], capture_output=True, text=True, encoding="utf-8", timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            # MCP discovery output may contain private transport credentials.
            exc.output = None
            exc.stderr = None
        raise ProviderError(code="configuration") from None
    if result.returncode != 0:
        raise ProviderError(code="configuration")
    return result.stdout


def preflight(codex):
    started = time.monotonic()
    version = local(codex, ["--version"]).strip()
    if not re.fullmatch(r"codex-cli [0-9A-Za-z.+_-]{1,80}", version):
        raise ProviderError(code="configuration")
    help_text = local(codex, ["exec", "--help"])
    if any(flag not in help_text for flag in ("--ephemeral", "--json", "--config", "--output-last-message")):
        raise ProviderError(code="configuration")
    features = local(codex, ["features", "list"])
    if any(not re.search(r"(?m)^" + key + r"\s+", features) for key in FEATURES):
        raise ProviderError(code="configuration")
    servers = json.loads(local(codex, ["mcp", "list", "--json"]))
    flags = []
    for key in FEATURES:
        flags.extend(["--config", f"features.{key}=false"])
    flags += ["--config", 'web_search="disabled"', "--config", 'history.persistence="none"',
              "--config", "hide_agent_reasoning=true"]
    if not isinstance(servers, list):
        raise ProviderError(code="configuration")
    for server in servers:
        name, transport = server.get("name"), server.get("transport", {})
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name):
            raise ProviderError(code="configuration")
        # Bootstrap parsing needs a complete transport. Preserve its type using
        # inert values, never copy URLs, headers or commands/secrets into argv.
        if "url" in transport:
            neutral = 'url="https://disabled.invalid"'
        elif "command" in transport:
            neutral = 'command="vita-disabled-mcp"'
        else:
            raise ProviderError(code="configuration")
        flags += ["--config", f"mcp_servers.{name}={{{neutral},enabled=false}}"]
    checked = json.loads(local(codex, [*flags, "mcp", "list", "--json"]))
    effective_features = local(codex, [*flags, "features", "list"])
    if (not isinstance(checked, list) or any(s.get("enabled") is not False for s in checked)
            or {s.get("name") for s in checked} != {s.get("name") for s in servers}
            or any(not re.search(r"(?m)^" + key + r"\s+[^\n]*\bfalse\s*$", effective_features) for key in FEATURES)):
        raise ProviderError(code="configuration")
    return {"flags": flags, "cli_version": version, "mcp_servers_disabled": len(checked),
            "restrictions": ["shell", "web_search", "subagents", "plugins", "configured_mcp"],
            "capability_processes": 6, "generation_access": "not_tested",
            "capability_check_seconds": time.monotonic() - started}


def events(content):
    """Count allowlisted event fields; never retain reasoning, commands or payloads."""
    result = {"event_stream": "unavailable", "turns_completed": 0, "model_calls": None,
              "tool_calls": None, "denied_tool_calls": None, "usage": None, "cost": None,
              "terminal": None, "unknown_items": 0, "error_category": None,
              "observed_tool_types": [], "tool_count_scope": "reported_item_events_only"}
    counts, seen, usage, valid, denials, tool_types, unidentified = {}, set(), {}, False, set(), set(), False
    turn_serial = 0
    mapping = {"command_execution": "shell", "mcp_tool_call": "mcp", "web_search": "web_search",
               "collab_tool_call": "subagent", "collaboration_tool_call": "subagent",
               "file_change": "file_change", "todo_list": "planning", "image_view": "image_view"}
    for line in content.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "turn.started":
            turn_serial += 1
        valid = valid or kind in ("thread.started", "turn.started", "turn.completed", "turn.failed")
        if kind in ("item.started", "item.completed"):
            item = event.get("item", {})
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type in mapping:
                tool_types.add(mapping[item_type])
                if not isinstance(item.get("id"), str) or not item["id"]:
                    unidentified = True
                    continue
                identity = (turn_serial, item_type, item.get("id"))
                if identity not in seen:
                    seen.add(identity)
                    key = mapping[item_type]
                    counts[key] = counts.get(key, 0) + 1
                if item.get("status") == "denied":
                    denials.add(identity)
            elif item_type not in ("agent_message", "reasoning"):
                result["unknown_items"] += 1
        if kind == "turn.completed":
            result["turns_completed"] += 1
            result["terminal"] = "completed"
            values = event.get("usage", {})
            if isinstance(values, dict):
                for key in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens"):
                    value = values.get(key)
                    if type(value) is int and value >= 0:
                        usage[key] = usage.get(key, 0) + value
        elif kind in ("turn.failed", "error"):
            result["terminal"] = "failed"
            # Classify in memory. No error prose or hidden reasoning is retained.
            text = json.dumps(event.get("error", event.get("message", ""))).lower()
            result["error_category"] = ("refusal" if "refus" in text else "input_context" if re.search(r"context|input.*too long", text)
                                         else "output_length" if re.search(r"truncat|max_tokens|output.*limit", text) else None)
    if valid:
        result.update(event_stream="observed", tool_calls=None if unidentified else counts, usage=usage or None,
                      observed_tool_types=sorted(tool_types))
        # Absence of an explicit denial event does not establish zero denials.
        result["denied_tool_calls"] = len(denials) if denials and not unidentified else None
    return result


def invoke(codex, cmd, prompt, options, session):
    restricted = options["mode"] == "restricted"
    effective = {**options, "cli_version": None, "restrictions": [], "generation_dispatch": "not_dispatched",
                 "restriction_status": "pending" if restricted else "not_requested"}
    session["execution"] = effective
    session.pop("agent_telemetry", None)
    diagnostic.journal("configuration.agent_requested", **effective)
    if options["guard_inputs"] and len(prompt.encode("utf-8")) > options["max_input_bytes"]:
        raise ProviderError(code="invalid_request", limit_kind="input_context")
    if restricted:
        cached = bool(session.get("agent_capabilities"))
        if not cached:
            try:
                session["agent_capabilities"] = preflight(codex)
            except (ProviderError, ValueError, TypeError, KeyError):
                effective["restriction_status"] = "unavailable"
                diagnostic.journal("agent.restriction_unavailable", reason="Local controls could not be verified; no generation dispatched.")
                print("Restricted Codex controls could not be verified. No generation was dispatched; update the CLI/configuration or explicitly select execution_mode=baseline.")
                raise ProviderError(code="configuration") from None
        capabilities = session["agent_capabilities"]
        effective.update({k: v for k, v in capabilities.items() if k != "flags"})
        effective["capability_cache_reused"] = cached
        if cached:
            effective.update(capability_processes=0, capability_check_seconds=0.0)
        effective["restriction_status"] = "verified_local_controls"
        cmd.extend(capabilities["flags"])
        cmd.append("--ephemeral")
        prompt = GENERATION + "\n" + prompt
    else:
        began = time.monotonic()
        version = local(codex, ["--version"]).strip()
        effective["cli_version"] = version if re.fullmatch(r"codex-cli [0-9A-Za-z.+_-]{1,80}", version) else None
        effective.update(capability_processes=1, capability_check_seconds=time.monotonic() - began)
        cmd.extend(["--config", "hide_agent_reasoning=true"])
    cmd.extend(["--json", "-"])
    effective["effective_prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if options["guard_inputs"] and len(prompt.encode("utf-8")) > options["max_input_bytes"]:
        raise ProviderError(code="invalid_request", limit_kind="input_context")
    diagnostic.journal("configuration.agent_execution", **effective)
    diagnostic.local_artifact("cli-request", {"argv": cmd, "stdin": prompt})
    started = time.monotonic()
    telemetry = {"event_stream": "unavailable", "model_calls": None, "tool_calls": None,
                 "denied_tool_calls": None, "usage": None, "cost": None}
    try:
        effective["generation_dispatch"] = "cli_invoked"
        result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                timeout=options["timeout_seconds"])
        telemetry.update(events(result.stdout))
        if telemetry.get("terminal") == "completed":
            effective["generation_dispatch"] = "turn_completed"
        telemetry["exit_status"] = result.returncode
        if restricted and set(telemetry.get("observed_tool_types", [])).intersection(("shell", "mcp", "web_search", "subagent")):
            effective["restriction_status"] = "contradicted_by_observed_activity"
            print("Codex events contradicted the requested restrictions. Output rejected; inspect execution diagnostics and update the CLI/configuration.")
            raise ProviderError(code="configuration")
        if telemetry.get("error_category"):
            category = telemetry["error_category"]
            raise ProviderError(code="refusal" if category == "refusal" else "incomplete_response" if category == "output_length" else "invalid_request",
                                limit_kind=category if category != "refusal" else None)
        if result.returncode == 0 and telemetry.get("terminal") != "completed":
            raise ProviderError(code="response_shape")
        return result
    except subprocess.TimeoutExpired as exc:
        # Existing diagnostics retain partial process output on exceptions.
        # Preserve only allowlisted observations, never raw partial reasoning.
        partial = exc.output or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        telemetry.update(events(partial))
        telemetry["process_outcome"] = "timeout"
        exc.output = None
        exc.stderr = None
        raise
    finally:
        telemetry["agent_process_seconds"] = time.monotonic() - started
        session["agent_telemetry"] = telemetry
        diagnostic.journal("agent.observed", **telemetry)
        # Raw event/error streams can contain reasoning, secrets and source text.
        diagnostic.local_artifact("cli-result", {"telemetry": telemetry})


def fingerprint(options):
    return hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()


def log_output(text):
    """Keep legacy technical logs, but suppress recognized agent reasoning streams."""
    observed = events(text)
    if observed["event_stream"] == "observed":
        return json.dumps(observed, sort_keys=True)
    if re.search(r"(?mi)^\s*(?:thinking|analysis|reasoning)\s*$", text):
        return "[Agent reasoning stream suppressed; final output retained separately]"
    return text
