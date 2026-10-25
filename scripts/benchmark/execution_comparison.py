"""Prepare paired development plans and analyze existing benchmark records.

Execution, spending authorization and persistence stay in scripts.benchmark.
No semantic labels or independent human reviews are fabricated here.
"""

import argparse
import math
import random
import statistics
from pathlib import Path

from scripts.benchmark import runner
from scripts.evaluation.scoring import proportion

SCENARIOS = ("short", "long_includes", "mismatched_role", "missing_evidence", "ambiguities",
             "spanish", "french", "arabic", "malformed", "context_limit")
THRESHOLDS = {"status": "proposed_requires_user_decision_before_live_comparison",
              "minimum_paired_median_speed_improvement": 0.20,
              "maximum_regression_percentage_points": {k: 0 for k in (
                  "factual_error_documents", "unsupported_additions", "contradictions", "harmful_omissions",
                  "requirement_classification", "requirement_satisfaction", "translation_fidelity")},
              "critical_factual_errors": 0, "minimum_completion_rate": 0.95,
              "minimum_delivered_document_build_success": 1.0,
              "minimum_independently_reviewed_document_usability": 1.0,
              "maximum_critical_layout_defects": 0,
              "maximum_human_correction_time_relative_regression": 0.0,
              "maximum_blinded_rating_regression": {"relevance": 0, "clarity": 0, "usefulness": 0},
              "population": "Future preregistered supported-input primary cases, retaining unexpected failures/unavailability; deliberate invalid-input controls require safe stops separately. Not fixture adoption thresholds.",
              "practical_rubric": "Proposed 1..5 blinded ratings; custodian must approve a protocol supplement before collection. No ratings supplied.",
              "policy": "Engineering proposals, not approved quality-loss tolerances or measured findings."}
EFFORTS = ("minimal", "low", "medium", "high", "xhigh")


def rate(numerator, denominator):
    # Repeated generations share scenarios/sources; a naive binomial interval
    # treating every repeat as an independent case would overstate precision.
    return proportion(numerator, denominator, interval=False)


def validate_pairs(plan):
    selected = [c for c in plan["cases"] if "arm" in c]
    if not selected:
        return
    if len({c["model"] for c in selected}) != 1:
        raise ValueError("Use one exact model per comparison plan; do not pool different models")
    if len({c["reasoning_effort"] for c in selected if c["arm"] == "A"}) != 1:
        raise ValueError("Use one baseline reasoning effort per comparison plan")
    groups = {}
    for case in selected:
        arms = groups.setdefault((case["scenario"], case["repeat"]), {})
        if case["arm"] in arms:
            raise ValueError("Duplicate paired arm")
        arms[case["arm"]] = case
    for arms in groups.values():
        if not {"A", "B"}.issubset(arms):
            raise ValueError("Full comparison plans require both A and B; filtering is fixture-only")
        a, b = arms["A"], arms["B"]
        fields = ("provider", "model", "reasoning_effort", "extraction", "max_attempts", "target_language", "max_input_bytes", "faults")
        if a["execution_mode"] != "baseline" or b["execution_mode"] != "restricted" or any(a.get(k) != b.get(k) for k in fields):
            raise ValueError("A/B must preserve model, reasoning, inputs and attempt budget")
        if "C" in arms:
            c = arms["C"]
            if c["execution_mode"] != "restricted" or EFFORTS.index(c["reasoning_effort"]) >= EFFORTS.index(a["reasoning_effort"]):
                raise ValueError("C must use separately lower reasoning")
            if any(a.get(k) != c.get(k) for k in fields if k != "reasoning_effort"):
                raise ValueError("C must preserve all other paired settings")


def validate_case(case):
    if case["provider"] != "codex" or case.get("execution_mode", "baseline") not in ("baseline", "restricted"):
        raise ValueError("Execution comparisons currently support only baseline/restricted Codex CLI")
    if type(case.get("agent_telemetry", False)) is not bool:
        raise ValueError("agent_telemetry must be boolean")
    if case.get("scenario", "short") not in SCENARIOS or case.get("arm", "A") not in ("A", "B", "C"):
        raise ValueError("Unknown comparison scenario/arm")
    if type(case.get("repeat", 1)) is not int or not 1 <= case.get("repeat", 1) <= 20:
        raise ValueError("Repeat must be 1..20")
    if type(case.get("max_input_bytes", 2_000_000)) is not int or not 1 <= case.get("max_input_bytes", 2_000_000) <= 20_000_000:
        raise ValueError("Invalid complete-input byte guard")
    if case.get("target_language") not in (None, "en", "es", "fr", "ar"):
        raise ValueError("Unsupported comparison language")
    if case.get("execution_mode") == "restricted" and case["reasoning_effort"] is None:
        raise ValueError("Restricted comparison requires explicit reasoning")
    if type(case.get("max_attempts", 3)) is not int or not 1 <= case.get("max_attempts", 3) <= 5:
        raise ValueError("Invalid shared attempt budget")
    if type(case.get("fixture_approvals", False)) is not bool:
        raise ValueError("fixture_approvals must be boolean")


def plan(model, reasoning, repeats=2, *, lower_reasoning=None, reverse=False, fixture=True):
    arms = [("A", "baseline", reasoning), ("B", "restricted", reasoning)]
    if lower_reasoning is not None:
        if reasoning not in EFFORTS or lower_reasoning not in EFFORTS or EFFORTS.index(lower_reasoning) >= EFFORTS.index(reasoning):
            raise ValueError("Optional C must have a separately selected lower reasoning effort")
        arms.append(("C", "restricted", lower_reasoning))
    if reverse:
        arms.reverse()
    cases = []
    for scenario in SCENARIOS:
        for repeat in range(1, repeats + 1):
            for arm, execution, effort in arms:
                case = {"id": f"{scenario}-{repeat}-{arm}", "provider": "codex", "model": model,
                        "reasoning_effort": effort, "extraction": True, "execution_mode": execution,
                        "agent_telemetry": True, "scenario": scenario, "arm": arm, "repeat": repeat, "max_attempts": 3,
                        "fixture_approvals": fixture and scenario not in ("ambiguities", "missing_evidence")}
                if scenario in ("spanish", "french", "arabic"):
                    case["target_language"] = {"spanish": "es", "french": "fr", "arabic": "ar"}[scenario]
                if scenario == "malformed" and fixture:
                    case["faults"] = ["malformed"]
                if scenario == "context_limit":
                    case["max_input_bytes"] = 256
                cases.append(case)
    result = {"schema_version": 1, "cases": cases}
    runner.validate_plan(result, live=not fixture)
    return result


def prepare_inputs(path, case):
    scenario = case["scenario"]
    main = path / "main.tex"
    content = main.read_text(encoding="utf-8")
    if scenario == "long_includes":
        history = "\n".join(f"\\section{{History {year}}}\nAtelier Boréal, service maintenance, {year}; 250 ms.\\par" for year in range(1995, 2026))
        (path / "history.tex").write_text(history, encoding="utf-8")
        content = content.replace(r"\end{document}", "\\input{history}\n" + r"\end{document}")
    if scenario == "ambiguities":
        content = content.replace(r"\end{document}", "Sen 2017; TTR undefined; OOP; 125000 currency unspecified; 40\\% reduction; 250 ms.\\par\nCertificado Delta expired 2020; master's in progress, degree not awarded.\n" + r"\end{document}")
    if scenario == "missing_evidence":
        content = content.replace("Python engineer", "Community coordinator").replace("Built Python services", "Coordinated community events")
    if scenario == "mismatched_role":
        job = path / "job.md"
        job.write_text(job.read_text(encoding="utf-8") + "\nMismatched-role control: quota-carrying sales leadership; no technical-role substitution.\n", encoding="utf-8")
    if scenario in ("spanish", "french", "arabic"):
        text = {"spanish": "Formación y voluntariado; máster en curso, no otorgado.",
                "french": "Formation et bénévolat; master en cours, diplôme non obtenu.",
                "arabic": "التعليم والتطوع؛ الماجستير قيد الإنجاز ولم تمنح الدرجة."}[scenario]
        if scenario == "arabic":
            content = content.replace(r"\begin{document}", "\\usepackage{fontspec}\n\\usepackage{polyglossia}\n\\setmainfont{DejaVu Serif}\n\\newfontfamily\\arabicfont[Script=Arabic]{Amiri}\n\\setdefaultlanguage{english}\n\\setotherlanguage{arabic}\n\\begin{document}")
            text = r"\textarabic{" + text + "}"
            config = runner.read(path / ".vita/config.json")
            config["latex_engine"] = "xelatex"
            runner.write(path / ".vita/config.json", config)
        (path / "education.tex").write_text("\\section{Education}\n" + text + "\n", encoding="utf-8")
    main.write_text(content, encoding="utf-8")
    frozen = path / ".vita/benchmark-inputs"
    frozen.mkdir()
    hashes = {}
    for source in (main, path / "job.md", path / "education.tex", path / "history.tex", path / "requirements.json"):
        if source.is_file():
            data = source.read_bytes()
            (frozen / source.name).write_bytes(data)
            hashes[source.name] = runner.digest(data)
    runner.write(frozen / "manifest.json", {"split": "development_only", "scenario": scenario, "files": hashes})


def quantiles(values):
    values = sorted(values)
    return {"n": len(values), "median": statistics.median(values) if values else None,
            "p95": values[max(0, math.ceil(.95 * len(values)) - 1)] if values else None,
            "p95_method": "nearest_rank"}


def paired_interval(clusters):
    # Resample independent families, preserving dependent repetitions inside one.
    if len(clusters) < 2:
        return None
    rng = random.Random(43043)
    samples = sorted(statistics.median([v for cluster in rng.choices(clusters, k=len(clusters)) for v in cluster]) for _ in range(2000))
    return [samples[49], samples[1949]]


def report(root):
    root = Path(root)
    manifest, summary = runner.read(root / "manifest.json"), runner.read(root / "summary.json")
    planned = manifest["plan"]["cases"]
    results = {r["id"]: r for r in summary["cases"]}
    stages, paired, terminal_pairs, rows, review_refs = {}, {}, {}, [], []
    for case in planned:
        result = results.get(case["id"], {"status": "not_run", "commands": []})
        commands = result["commands"]
        workflow = [c for c in commands if c["label"] == "pipeline" or c["label"].startswith("resumed-")]
        row = {**case, "status": result["status"], "end_to_end_seconds": sum(c["duration_seconds"] for c in commands if not c["label"].startswith(("manual-", "control-", "repeat-", "cached-"))) if commands else None,
               "approval_wait_seconds": None, "content_quality": "unmeasured",
               "fresh_generation_requested": any(c.get("transport", {}).get("requests") for c in commands)}
        rows.append(row)
        unique = {}
        for operation in workflow:
            recorded = operation.get("outcomes", {})
            order = ("extract", "analyze", "adapt", "review", "cover")
            latest = next((s for s in reversed(order) if f"{s}.outcome.json" in recorded), None)
            timing = operation.get("host_timing")
            if timing is None and len(workflow) == 1 and operation.get("cwd"):
                # Older frozen runs already retained public spans. Workflow-only
                # files have one pipeline plus a separate build; exclude build.
                project = (root / operation["cwd"]).resolve()
                timing = runner.public_span_timings(runner.diagnostic_files(project)) if project.is_relative_to(root.resolve()) else None
            for filename, outcome in recorded.items():
                step = filename.split(".")[0]
                identity = outcome.get("run_id", step)
                if identity not in unique:
                    matches = [s for s in (timing or {}).get("stage_spans", []) if s["step"] == step]
                    unique[identity] = {"step": step, "outcome": outcome,
                        "host_stage": matches[0] if len(matches) == 1 else None,
                        "requests": [t for t in operation.get("transport", {}).get("requests", []) if t.get("step") == step]}
                # Snapshots retain old outcomes on resume. Deduplicate generation
                # IDs while allowing later explicit approvals to resolve a stop.
                entry = unique[identity]
                entry["confirmation"] = (operation.get("pending_confirmation") or {}).get("step") == step and not operation.get("resolved_confirmation")
                entry["post_generation_failure"] = (operation.get("exit_status") not in (None, 0) and step == latest
                                                    and step in ("adapt", "cover") and outcome["status"] == "success" and not entry["confirmation"])
        for entry in unique.values():
            step, outcome = entry["step"], entry["outcome"]
            key = (case["provider"], case["model"], case["reasoning_effort"], case["execution_mode"], step)
            bucket = stages.setdefault(key, [])
            attempts = outcome.get("attempts", [])
            confirmation, requests = entry["confirmation"], entry["requests"]
            terminal = "approval_required" if confirmation else "post_generation_failure" if entry["post_generation_failure"] else outcome["status"]
            host_stage = entry.get("host_stage") or {}
            bucket.append({"case": case["id"], "terminal": terminal,
                           "contract_status": outcome["status"], "category": (outcome.get("error") or {}).get("category", (outcome.get("error") or {}).get("code")),
                           "input_sha256": outcome.get("input_sha256"),
                           "provider_requests": requests,
                           "time_to_contract_valid_seconds": outcome.get("time_to_contract_valid_seconds"),
                           "time_to_validated_output_seconds": host_stage.get("duration_seconds") if terminal == "success" and host_stage.get("status") == "ok" else None,
                           "terminal_seconds": host_stage.get("duration_seconds"),
                           "operation_terminal_seconds": outcome.get("duration_seconds"), "host_stage": host_stage,
                           "attempts": len(attempts),
                           "cache_reused": bool(outcome.get("cache")), "fresh_generation": bool(requests),
                           "first_attempt_contract_valid": bool(attempts and attempts[0]["category"] == "valid"),
                           "format_repairs": sum(a["category"] in ("invalid_json", "schema_error", "validation_error") for a in attempts[:-1]),
                           "transport_retries": sum(a["category"] in ("overloaded", "rate_limit", "server_error", "connection", "timeout") for a in attempts[:-1]),
                           "attempt_records": attempts})
        if result["status"] == "passed" and row["end_to_end_seconds"] is not None:
            paired[(case["scenario"], case["repeat"], case["arm"])] = row["end_to_end_seconds"]
        if row["end_to_end_seconds"] is not None:
            terminal_pairs[(case["scenario"], case["repeat"], case["arm"])] = row["end_to_end_seconds"]
        for command in commands:
            for output in command["outputs"]:
                if output["path"].endswith(("adapt.facts.json", "cover.facts.json")):
                    review_refs.append({"case": case["id"], "command": command["label"], **output,
                                        "review_includes_blocked_proposal": True, "human_review": "pending"})
    comparisons = []
    for arm in ("B", "C"):
        clusters = []
        for scenario in SCENARIOS:
            values = [1 - paired[(scenario, repeat, arm)] / baseline for (s, repeat, a), baseline in paired.items()
                      if s == scenario and a == "A" and baseline > 0 and (scenario, repeat, arm) in paired]
            if values:
                clusters.append(values)
        comparisons.append({"contrast": arm + " versus A", "complete_paired_repeats": sum(map(len, clusters)),
                            "time_change_definition": "1 - compared workflow seconds / baseline seconds; positive is less time, negative is more time (not reciprocal throughput).",
                            "scenario_clusters": len(clusters), "paired_fractional_speed_change": quantiles([v for c in clusters for v in c]),
                            "independent_families": int(bool(clusters)),
                            "family_cluster_bootstrap95": paired_interval([[v for c in clusters for v in c]] if clusters else []),
                            "all_outcome_terminal_time_change": quantiles([1 - terminal_pairs[(scenario, repeat, arm)] / baseline for (scenario, repeat, a), baseline in terminal_pairs.items()
                                if a == "A" and baseline > 0 and (scenario, repeat, arm) in terminal_pairs]),
                            "interpretation": "Fixture host mechanics only; no real model speed claim." if manifest["settings"]["mode"] == "fixture" else "Pilot paired timings; semantic noninferiority unmeasured."})
    stage_rows = []
    for case in planned:
        for step in ("extract", "analyze", "adapt", "review", "cover"):
            stages.setdefault((case["provider"], case["model"], case["reasoning_effort"], case["execution_mode"], step), [])
    for (provider, model, reasoning, execution, step), values in sorted(stages.items()):
        generated = [v for v in values if v["fresh_generation"]]
        planned_n = sum((c["provider"], c["model"], c["reasoning_effort"], c["execution_mode"]) == (provider, model, reasoning, execution) for c in planned)
        attempts = [a for v in values for a in v["attempt_records"]]
        telemetry = [a.get("agent_telemetry", {}) for a in attempts]
        reported_usage = [t["usage"] for t in telemetry if t.get("usage")]
        stage_rows.append({"provider": provider, "model": model, "reasoning": reasoning, "execution": execution, "stage": step,
            "planned_operations": planned_n, "not_run_operations": planned_n - len(values),
            "attempted_operations": len(values), "fresh_generation_operations": len(generated),
            "cache_reuse_operations": sum(v["cache_reused"] for v in values),
            "first_attempt_contract_validity": rate(sum(v["first_attempt_contract_valid"] for v in generated), len(generated)),
            "contract_completion": rate(sum(v["contract_status"] == "success" for v in values), len(values)),
            "terminal_rates": {status: rate(sum(v["terminal"] == status or v["category"] == status for v in values), len(values)) for status in ("success", "failed", "post_generation_failure", "timeout", "approval_required", "incomplete_response", "refusal")},
            "time_to_validated_output_seconds": quantiles([v["time_to_validated_output_seconds"] for v in values if v["time_to_validated_output_seconds"] is not None]),
            "time_to_contract_valid_seconds": quantiles([v["time_to_contract_valid_seconds"] for v in values if v["time_to_contract_valid_seconds"] is not None]),
            "all_terminal_seconds": quantiles([v["terminal_seconds"] for v in values if v["terminal_seconds"] is not None]),
            "efficiency": {"model_calls": None, "cost": None,
                "host_generation_dispatches": sum(len(v["provider_requests"]) for v in values),
                "format_repairs": sum(v["format_repairs"] for v in values), "transport_retries": sum(v["transport_retries"] for v in values),
                "reported_usage_attempts": len(reported_usage), "unknown_usage_attempts": len(attempts) - len(reported_usage),
                "observed_token_totals": {key: sum(u.get(key, 0) for u in reported_usage) for key in {k for u in reported_usage for k in u}} if reported_usage else None,
                "tool_calls_by_attempt": [t.get("tool_calls") for t in telemetry], "denied_calls_by_attempt": [t.get("denied_tool_calls") for t in telemetry]},
            "operations": values})
    reference_states = [criterion.get("evidence_verification", {}).get("status", "unreported") for r in results.values() for c in r["commands"]
                        for assessment in c.get("assessments", {}).values() for criterion in assessment["metrics"]["criteria"]]
    value = {"contract_version": "execution-comparison/1", "plan_sha256": manifest["plan_sha256"], "mode": manifest["settings"]["mode"],
             "execution_git_revision": manifest.get("git_revision"),
             "execution_source_versions": manifest.get("source_versions"),
             "analysis_source_sha256": runner.digest(Path(__file__).read_bytes()),
             "split": "development_only", "ordering": "serial in exact listed plan order; reverse ordering requires a separately authorized reversed plan",
             "planned": len(planned), "not_run": sum(r["status"] == "not_run" for r in rows),
             "attempted": sum(r["status"] != "not_run" for r in rows), "cases": rows, "stages": stage_rows,
             "paired": comparisons, "proposed_thresholds": THRESHOLDS, "approval_waits": "unmeasured; not included in generation durations",
             "accuracy": {key: {"numerator": None, "denominator": 0, "status": "unmeasured_pending_independent_review"} for key in THRESHOLDS["maximum_regression_percentage_points"]},
             "source_reference_verification": {"criterion_observations": len(reference_states), "counts": {s: reference_states.count(s) for s in sorted(set(reference_states))},
                 "interpretation": "Mechanical quotation/source checks; includes dependent repeated report observations, not semantic accuracy."},
             "uncertainty": "No naive binomial intervals for dependent repeats. All current variants share one synthetic candidate/job family: family-cluster speed intervals are unestimable, not invented from variant/repeat counts. Completed-output comparisons condition on both arms completing.",
             "practical_quality": {"correction_time": None, "blinded_preference": None, "layout_defects": None},
             "document_builds": {"attempted": sum(c["label"] == "build" for r in results.values() for c in r["commands"]),
                 "successful": sum(c["label"] == "build" and c["exit_status"] == 0 for r in results.values() for c in r["commands"]),
                 "measurement": "real_compilation" if manifest["settings"].get("real_pdf") or manifest["settings"]["mode"] == "live" else "fixture_handoff_only"},
             "proposal_review_inventory": review_refs, "accepted_output_resources": None,
             "host_generation_dispatches": sum(len(c.get("transport", {}).get("requests", [])) for r in results.values() for c in r["commands"]),
             "document_validation_timing": "Validated-output and stage-terminal timings use outer public host step spans, including preparation and document gates. Unavailable/unfinished/ambiguous spans remain null. Post-approval waiting is unmeasured and generation-contract timing is never substituted.",
             "model_calls": None, "cost": None, "direct_api_reference": "not_run; comparable accessible model not established",
             "decision": "inconclusive; retain baseline and gather authorized live timings plus independent human evaluation",
             "human_evaluation": "Use EVALUATION_PROTOCOL.md / ANNOTATION_GUIDE.md and scripts.evaluation with two independent qualified reviewers, adjudication and agreement; no labels supplied here."}
    runner.write(root / "execution-comparison.json", value)
    compact = {key: item for key, item in value.items() if key not in ("stages", "proposal_review_inventory", "execution_source_versions")}
    compact["stage_metrics"] = [{key: item for key, item in row.items() if key != "operations"} for row in stage_rows]
    compact["proposal_review_inventory_count"] = len(review_refs)
    compact["execution_source_versions_sha256"] = runner.object_hash(value.get("execution_source_versions"))
    compact["detail_report"] = "execution-comparison.json"
    compact["detail_report_sha256"] = runner.digest((root / "execution-comparison.json").read_bytes())
    compact["timing_scope"] = "CLI workflow/build wall time, including their host work; excludes harness artifact copying, manual/control commands and human waits. Fixtures are not real model timing."
    runner.write(root / "execution-comparison.compact.json", compact)
    lines = ["# Agent execution comparison", "", "Decision: **inconclusive — retain baseline; gather more evidence**.", "",
             f"Mode: {value['mode']}; development only. Planned {value['planned']}, attempted {value['attempted']}, not run {value['not_run']}.", "",
             "Fixture timings measure software mechanics, not real model latency, accuracy, OCR, translation or hiring outcomes.", "",
             "Validated timing means existing host gates, not independent semantic correctness. Positive fixtures use explicitly synthetic approvals; human waiting is unmeasured.", "",
             "| Configuration / stage | Fresh operations | First-attempt contract validity | Validated n | Median validated seconds | p95 |", "| --- | ---: | --- | ---: | ---: | ---: |"]
    for row in stage_rows:
        validity, speed = row["first_attempt_contract_validity"], row["time_to_validated_output_seconds"]
        median = f"{speed['median']:.3f}" if speed["median"] is not None else "unmeasured"
        tail = f"{speed['p95']:.3f}" if speed["p95"] is not None else "unmeasured"
        lines.append(f"| {row['model']} / {row['reasoning']} / {row['execution']} / {row['stage']} | {row['fresh_generation_operations']} | {validity['numerator']}/{validity['denominator']} | {speed['n']} | {median} | {tail} |")
    lines.extend(["", "JSON contains terminal outcomes, paired timing counts, retries, effective settings, usage where observable, and all retained proposals including stopped Adapt/Cover output. Variants share one synthetic source family; independent-family uncertainty intervals are not estimable.", "",
                  "Semantic accuracy, harmful omissions, unsupported additions, translation fidelity, human correction time and blinded preference are unmeasured. Source-reference validity and successful compilation are separate technical checks, not semantic correctness.", "",
                  "Proposed thresholds require a user decision before live comparisons. CLI invocations are capped by the existing authorization ledger; internal model requests and cost are not bounded by that invocation cap. Unknown telemetry is null, never zero."])
    (root / "execution-comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("plan")
    create.add_argument("--model", required=True)
    create.add_argument("--reasoning", required=True)
    create.add_argument("--repeats", type=int, default=2)
    create.add_argument("--lower-reasoning")
    create.add_argument("--reverse", action="store_true")
    create.add_argument("--live", action="store_true")
    create.add_argument("--output", type=Path, required=True)
    analyze = sub.add_parser("report")
    analyze.add_argument("run", type=Path)
    args = parser.parse_args()
    if args.action == "report":
        report(args.run)
        return
    if args.output.exists():
        parser.error("Choose a new plan file; do not overwrite a preregistered plan")
    value = plan(args.model, args.reasoning, args.repeats, lower_reasoning=args.lower_reasoning, reverse=args.reverse, fixture=not args.live)
    runner.write(args.output, value)
    runner.write(args.output.with_suffix(".proposal.json"), {"plan_sha256": runner.object_hash(value),
        "maximum_host_generation_dispatches_including_retries": sum(8 * c["max_attempts"] for c in value["cases"]),
        "maximum_internal_cli_model_requests": None, "expected_tokens_and_cost": None,
        "generation_access": "unverified; local CLI discovery is not successful generation",
        "malformed_output_control": "Injected only in fixture mode. Live mode observes natural structured-output validity without forcing a provider error.",
        "thresholds": THRESHOLDS, "authorization": "Separate plan-bound artifact with billing acknowledgment, explicit max_requests and future expiry; no authorization created."})
    print(runner.object_hash(value))


if __name__ == "__main__":
    main()
