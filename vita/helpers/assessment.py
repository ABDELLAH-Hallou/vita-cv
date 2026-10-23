"""One scoring judge, exact-input reuse, and separate optional writing commentary."""

import copy
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

from vita.helpers import llm
from vita.helpers.assessment_narrative import qualitative_text
from vita.helpers.candidate_evidence import (
    capture_candidate_sources,
    stable_hash,
    validate_snapshot,
)
from vita.helpers.context_builder import (
    build_system_context,
    current_date_instruction,
    multi_job_instruction,
)
from vita.helpers.evaluation import (
    compute_delta,
    evaluation_instruction,
    finalize,
    load_baseline,
    save_delta,
    save_evaluation,
    taxonomy,
    validate_evaluation,
)
from vita.helpers.job_extraction import fingerprint, read_job
from vita.helpers.skills import skill_context
from vita.helpers.structured import (
    EVALUATION_OUTPUT_SCHEMA,
    generation_schema,
    json_text,
    parse_json,
    write_artifact,
)
from vita.helpers.structured_output import (
    MAX_ATTEMPTS,
    StructuredOutputError,
    accepts_keyword,
    run_structured,
)

ASSETS = Path(__file__).parent.parent / "assets"
RESULTS = Path(".vita/results")
CACHE = RESULTS / "assessments"


@dataclass
class AssessmentRequest:
    system: str
    prompt: str
    provenance: dict
    sources: dict
    session: dict
    route: dict
    cacheable: bool


def host_fingerprint() -> str:
    names = ("assessment", "evaluation", "candidate_evidence", "requirements", "structured", "llm",
             "structured_output", "assessment_narrative", "context_builder", "skills", "pipeline_config")
    return stable_hash({name: Path(__file__).with_name(name + ".py").read_text(encoding="utf-8") for name in names})


def cv_fingerprint(sources: dict) -> str:
    return stable_hash({s["path"]: s["sha256"] for s in sources["sources"] if s["kind"] in ("cv", "include")})


def rekey(provenance: dict) -> dict:
    result = {key: value for key, value in provenance.items() if key != "key"}
    result["key"] = stable_hash(result)
    return result


def prepare_assessment(job, *, route: dict | None = None, baseline: dict | None = None,
                       sources: dict | None = None, external: bool = False) -> AssessmentRequest:
    """Freeze a shared payload. External-assistant identity is explicitly unreported.

    The returned session is private (it contains credentials). Only provenance
    is serializable. Inherited Codex model/reasoning cannot safely key reuse.
    """
    sources = sources if sources is not None else capture_candidate_sources()
    validate_snapshot(sources)
    route = route or {"provider": None}
    session = {} if external else llm.prepare_session(**route)
    if external:
        provider = model = reasoning = None
        config = {}
        route_source, reasoning_source = "external_unreported", "external_unreported"
    else:
        provider, model, config, _ = session["resolved"]
        reasoning = config.get("reasoning_effort") if provider in ("openai", "openrouter", "codex") else None
        inherited = provider == "codex" and (not model or reasoning is None)
        route_source = "inherited_unreported" if inherited else "resolved"
        reasoning_source = "configured" if reasoning is not None else (
            "cli_inherited_unreported" if provider == "codex" else "provider_default")
    judge = skill_context("assess")
    template = (ASSETS / "prompts/assess.md").read_text(encoding="utf-8")
    system = "You are VITA's documented-coverage assessment judge.\n" + current_date_instruction() + "\n" + judge
    # Neither stage, prior scores/statuses nor additional review advice is sent.
    prompt = template.replace("{{JOB_DESCRIPTION}}", job.text) + evaluation_instruction("assess", job, baseline, sources=sources)
    if len(job.ids) > 1:
        prompt += multi_job_instruction(len(job.ids))
    units = job.requirements["requirements"] if job.requirements is not None else (
        baseline["metrics"]["criteria"] if baseline else None)
    criteria_sha = fingerprint(json_text(taxonomy({"metrics": {"criteria": units}}))) if units is not None else "unlocked"
    provenance = rekey({
        "contract_version": "assessment-v1", "source_sha256": sources["sha256"], "cv_sha256": cv_fingerprint(sources),
        "job_sha256": job.source_sha256, "context_sha256": job.context_sha256, "criteria_sha256": criteria_sha,
        "requirements_revision": job.requirements["revision"] if job.requirements else None,
        "provider": provider, "model": model or None, "reasoning_effort": reasoning,
        "requested_provider": provider, "requested_model": model or None, "requested_reasoning_effort": reasoning,
        "reasoning_source": reasoning_source, "route_source": route_source,
        "config_sha256": stable_hash({"provider": provider, "model": model, "reasoning": reasoning,
                                      "structured_output": config.get("structured_output", "auto")}),
        "system_sha256": fingerprint(system), "prompt_sha256": fingerprint(prompt),
        "schema_sha256": stable_hash(EVALUATION_OUTPUT_SCHEMA),
        "generation_schema_sha256": stable_hash(generation_schema(EVALUATION_OUTPUT_SCHEMA)),
        "host_sha256": host_fingerprint(), "judge_sha256": fingerprint(template + "\n" + judge),
        "as_of_date": date.today().isoformat(),
    })
    cacheable = units is not None and route_source == "resolved" and any(s["kind"] == "cv" for s in sources["sources"])
    return AssessmentRequest(system, prompt, provenance, sources, session, route, cacheable)


def new_execution(mode: str, *, origin: str | None = None, session: dict | None = None) -> dict:
    session = session or {}
    request = session.get("request", {})
    return {"id": uuid.uuid4().hex, "mode": mode, "origin_id": origin,
            "created_at": datetime.now(timezone.utc).isoformat(), "attempts": request.get("attempt", 0),
            "request_sha256": request.get("prompt_sha256"),
            "output_mode": "cache" if mode == "reused" else session.get("mode", "external_unreported")}


def reusable(report: dict, request: AssessmentRequest, job) -> bool:
    try:
        validate_evaluation(report)
        metadata = report.get("metadata", {})
        if (not request.cacheable or metadata.get("assessment") != request.provenance
                or metadata.get("candidate_snapshot") != request.sources
                or metadata.get("candidate_capture_status") != "captured"
                or not metadata.get("assessment_execution", {}).get("id")
                or metadata.get("job_sha256") != job.source_sha256
                or metadata.get("context_sha256") != job.context_sha256
                or metadata.get("requirements_revision") != request.provenance["requirements_revision"]
                or metadata.get("criteria_sha256") != request.provenance["criteria_sha256"]
                or fingerprint(read_job()) != job.source_sha256
                or capture_candidate_sources(request.sources["entry"]) != request.sources):
            return False
        checked = finalize(json_text(report), job, sources=request.sources, assessment=request.provenance)
        if taxonomy(checked) != taxonomy(report) or checked["metrics"]["criteria"] != report["metrics"]["criteria"]:
            return False
        return all(item["evidence_verification"]["status"] in ("verified", "not_applicable")
                   for item in checked["metrics"]["criteria"])
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        return False


def cached_assessment(request: AssessmentRequest, job, baseline: dict | None) -> dict | None:
    # Prefer the initial assessment: an explicit fresh reassessment must not
    # replace an unchanged baseline's judgments during a subsequent default run.
    if baseline is not None and reusable(baseline, request, job):
        return baseline
    try:
        envelope = parse_json((CACHE / f"{request.provenance['key']}.json").read_text(encoding="utf-8"))
        if (set(envelope) == {"schema_version", "key", "report_sha256", "report"}
                and type(envelope["schema_version"]) is int and envelope["schema_version"] == 1
                and envelope["key"] == request.provenance["key"]
                and envelope["report_sha256"] == stable_hash(envelope["report"])
                and reusable(envelope["report"], request, job)):
            return envelope["report"]
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        # An optional cache miss/corruption never supplies candidate judgments.
        return None
    return None


def save_cached(report: dict, request: AssessmentRequest, job) -> None:
    if reusable(report, request, job):
        write_artifact(CACHE / f"{request.provenance['key']}.json", json_text({
            "schema_version": 1, "key": request.provenance["key"],
            "report_sha256": stable_hash(report), "report": report,
        }))


def reuse_outcome(step: str, report: dict) -> None:
    run_id = uuid.uuid4().hex
    execution = report["metadata"]["assessment_execution"]
    record = {"schema_version": 1, "run_id": run_id, "step": step, "status": "success",
              "max_attempts": MAX_ATTEMPTS, "attempts": [], "error": None, "recovered": False,
              "input_sha256": report["metadata"]["assessment"]["key"],
              "cache": {"status": "hit", "origin_id": execution["origin_id"]}}
    write_artifact(RESULTS / "attempts" / f"{step}-{run_id}.json", json_text(record))
    write_artifact(RESULTS / f"{step}.outcome.json", json_text(record))


def qualitative_prompt(step: str, request: AssessmentRequest) -> tuple[str, str]:
    task = (ASSETS / "prompts" / f"{step}.md").read_text(encoding="utf-8")
    system = build_system_context(task, step=step, resume_entry=request.sources["entry"], include_job=False)
    prompt = ("ADDITIONAL QUALITATIVE COMMENTARY ONLY. Do not calculate scores, change criterion judgments, "
              "or claim tailoring improved a score. Do not edit source files. Give concise writing feedback.\n"
              + task.replace("{{JOB_DESCRIPTION}}", read_job())
              + "\nIgnore task/skill instructions asking for numeric or structured scoring; the separate assessment is authoritative. "
              f"Output prose only. VITA saves it separately as {step}-qualitative.md with provenance in {step}-qualitative.json.")
    return system, prompt


def run_assessment(step: str, job, *, settings, resume_entry: str, generate, auto: bool,
                   provider: str | None = None, reassess: bool = False, qualitative: bool = False) -> bool:
    try:
        baseline = load_baseline(job)
        preview_job = job
        if not auto and settings.extraction_enabled and job.requirements is None:
            preview_job = replace(job, text="At execution time, read .vita/results/job.json and job.toon if their job hash matches; otherwise use raw job.md. Regenerate this judge payload with the current prepared context before execution.")
        request = prepare_assessment(preview_job, route=settings.route(step, provider).kwargs(), baseline=baseline,
                                     sources=capture_candidate_sources(resume_entry), external=not auto)
        if not auto:
            host = (
                f"HOST EXECUTION INSTRUCTIONS (outside the shared judge payload): stage={step}.\n"
                "At execution time prepare current sources and job context with prepare_job (using validated job.json/job.toon where available), "
                "then call prepare_assessment again. Never use a stale embedded snapshot. "
                "For configured API execution use run_assessment with auto=True; it validates/reuses identical-input assessments. "
                "For an external assistant, call prepare_assessment(job, external=True), generate ONLY from its system/prompt, "
                "and use vita.helpers.evaluation.finalize(response, job, baseline, "
                f"step='{step}', sources=request.sources, assessment=request.provenance, execution=new_execution('reassessment')). "
                "Use save_evaluation, compute_delta and save_delta to save JSON and Markdown. "
                "An external assistant's model/reasoning are unreported; do not claim the configured API was used. "
                "Such assessments are not eligible for automatic exact-input reuse.\n\n"
            )
            text = host + "PLANNED EXTERNAL PROVENANCE (runtime model unreported):\n" + json_text(request.provenance)
            text += "==== SHARED ASSESSMENT SYSTEM ====\n" + request.system + "\n==== SHARED ASSESSMENT JUDGE ====\n" + request.prompt
            if qualitative:
                system, prompt = qualitative_prompt(step, request)
                text += "\n==== OPTIONAL QUALITATIVE TASK (SEPARATE OUTPUT) ====\n" + system + "\n" + prompt
                text += (f"\nFor external execution save only .vita/results/{step}-qualitative.md and its separate "
                         "JSON provenance linked to the assessment key/execution. Never overwrite scoring reports with commentary.")
            write_artifact(Path(f".vita/prompts/{step}.md"), text)
            write_artifact(Path(".vita/current_prompt.md"), text)
            print(text)
            return True

        def save(report):
            delta = compute_delta(baseline, report) if step == "review" and baseline else None
            save_evaluation(step, report)
            if delta:
                save_delta(delta)
            else:
                for extension in ("json", "md"):
                    (RESULTS / f"delta.{extension}").unlink(missing_ok=True)

        cached = None if reassess else cached_assessment(request, job, baseline)
        if cached is not None:
            prior = cached["metadata"]["assessment_execution"]
            origin = prior.get("origin_id") or prior["id"]
            report = finalize(json_text(cached), job, baseline if step == "review" else None, step=step,
                              sources=request.sources, assessment=request.provenance,
                              execution=new_execution("reused", origin=origin))
            save(report)
            reuse_outcome(step, report)
            print(f"Reused identical-input assessment for {step}; no scoring provider call was made.")
        else:
            def finish(data):
                description = copy.deepcopy(request.provenance)
                actual = request.session.get("route")
                expected = {"provider": description["provider"], "model": description["model"],
                            "reasoning_effort": description["reasoning_effort"]}
                if actual != expected:
                    description["route_source"] = "external_unreported"
                    request.cacheable = False
                    description.update({key: (actual or {}).get(key) for key in expected})
                description = rekey(description)
                return finalize(json_text(data), job, baseline if step == "review" else None, step=step,
                                sources=request.sources, assessment=description,
                                execution=new_execution("reassessment" if reassess or baseline else "generated", session=request.session))

            report = run_structured(step=step, generate=generate, system=request.system, prompt=request.prompt,
                                    route=request.route, schema=EVALUATION_OUTPUT_SCHEMA,
                                    finalize=finish, save=save, session=request.session)
            try:
                save_cached(report, request, job)
            except OSError:
                print("Assessment saved; optional assessment cache could not be written.")
        if qualitative:
            system, prompt = qualitative_prompt(step, request)
            options = dict(request.route)
            if accepts_keyword(generate, "session"):
                options["session"] = request.session
            commentary = qualitative_text(generate(system, prompt, **options))
            actual = request.session.get("route", {})
            artifact = {"schema_version": 1, "assessment_key": report["metadata"]["assessment"]["key"],
                        "assessment_execution_id": report["metadata"]["assessment_execution"]["id"],
                        "source_sha256": request.sources["sha256"], "job_sha256": job.source_sha256,
                        "system_sha256": fingerprint(system), "prompt_sha256": fingerprint(prompt),
                        "provider": actual.get("provider"), "model": actual.get("model"),
                        "reasoning_effort": actual.get("reasoning_effort"),
                        "source_status": "captured" if capture_candidate_sources(resume_entry) == request.sources else "stale",
                        "commentary": commentary}
            write_artifact(RESULTS / f"{step}-qualitative.json", json_text(artifact))
            write_artifact(RESULTS / f"{step}-qualitative.md", "# Additional qualitative commentary\n\n"
                           "This separate writing review does not set assessment scores or comparisons.\n\n" + commentary)
        return True
    except (StructuredOutputError, ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(f"Could not prepare, validate or save {step} assessment: {exc}")
        return False
