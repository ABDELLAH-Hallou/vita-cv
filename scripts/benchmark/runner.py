"""Serial, immutable benchmark runs. Live dispatch requires a plan-bound authorization."""

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from vita import __version__
from vita.helpers import llm
from vita.helpers.diagnostics import PHASES
from vita.helpers.pipeline_config import STAGE_PREFIXES
from vita.helpers.provider_errors import safe_identifier

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CORPUS = HERE / "corpus"
ADAPTERS = (*llm._OPENAI_COMPATIBLE, "anthropic", "gemini", "google", "codex")
REASONING = {"openai", "openrouter", "codex"}
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
VERSION = 1


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def object_hash(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def corpus_manifest():
    files = {p.name: digest(p.read_bytes()) for p in sorted(CORPUS.iterdir()) if p.name != "manifest.json"}
    expected = read(CORPUS / "manifest.json")
    if files != expected["files"]:
        raise ValueError("Frozen corpus checksum mismatch; create a reviewed corpus revision.")
    return expected


def fixture_plan():
    cases = []
    for provider in ADAPTERS:
        for enabled in (False, True):
            cases.append({"id": f"{provider}-extract-{str(enabled).lower()}", "provider": provider,
                          "model": "fixture/custom-model-v1", "extraction": enabled,
                          "reasoning_effort": "low" if provider in REASONING else None})
    for provider in sorted(REASONING):
        cases.append({"id": provider + "-high", "provider": provider, "model": "fixture/custom-v2",
                      "reasoning_effort": "high", "extraction": True})
    for name, faults in {"format-recovery": ["malformed"], "overload-recovery": ["503"],
                         "rate-limit-recovery": ["429"], "authentication": ["401"],
                         "invalid-model": ["invalid_model"], "exhaustion": ["503"] * 3,
                         "shared-budget": ["503", "malformed"]}.items():
        cases.append({"id": name, "provider": "openai", "model": "fixture/custom-v1",
                      "reasoning_effort": None, "extraction": True, "faults": faults})
    for enabled in (False, True):
        cases.append({"id": f"codex-restricted-{str(enabled).lower()}", "provider": "codex",
                      "model": "fixture/custom-agent-v1", "reasoning_effort": "low", "extraction": enabled,
                      "execution_mode": "restricted", "agent_telemetry": True})
    return {"schema_version": VERSION, "cases": cases}


def validate_plan(plan, *, live):
    if set(plan) != {"schema_version", "cases"} or plan["schema_version"] != VERSION or not isinstance(plan["cases"], list) or not plan["cases"]:
        raise ValueError("Expected schema_version=1 and a nonempty cases array.")
    ids = set()
    for case in plan["cases"]:
        fields = {"id", "provider", "model", "extraction", "reasoning_effort"}
        optional = {"execution_mode", "agent_telemetry", "scenario", "arm", "repeat", "max_input_bytes", "target_language", "max_attempts", "fixture_approvals", "input_bundle", "approved_job_criteria"}
        if not fields.issubset(case) or set(case) - (fields | optional | ({"faults"} if not live else set())):
            raise ValueError("Invalid case fields (credentials/endpoints are not accepted in plans).")
        if not isinstance(case["id"], str) or not NAME.fullmatch(case["id"]) or case["id"] in ids:
            raise ValueError("Case IDs must be unique simple directory names.")
        ids.add(case["id"])
        if case["provider"] not in ADAPTERS or not safe_identifier(case["model"]) or type(case["extraction"]) is not bool:
            raise ValueError("Unsupported provider, unsafe model ID, or nonboolean extraction setting.")
        if case["reasoning_effort"] is not None and (case["provider"] not in REASONING or case["reasoning_effort"] not in {"minimal", "low", "medium", "high", "xhigh"}):
            raise ValueError("Reasoning is supported only for openai/openrouter/codex; use an explicit effort.")
        if optional.intersection(case):
            from scripts.benchmark.execution_comparison import validate_case
            validate_case(case)
            if live and case.get("fixture_approvals"):
                raise ValueError("Live comparisons cannot enable synthetic factual approvals")
        if "input_bundle" in case:
            from scripts.benchmark.input_bundle import validate
            validate(case["input_bundle"])
    if any("arm" in c for c in plan["cases"]):
        from scripts.benchmark.execution_comparison import validate_pairs
        validate_pairs(plan)


def validate_authorization(path, plan):
    auth = read(path)
    if (auth.get("plan_sha256") != object_hash(plan) or auth.get("acknowledge_api_billing") is not True
            or type(auth.get("max_requests")) is not int or not 1 <= auth["max_requests"] <= 10000):
        raise ValueError("Live authorization must acknowledge API billing, match the exact plan hash, and cap requests (1..10000).")
    expires = datetime.fromisoformat(auth["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("Live authorization has expired or lacks a timezone.")
    return auth


def child_env(project, case, mode):
    env = os.environ.copy()
    # An absolute venv Python does not activate its console scripts. Both
    # agent arms must have the real Vita CLI available in a checkout run.
    scripts = str(Path(sys.executable).parent)
    env["PATH"] = scripts + os.pathsep + env.get("PATH", "")
    for key in list(env):
        if key.startswith("VITA_") or key in {"ENABLE_JD_EXTRACTION", *(p + "_" + s for p in STAGE_PREFIXES.values() for s in ("PROVIDER", "MODEL"))}:
            if key != "VITA_CODEX":
                env.pop(key, None)
    env.update(PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               VITA_PROJECT_ROOT=str(project), VITA_REQUIREMENTS_DIR=str(project / ".vita/requirements-store"),
               VITA_DIAGNOSTIC_CONTENT="local", VITA_PROVIDER_MAX_ATTEMPTS="3",
               ENABLE_JD_EXTRACTION=str(case["extraction"]).lower())
    if mode == "fixture":
        for key in list(env):
            if any(part in key.upper() for part in ("API_KEY", "TOKEN", "PASSWORD", "SECRET")):
                env.pop(key, None)
        env.update({p.upper() + "_API_KEY": "fixture-not-a-credential" for p in ADAPTERS})
        env.update(VITA_PROVIDER_RETRY_BASE_SECONDS="0", VITA_PROVIDER_RETRY_MAX_SECONDS="0")
    for prefix in STAGE_PREFIXES.values():
        env[prefix + "_PROVIDER"], env[prefix + "_MODEL"] = case["provider"], case["model"]
    if "max_attempts" in case:
        env["VITA_PROVIDER_MAX_ATTEMPTS"] = str(case["max_attempts"])
    return env


def project_setup(path, case):
    path.mkdir(parents=True)
    (path / ".vita").mkdir()
    if "input_bundle" in case:
        from scripts.benchmark.input_bundle import copy
        copy(case["input_bundle"], path)
    else:
        for file in ("main.tex", "education.tex", "job.md", "requirements.json"):
            shutil.copyfile(CORPUS / file, path / file)
    write(path / ".vita/config.json", {"author": case.get("input_bundle", {}).get("candidate_id", "synthetic"), "tex_entry": "main.tex",
          "cover_tex_entry": "cover-letter.tex", "output_dir": "artifacts/pdf",
          "output_filename": "resume.pdf", "cover_output_filename": "letter.pdf"})
    config = {"model": case["model"]}
    if case["reasoning_effort"] is not None:
        config["reasoning_effort"] = case["reasoning_effort"]
    for key in ("execution_mode", "agent_telemetry", "max_input_bytes"):
        if key in case:
            config[key] = case[key]
    write(path / ".vita/extensions.json", {"llm_providers": {case["provider"]: config}})
    if "scenario" in case and "input_bundle" not in case:
        from scripts.benchmark.execution_comparison import prepare_inputs
        prepare_inputs(path, case)


def pending(project):
    for step in ("adapt", "cover"):
        path = project / f".vita/results/{step}.facts.json"
        if path.exists():
            report = read(path)
            if report["status"] in ("confirmation_required", "rejected") or report.get("application_status") != "applied":
                return {"step": step, "revision": report["revision"], "status": report["status"]}
    return None


def capture_outputs(project, destination):
    outputs = []
    paths = [project / "main.tex", project / "cover-letter.tex"]
    for folder in (".vita/results", ".vita/prompts", "artifacts/pdf"):
        directory = project / folder
        paths.extend(p for p in directory.glob("*") if p.is_file())
    for path in sorted(paths):
        if not path.is_file():
            continue
        relative = path.relative_to(project)
        target = destination / "outputs" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        outputs.append({"path": relative.as_posix(), "sha256": digest(path.read_bytes()), "bytes": path.stat().st_size})
    return outputs


def diagnostic_files(project):
    return set((Path(project) / ".vita/logs/traces").glob("*/events-*.jsonl"))


def public_span_timings(files):
    """Reuse sanitized host spans; never read prompts/private agent journals."""
    spans, outer, partial = [], [], False
    for path in sorted(files):
        starts, ends = {}, {}
        try:
            if path.stat().st_size > 16 * 1024 * 1024:
                partial = True
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    partial = True
                    continue
                if not isinstance(event, dict) or event.get("phase") not in PHASES:
                    continue
                identity = event.get("span_id")
                if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{16}", identity):
                    continue
                if event.get("event") == "span_start":
                    starts[identity] = event
                elif event.get("event") == "span_end":
                    ends[identity] = event
        except (OSError, UnicodeError):
            partial = True
            continue
        for identity, start in starts.items():
            end = ends.get(identity, {})
            duration = end.get("details", {}).get("duration_ms")
            duration = duration / 1000 if type(duration) in (int, float) and math.isfinite(duration) and duration >= 0 else None
            partial = partial or duration is None
            step = start.get("step")
            step = step if step in (*STAGE_PREFIXES, "build", "operation", "requirements", "analyze-qualitative", "review-qualitative", None) else None
            item = {"phase": start["phase"], "step": step, "span_id": identity,
                    "parent_span_id": start.get("parent_span_id"), "duration_seconds": duration,
                    "status": end.get("status") if end.get("status") in ("ok", "error", "interrupted") else "unreported"}
            spans.append(item)
            parent, visited, duplicate = start.get("parent_span_id"), set(), False
            while parent in starts and parent not in visited:
                visited.add(parent)
                ancestor = starts[parent]
                duplicate = duplicate or ancestor["phase"] == "step" and ancestor.get("step") == step
                parent = ancestor.get("parent_span_id")
            if start["phase"] == "step" and not duplicate:
                outer.append(item)
    return {"status": "partial" if partial else "observed" if spans else "unavailable",
            "clock": "host_monotonic_public_span_durations", "spans": spans, "stage_spans": outer,
            "scope": "Nested spans overlap; do not sum them as independent time or infer model startup/inference."}


def invoke(run_dir, case, workspace, label, argv, settings, *, seed=False, inject=False):
    directory = run_dir / "cases" / case["id"] / "commands"
    directory.mkdir(parents=True, exist_ok=True)
    number = len(list(directory.iterdir()))
    command_dir = directory / f"{number:03}-{label}"
    command_dir.mkdir()
    spec = {"mode": settings["mode"], "case": case, "argv": argv, "seed_controls": seed,
            "inject_faults": inject, "telemetry": str(command_dir / "transport.json"),
            "authorization": settings.get("frozen_authorization"), "ledger": str(run_dir / "request-ledger.json"),
            "real_pdf": settings["real_pdf"], "timeout": settings["timeout"]}
    write(command_dir / "invocation.json", spec)
    write(command_dir / "transport.json", {"requests": [], "synthetic_approvals": []})
    before_logs = diagnostic_files(workspace)
    started = time.monotonic()
    with (command_dir / "stdout.txt").open("w", encoding="utf-8") as out, (command_dir / "stderr.txt").open("w", encoding="utf-8") as err:
        try:
            result = subprocess.run([sys.executable, "-m", "scripts.benchmark.worker", str(command_dir / "invocation.json")],
                cwd=workspace, env=child_env(workspace, case, settings["mode"]), stdout=out, stderr=err,
                timeout=settings["timeout"] + 10, check=False)
            status, exit_status = "completed", result.returncode
        except subprocess.TimeoutExpired:
            status, exit_status = "timeout", None
    record = {"schema_version": VERSION, "label": label, "argv": ["vita", *argv],
              "cwd": str(workspace.relative_to(run_dir)), "exit_status": exit_status, "status": status,
              "duration_seconds": round(time.monotonic() - started, 6),
              "transport": read(command_dir / "transport.json"), "outputs": capture_outputs(workspace, command_dir),
              "pending_confirmation": pending(workspace)}
    record["host_timing"] = public_span_timings(diagnostic_files(workspace) - before_logs)
    record["outcomes"] = {p.name: read(p) for p in sorted((workspace / ".vita/results").glob("*.outcome.json"))}
    record["assessments"] = {p.stem: read(p) for p in (workspace / ".vita/results/analysis.json", workspace / ".vita/results/review.json") if p.exists()}
    record["job"] = read(workspace / ".vita/results/job.json") if (workspace / ".vita/results/job.json").exists() else None
    snapshot_path = workspace / ".vita/benchmark-inputs/manifest.json"
    record["input_snapshot"] = read(snapshot_path) if snapshot_path.is_file() else None
    write(command_dir / "record.json", record)
    return record


def controls(records):
    reports = {r["label"]: r["assessments"].get("review" if "review" in r["label"] else "analysis") for r in records}
    pairs = (("analyze_to_analyze", "control-analyze", "repeat-analyze"),
             ("analyze_to_review", "control-analyze", "control-review"),
             ("cache_reuse", "control-analyze", "cached-review"))
    result = {}
    for name, before, after in pairs:
        a, b = reports.get(before), reports.get(after)
        if not a or not b:
            result[name] = {"status": "unmeasured"}
            continue
        pa, pb = a["metadata"]["assessment"], b["metadata"]["assessment"]
        result[name] = {"status": "measured", "same_prompt": pa["prompt_sha256"] == pb["prompt_sha256"] and pa["system_sha256"] == pb["system_sha256"],
            "same_sources": pa["source_sha256"] == pb["source_sha256"],
            "same_criteria": pa["criteria_sha256"] == pb["criteria_sha256"],
            "delta": round(b["overall_score"] - a["overall_score"], 6),
            "execution": b["metadata"]["assessment_execution"],
            "attribution": "Unchanged CV control; any difference is reassessment, never tailoring."}
    return result


def summarize(plan, results):
    rows = {r["id"]: r for r in results}
    statuses = {name: sum(rows.get(c["id"], {}).get("status", "not_run") == name for c in plan["cases"])
                for name in ("passed", "failed", "unavailable", "confirmation_required", "not_run")}
    provider_results = {}
    for provider in sorted({c["provider"] for c in plan["cases"]}):
        selected = [c for c in plan["cases"] if c["provider"] == provider]
        provider_results[provider] = {"denominator": len(selected),
            "successful": sum(rows.get(c["id"], {}).get("status") == "passed" for c in selected),
            "unavailable": sum(rows.get(c["id"], {}).get("status") == "unavailable" for c in selected),
            "quality": "unmeasured"}
    attempts = [o.get("attempts", []) for r in results for cmd in r["commands"]
                if cmd["label"] == "pipeline" for o in cmd["outcomes"].values()]
    return {"denominator": len(plan["cases"]), "counts": statuses, "providers": provider_results,
            "success_rate": statuses["passed"] / len(plan["cases"]),
            "generation_operations": {"with_attempts": sum(bool(a) for a in attempts),
                "first_attempt_valid": sum(bool(a) and a[0]["category"] == "valid" for a in attempts),
                "recovered": sum(len(a) > 1 and a[-1]["category"] == "valid" for a in attempts)},
            "quality": {"status": "unmeasured", "reason": "Requires source-linked paired human adjudication; unavailable providers are N/A, never zero-quality.",
                        "billing": "unknown; usage is provider-reported, not independently audited"}}


def execute_case(run_dir, case, settings, previous=None):
    base = run_dir / "cases" / case["id"]
    workflow = base / "workflow"
    if previous is None:
        for folder in ("workflow", "manual", "controls"):
            project_setup(base / folder, case)
        language = ["--language", case["target_language"]] if case.get("target_language") else []
        record = invoke(run_dir, case, workflow, "pipeline", ["run", "--auto", *language], settings,
                        inject=True, seed=case.get("approved_job_criteria", False))
        records = [record]
    else:
        records = previous["commands"]
        if pending(workflow):
            return previous
        # A human has resolved the frozen proposal with the product's facts CLI.
        decision = read(workflow / f".vita/results/{previous['pending_confirmation']['step']}.facts.json")
        if decision["revision"] != previous["pending_confirmation"]["revision"]:
            raise ValueError("The approved factual revision differs from the suspended run.")
        records[-1]["resolved_confirmation"] = previous["pending_confirmation"]
        record = {"exit_status": 0}
        todo = ["review", "cover"] if previous["pending_confirmation"]["step"] == "adapt" else []
        for step in todo:
            record = invoke(run_dir, case, workflow, "resumed-" + step, [step, "--auto"], settings)
            records.append(record)
            if record["exit_status"] != 0:
                break
    waiting = pending(workflow)
    if waiting:
        result = {"id": case["id"], "status": "confirmation_required", "pending_confirmation": waiting, "commands": records,
                  "quality": {"status": "unmeasured", "value": None}}
        write(base / "result.json", result)
        return result
    if record["exit_status"] != 0:
        transports = [t for r in records for t in r["transport"]["requests"]]
        host_input_failure = any((o.get("error") or {}).get("limit_kind") == "input_context" for o in record.get("outcomes", {}).values())
        result = {"id": case["id"], "status": "failed" if host_input_failure or any(t["status"] == "response" for t in transports) else "unavailable",
                  "failure_origin": "input_context" if host_input_failure else "generation_or_availability",
                  "commands": records, "controls": {}, "quality": {"status": "unmeasured", "value": None},
                  "build": "not_attempted", "stop_reason": "Pipeline failed; downstream commands were not run."}
        write(base / "result.json", result)
        return result
    records.append(invoke(run_dir, case, workflow, "build", ["build", "both"], settings))
    manual = base / "manual"
    for step in ("extract", "analyze", "adapt", "review", "cover", "run"):
        records.append(invoke(run_dir, case, manual, "manual-" + step, [step], settings))
    control = base / "controls"
    for label, argv in (("control-analyze", ["analyze", "--auto"]), ("repeat-analyze", ["analyze", "--auto", "--reassess"]),
                        ("control-review", ["review", "--auto", "--reassess"]), ("cached-review", ["review", "--auto"])):
        records.append(invoke(run_dir, case, control, label, argv, settings, seed=label == "control-analyze"))
    transports = [t for r in records for t in r["transport"]["requests"]]
    status = "passed" if all(r["exit_status"] == 0 or r.get("resolved_confirmation") for r in records) else "failed"
    if not any(t["status"] == "response" for t in transports):
        status = "unavailable"
    result = {"id": case["id"], "status": status, "commands": records, "controls": controls(records),
              "quality": {"status": "unmeasured", "value": None},
              "build": "real_latex" if settings["real_pdf"] or settings["mode"] == "live" else "fixture_handoff_only"}
    write(base / "result.json", result)
    return result


def fixture_failures(case, result):
    """Conformance assertions are separate from provider reliability outcomes."""
    errors = []
    if case.get("scenario") == "context_limit":
        outcomes = result["commands"][0]["outcomes"]
        return [] if result["status"] == "failed" and any((o.get("error") or {}).get("limit_kind") == "input_context" for o in outcomes.values()) else ["Context limit did not stop safely before generation"]
    if case.get("scenario") in ("ambiguities", "missing_evidence") and case.get("fixture_approvals") is False:
        command = result["commands"][0]
        original = command["input_snapshot"]["files"]["main.tex"]
        unchanged = any(o["path"] == "main.tex" and o["sha256"] == original for o in command["outputs"])
        return [] if result["status"] == "confirmation_required" and unchanged else ["Unreviewed proposal changed the original or failed to stop"]
    failed = case.get("faults") in (["401"], ["invalid_model"], ["503"] * 3)
    if result["status"] != ("unavailable" if failed else "passed"):
        errors.append("Unexpected reliability outcome: " + result["status"])
    pipeline = result["commands"][0]
    if pipeline["exit_status"] != int(failed):
        errors.append("Incorrect pipeline exit status")
    extraction = ".vita/results/job.json" in {o["path"] for o in pipeline["outputs"]}
    if extraction != (case["extraction"] and not failed):
        errors.append("Extraction toggle/output contract violated")
    if extraction:
        job = pipeline["job"]["jobs"][0]
        if job["location"] != "Remote, France" or "conflict" not in job["summary"].lower() or job["hard_skills"] != ["Python"]:
            errors.append("Role conflict, job location, or navigation/form-noise fixture contract failed")
    requests = pipeline["transport"]["requests"]
    if any(t.get("wire_model") != case["model"] for t in requests):
        errors.append("Wire model differs from explicit model ID")
    if any(t.get("reasoning_effort") != case["reasoning_effort"] for t in requests):
        errors.append("Wire reasoning differs from explicit setting")
    if case.get("faults"):
        outcome = pipeline["outcomes"].get("extract.outcome.json", {})
        expected = len(case["faults"]) + (0 if failed else 1)
        if len(outcome.get("attempts", [])) != expected:
            errors.append("Shared retry budget/attempt count violated")
        if outcome.get("attempts", [{}])[0].get("category") == "valid":
            errors.append("First-attempt failure was lost")
    if not failed:
        for report in pipeline["assessments"].values():
            provenance = report.get("metadata", {}).get("assessment", {})
            required = {"source_sha256", "job_sha256", "criteria_sha256", "provider", "model",
                        "reasoning_effort", "prompt_sha256", "schema_sha256", "host_sha256"}
            if not required.issubset(provenance) or provenance.get("model") != case["model"] or provenance.get("provider") != case["provider"]:
                errors.append("Missing or incorrect assessment provenance")
        if pipeline["assessments"].get("review", {}).get("assessment_comparison", {}).get("kind") != "cv_changed":
            errors.append("Actual fixture edit was not distinguished from unchanged controls")
        for name, pair in result["controls"].items():
            if pair.get("status") != "measured" or not all(pair.get(k) for k in ("same_prompt", "same_sources", "same_criteria")):
                errors.append("Invalid unchanged-input control: " + name)
        if result["controls"]["cache_reuse"].get("execution", {}).get("mode") != "reused":
            errors.append("Identical-input Review did not reuse its assessment")
        for r in result["commands"]:
            if r["label"].startswith("manual-") and r["transport"]["requests"]:
                errors.append("Manual mode dispatched a provider request")
            if r["label"].startswith("manual-") and r["label"] != "manual-run":
                step = r["label"].removeprefix("manual-")
                if f".vita/prompts/{step}.md" not in {o["path"] for o in r["outputs"]}:
                    errors.append("Missing manual prompt: " + step)
        build = next(r for r in result["commands"] if r["label"] == "build")
        if not {"artifacts/pdf/resume.pdf", "artifacts/pdf/letter.pdf"}.issubset(o["path"] for o in build["outputs"]):
            errors.append("PDF output handoff missing")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", type=Path, help="Resume live cases after explicit factual approval")
    parser.add_argument("--real-pdf", action="store_true")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--plan-hash", action="store_true", help="Print exact plan hash without any execution")
    parser.add_argument("--case", action="append", help="Select fixture case ID (repeatable; never filters live authorization)")
    args = parser.parse_args(argv)
    try:
        plan = read(args.plan) if args.plan else fixture_plan()
        validate_plan(plan, live=args.mode == "live")
        if args.case:
            if args.mode != "fixture" or set(args.case) - {c["id"] for c in plan["cases"]}:
                raise ValueError("--case requires known fixture IDs; live runs must use their exact authorized plan.")
            plan = {**plan, "cases": [c for c in plan["cases"] if c["id"] in args.case]}
        if args.mode == "live" and args.plan is None:
            raise ValueError("Live runs require an explicit plan; defaults are fixture-only.")
        if args.plan_hash:
            print(object_hash(plan))
            return 0
        if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 3600:
            raise ValueError("Timeout must be between 1 and 3600 seconds.")
        if args.mode == "live":
            if args.authorization is None:
                raise ValueError("Live runs require a plan-bound --authorization file. No subscription/API billing assumptions.")
            authorization = validate_authorization(args.authorization, plan)
        bundles = {c["id"]: c["input_bundle"] for c in plan["cases"] if "input_bundle" in c}
        corpus = {"revision": "case-pinned-bundles-v1", "bundles": bundles} if bundles else corpus_manifest()
        if args.resume and (args.mode != "live" or args.output):
            raise ValueError("--resume is live-only and replaces --output.")
        if not args.resume and args.output is None:
            raise ValueError("Specify a new --output directory.")
        run_dir = (args.resume or args.output).resolve()
        settings = {"mode": args.mode, "timeout": args.timeout, "real_pdf": args.real_pdf,
                    "authorization": str(args.authorization.resolve()) if args.authorization else None}
        source_files = (sorted((ROOT / "vita").rglob("*.py")) + sorted((ROOT / "vita/assets").rglob("*.md")) + sorted(HERE.glob("*.py"))
                        + sorted((ROOT / "scripts/evaluation").glob("*.py"))
                        + [ROOT / name for name in ("EVALUATION_PROTOCOL.md", "ANNOTATION_GUIDE.md", "BENCHMARKING.md", "AGENT_EXECUTION.md") if (ROOT / name).is_file()])
        source_versions = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in source_files}
        if args.resume:
            old = read(run_dir / "manifest.json")
            if old["plan_sha256"] != object_hash(plan) or old["corpus"] != corpus or old["version"] != __version__ or old["settings"] != settings or old["source_versions"] != source_versions:
                raise ValueError("Resume requires the same plan, corpus, Vita version, and settings.")
        else:
            run_dir.mkdir(parents=True, exist_ok=False)
            try:
                revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
                commit = revision.stdout.strip() if revision.returncode == 0 else None
            except OSError:
                commit = None
            write(run_dir / "manifest.json", {"schema_version": VERSION, "version": __version__,
                "python": platform.python_version(), "platform": platform.platform(),
                "git_revision": commit,
                "started_at": datetime.now(timezone.utc).isoformat(), "plan": plan, "plan_sha256": object_hash(plan),
                "settings": settings, "corpus": corpus, "ordering": "serial, listed case order; pipeline then manual then unchanged controls",
                "source_versions": source_versions,
                "limits": {"generation_attempts_per_operation": 3, "request_timeout_seconds": 120,
                           "retry_base_seconds": 0 if args.mode == "fixture" else 1,
                           "retry_max_seconds": 0 if args.mode == "fixture" else 30,
                           "authorization_max_requests": read(args.authorization)["max_requests"] if args.authorization else 0},
                "approval_policy": "Fixture-only synthetic approvals; live changes require explicit revision-bound human decisions."})
        if args.mode == "live":
            approved = {k: authorization[k] for k in ("plan_sha256", "acknowledge_api_billing", "max_requests", "expires_at")}
            frozen = run_dir / "authorizations" / (object_hash(approved) + ".json")
            if not frozen.exists():
                write(frozen, approved)
            settings["frozen_authorization"] = str(frozen)
        results, errors = [], []
        for case in plan["cases"]:
            previous_path = run_dir / "cases" / case["id"] / "result.json"
            previous = read(previous_path) if previous_path.exists() else None
            if previous and previous["status"] != "confirmation_required":
                result = previous
            else:
                result = execute_case(run_dir, case, settings, previous)
            results.append(result)
            if args.mode == "fixture":
                errors.extend(case["id"] + ": " + e for e in fixture_failures(case, result))
            summary = summarize(plan, results)
            write(run_dir / "summary.json", {"schema_version": VERSION, "reliability": summary, "conformance_errors": errors, "cases": results})
            print(f"{case['id']}: {result['status']}", flush=True)
        (run_dir / "summary.md").write_text(
            "# Standalone Vita CV benchmark\n\n" + f"Mode: {args.mode}. Serial execution. Corpus revision: {corpus['revision']}.\n\n"
            + "| Result | Cases |\n| --- | ---: |\n" + "\n".join(f"| {k} | {v} |" for k, v in summary["counts"].items())
            + f"\n\nReliability denominator: {summary['denominator']}; success rate: {summary['success_rate']:.2%}.\n\n"
            + "Content quality: **unmeasured** pending source-linked human adjudication under EVALUATION_PROTOCOL.md. Unavailable providers: N/A for quality, retained in reliability.\n\n"
            + "Analyze-to-Analyze fresh repeats and Analyze-to-Review fresh controls are separate in summary.json. Cached controls are not independent generations. Fixture PDF files are handoff markers unless --real-pdf was selected.\n\n"
            + "Provider-reported usage is recorded when available. Unknown usage and billing are not zero. See each command's record.json, transport.json, stdout/stderr, frozen outputs, and project execution journals.\n", encoding="utf-8")
        write(run_dir / "adjudication-template.json", {"plan_sha256": object_hash(plan), "corpus": corpus,
            "rubric": {"protocol": "EVALUATION_PROTOCOL.md", "annotation_guide": "ANNOTATION_GUIDE.md", "source_reviews": "pending; no synthetic oracle applies to these public documents"} if bundles else read(CORPUS / "oracle.json"), "judge": None,
            "cases": [{"id": r["id"], "content_quality": None, "status": "unmeasured",
                       "reason": "Provider unavailable" if r["status"] == "unavailable" else "Awaiting human adjudication",
                       "output_refs": [str(p.relative_to(run_dir)) for p in sorted((run_dir / "cases" / r["id"] / "commands").glob("*/record.json"))]} for r in results]})
        print(f"Results: {run_dir / 'summary.json'}")
        return 1 if errors or (args.mode == "live" and any(r["status"] != "passed" for r in results)) else 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"Benchmark configuration/execution error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
