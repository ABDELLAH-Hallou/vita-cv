"""Issue #36: cross-stage consistency controls, not a same-prompt variance estimate."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step
from vita.helpers import assessment, evaluation, llm, requirements
from vita.helpers.candidate_evidence import capture_candidate_sources, digest, stable_hash
from vita.helpers.job_extraction import prepare_job
from vita.helpers.pipeline_config import STAGE_PREFIXES, load_pipeline_settings
from vita.helpers.structured import json_text, parse_json, write_artifact

JD = "Python production experience is required.\nSQL is preferred.\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for prefix in STAGE_PREFIXES.values():
        for suffix in ("PROVIDER", "MODEL"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    monkeypatch.setenv("VITA_REQUIREMENTS_DIR", str(tmp_path / "requirements"))
    monkeypatch.setenv("ANALYSIS_PROVIDER", "openai")
    monkeypatch.setenv("ANALYSIS_MODEL", "judge-v1")
    monkeypatch.setenv("OPENAI_API_KEY", "SECRET_MUST_NOT_BE_RECORDED")
    Path(".vita").mkdir()
    Path("sections").mkdir()
    Path("main.tex").write_text("Python engineer\n\\input{sections/project}\n", encoding="utf-8")
    Path("sections/project.tex").write_text("Built SQL pipelines.\n", encoding="utf-8")
    Path("job.md").write_text(JD, encoding="utf-8")
    configure()
    approve()
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=AssertionError("No real providers")))
    return tmp_path


def configure(**updates):
    path = Path(".vita/extensions.json")
    content = parse_json(path.read_text(encoding="utf-8")) if path.exists() else {
        "llm_providers": {"openai": {"model": "judge-v1", "reasoning_effort": "low"}}}
    content["llm_providers"]["openai"].update(updates)
    write_artifact(path, json_text(content))


def approve(raw=JD):
    proposal = {"schema_version": 1, "items": [
        {"job_id": "job-1", "key": key, "text": text, "kind": "capability", "category": "hard_skills",
         "classification": classification, "ambiguity": "",
         "source_refs": [{"job_id": "job-1", "line_start": line, "line_end": line,
                          "quote": raw.splitlines()[line - 1]}]}
        for key, text, classification, line in (("python", "Python production experience", "required", 1),
                                               ("sql", "SQL", "preferred", 2))
    ]}
    doc = requirements.save_revision(requirements.compile_revision(proposal, raw))
    return requirements.approve_revision(doc["revision"], raw)


def read(name):
    return parse_json(Path(f".vita/results/{name}.json").read_text(encoding="utf-8"))


def judge(monkeypatch, evaluation_report, *, statuses=("partial", "missing"), on_call=None):
    """Synthetic adapter acknowledges the actual resolved route like the built-ins."""
    grading = list(statuses)

    def generate(system, prompt, **options):
        session = options.get("session")
        if session is not None:
            provider, model, config, _ = session["resolved"]
            session["route"] = {"provider": provider, "model": model or None,
                                "reasoning_effort": config.get("reasoning_effort")}
            session["mode"] = "native_schema" if "response_schema" in options else "validated_prompt"
        if "ADDITIONAL QUALITATIVE COMMENTARY ONLY" in prompt:
            return "Overall score is 90%. Reduced costs by 40%. Use shorter paragraphs."
        snapshot, _ = json.JSONDecoder().raw_decode(prompt.split(
            "CAPTURED CANDIDATE SOURCES (the only eligible assessment evidence):\n", 1)[1].lstrip())
        units = requirements.active_requirements(Path("job.md").read_text(encoding="utf-8"))["requirements"]
        report = evaluation_report()
        criteria = []
        for unit in units:
            index = 0 if unit["key"] == "python" else 1
            source = next(s for s in snapshot["sources"] if s["path"] == ("main.tex" if index == 0 else "sections/project.tex"))
            quote = "Python engineer" if index == 0 else "Built SQL pipelines."
            status = grading[index]
            criteria.append({**{key: unit[key] for key in evaluation.TAXONOMY_FIELDS},
                             "status": status, "evidence": quote if status != "missing" else "",
                             "feedback": "Check the scope of documented experience.",
                             "evidence_kind": "direct" if status != "missing" else "none",
                             "evidence_refs": [{"source_id": source["id"], "quote": quote,
                                                "line_start": 1, "line_end": 1}] if status != "missing" else []})
        report["metrics"]["criteria"] = criteria
        if on_call:
            on_call()
        return json_text(report)

    provider = Mock(side_effect=generate)
    provider.grading = grading
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    return provider


def test_paired_unchanged_control_reuses_identical_assessment(project, monkeypatch, evaluation_report):
    provider = judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    before = read("analysis")
    assert ai_step.run("review", auto=True)
    after = read("review")
    assert provider.call_count == 1
    assert before["metrics"] == after["metrics"]
    assert before["overall_score"] == after["overall_score"]
    assert before["metadata"]["assessment"] == after["metadata"]["assessment"]
    assert after["metadata"]["assessment_execution"]["mode"] == "reused"
    assert after["metadata"]["assessment_execution"]["origin_id"] == before["metadata"]["assessment_execution"]["id"]
    assert after["assessment_comparison"]["kind"] == "unchanged_reused"
    assert read("delta")["overall_score"]["delta"] == 0
    assert read("review.outcome")["attempts"] == []
    assert ai_step.run("analyze", auto=True)
    assert ai_step.run("review", auto=True)
    assert provider.call_count == 1
    assert read("review")["metadata"]["assessment_execution"]["origin_id"] == before["metadata"]["assessment_execution"]["id"]
    serialized = json_text(after)
    assert "SECRET_MUST_NOT_BE_RECORDED" not in serialized
    for field in ("source_sha256", "cv_sha256", "job_sha256", "criteria_sha256", "provider", "model",
                  "reasoning_effort", "prompt_sha256", "schema_sha256", "judge_sha256", "host_sha256"):
        assert field in after["metadata"]["assessment"]


def test_forced_control_uses_identical_judge_payload_and_never_claims_tailoring(project, monkeypatch, evaluation_report):
    provider = judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    provider.grading[0] = "matched"
    assert ai_step.run("review", auto=True, reassess=True)
    assert provider.call_count == 2
    assert provider.call_args_list[0].args == provider.call_args_list[1].args
    after = read("review")
    assert after["overall_score"] != read("analysis")["overall_score"]
    assert after["assessment_comparison"]["kind"] == "unchanged_reassessment"
    assert after["assessment_comparison"]["cv_sources"] == "unchanged"
    assert "not evidence that tailoring caused an improvement" in after["executive_summary"]
    assert "CV source content is unchanged" in Path(".vita/results/delta.md").read_text(encoding="utf-8")
    # Default Review still prefers the identical unchanged initial assessment.
    assert ai_step.run("review", auto=True)
    assert provider.call_count == 2
    assert read("review")["overall_score"] == read("analysis")["overall_score"]


@pytest.mark.parametrize("path", ["main.tex", "sections/project.tex"])
def test_actual_cv_edits_require_new_assessment_with_same_criteria(project, monkeypatch, evaluation_report, path):
    provider = judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    before = read("analysis")
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write("Added a concrete production achievement.\n")
    provider.grading[0] = "matched"
    assert ai_step.run("review", auto=True)
    after = read("review")
    assert provider.call_count == 2
    assert evaluation.taxonomy(before) == evaluation.taxonomy(after)
    assert after["metrics"]["weighted_available"] == before["metrics"]["weighted_available"]
    assert after["assessment_comparison"]["kind"] == "cv_changed"
    assert after["assessment_comparison"]["source_changes"][0]["path"] == path
    assert read("delta")["evidence_changes"]


@pytest.mark.parametrize("change", ["provider", "model", "reasoning", "judge", "schema", "host", "date", "format"])
def test_configuration_changes_invalidate_reuse_without_implying_cv_edits(project, monkeypatch, evaluation_report, change):
    provider = judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    if change == "provider":
        monkeypatch.setenv("REVIEW_PROVIDER", "openrouter")
        monkeypatch.setenv("REVIEW_MODEL", "vendor/judge")
    elif change == "model":
        monkeypatch.setenv("REVIEW_MODEL", "judge-v2")
    elif change == "reasoning":
        configure(reasoning_effort="high")
    elif change == "judge":
        Path(".vita/skills/assess").mkdir(parents=True)
        Path(".vita/skills/assess/precision.md").write_text("Check duration explicitly.", encoding="utf-8")
    elif change == "schema":
        schema = copy.deepcopy(assessment.EVALUATION_OUTPUT_SCHEMA)
        schema["description"] = "Updated host contract"
        monkeypatch.setattr(assessment, "EVALUATION_OUTPUT_SCHEMA", schema)
    elif change == "host":
        monkeypatch.setattr(assessment, "host_fingerprint", lambda: "new-host-version")
    elif change == "date":
        monkeypatch.setattr(assessment, "current_date_instruction", lambda: "A different assessment date context")
    else:
        configure(structured_output="off")
    assert ai_step.run("review", auto=True)
    after = read("review")
    assert provider.call_count == 2
    assert after["metadata"]["assessment"]["key"] != read("analysis")["metadata"]["assessment"]["key"]
    assert after["assessment_comparison"]["cv_sources"] == "unchanged"
    assert after["assessment_comparison"]["configuration_changes"]
    assert "not evidence that tailoring caused an improvement" in after["executive_summary"]


@pytest.mark.parametrize("fault", ["malformed", "key", "checksum", "source", "criteria", "job"])
def test_stale_or_corrupt_cache_is_not_reused(project, monkeypatch, evaluation_report, fault):
    provider = judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    Path(".vita/results/analysis.json").unlink()
    path = next(assessment.CACHE.glob("*.json"))
    envelope = parse_json(path.read_text(encoding="utf-8"))
    if fault == "malformed":
        path.write_text("not JSON", encoding="utf-8")
    else:
        if fault == "key":
            envelope["key"] = "wrong"
        elif fault == "checksum":
            envelope["report"]["metrics"]["criteria"][0]["status"] = "matched"
        elif fault == "source":
            envelope["report"]["metadata"]["candidate_snapshot"]["sources"][0]["content"] += "Fake employer"
            envelope["report_sha256"] = stable_hash(envelope["report"])
        elif fault == "job":
            envelope["report"]["metadata"]["job_sha256"] = "wrong-job"
            envelope["report_sha256"] = stable_hash(envelope["report"])
        else:
            envelope["report"]["metrics"]["criteria"][0]["criterion"] = "Easier requirement"
            envelope["report_sha256"] = stable_hash(envelope["report"])
        write_artifact(path, json_text(envelope))
    assert ai_step.run("review", auto=True)
    assert provider.call_count == 2


def test_content_addressed_cache_can_reuse_without_mutable_baseline(project, monkeypatch, evaluation_report):
    provider = judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    Path(".vita/results/analysis.json").unlink()
    assert ai_step.run("review", auto=True)
    assert provider.call_count == 1
    assert read("review")["comparison"]["status"] == "unavailable"
    assert read("review")["metadata"]["assessment_execution"]["mode"] == "reused"


def test_changed_job_revision_invalidates_old_assessment_cache(project, monkeypatch, evaluation_report):
    provider = judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    old = read("analysis")
    raw = JD + "Clarification about the role.\n"
    Path("job.md").write_text(raw, encoding="utf-8")
    assert not ai_step.run("review", auto=True)
    assert provider.call_count == 1
    approve(raw)
    assert ai_step.run("review", auto=True)
    assert provider.call_count == 2
    assert read("review")["comparison"]["status"] == "unavailable"
    assert read("review")["metadata"]["assessment"]["key"] != old["metadata"]["assessment"]["key"]


def test_stale_capture_is_marked_and_never_cached(project, monkeypatch, evaluation_report):
    provider = judge(monkeypatch, evaluation_report, on_call=lambda: Path("main.tex").write_text("Changed CV", encoding="utf-8"))
    assert ai_step.run("analyze", auto=True)
    assert read("analysis")["metadata"]["candidate_capture_status"] == "stale"
    assert not list(assessment.CACHE.glob("*.json"))
    assert provider.call_count == 1


def test_verified_knowledge_changes_are_not_labelled_cv_tailoring(project, monkeypatch, evaluation_report):
    def knowledge(text):
        Path(".vita/cv.yaml").write_text(text, encoding="utf-8")
        write_artifact(Path(".vita/cv-verified.json"), json_text({"schema_version": 1, "source_sha256": digest(text),
                                                               "verified_spans": [{"line_start": 1, "line_end": 1}]}))
    knowledge("Verified migration achievement\n")
    provider = judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    knowledge("Verified additional achievement\n")
    assert ai_step.run("review", auto=True)
    comparison = read("review")["assessment_comparison"]
    assert provider.call_count == 2
    assert comparison["cv_sources"] == "unchanged" and comparison["candidate_evidence"] == "changed"
    assert comparison["kind"] == "evidence_changed"


def test_additional_qualitative_review_is_separate_and_cannot_change_scores(project, monkeypatch, evaluation_report):
    provider = judge(monkeypatch, evaluation_report)
    Path(".vita/skills/review").mkdir(parents=True)
    Path(".vita/skills/review/style.md").write_text("REVIEW_ONLY_STYLE", encoding="utf-8")
    assert ai_step.run("analyze", auto=True)
    before = read("analysis")
    assert ai_step.run("review", auto=True, qualitative=True)
    assert provider.call_count == 2  # The score is reused; only writing commentary calls the provider.
    assert "REVIEW_ONLY_STYLE" not in " ".join(provider.call_args_list[0].args)
    assert "REVIEW_ONLY_STYLE" in provider.call_args.args[0]
    assert read("review")["metrics"] == before["metrics"]
    commentary = read("review-qualitative")
    assert "90%" not in commentary["commentary"] and "40%" in commentary["commentary"]
    assert commentary["model"] == "judge-v1"
    assert commentary["assessment_execution_id"] == read("review")["metadata"]["assessment_execution"]["id"]


def test_generated_stages_embed_identical_shared_payload_with_unreported_external_route(project, monkeypatch):
    provider = Mock(side_effect=AssertionError("Generated mode must not call a provider"))
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("analyze")
    a = Path(".vita/prompts/analyze.md").read_text(encoding="utf-8")
    assert ai_step.run("review")
    b = Path(".vita/prompts/review.md").read_text(encoding="utf-8")
    assert a.split("==== SHARED ASSESSMENT SYSTEM ====", 1)[1] == b.split("==== SHARED ASSESSMENT SYSTEM ====", 1)[1]
    assert "external_unreported" in a and "schema_sha256" in a
    assert "SECRET_MUST_NOT_BE_RECORDED" not in a + b
    provider.assert_not_called()


def test_unreported_inherited_codex_settings_disable_exact_input_reuse(project, monkeypatch, evaluation_report):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "codex")
    monkeypatch.delenv("ANALYSIS_MODEL")
    write_artifact(Path(".vita/extensions.json"), json_text({"llm_providers": {"codex": {"model": ""}}}))
    provider = judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    assert ai_step.run("review", auto=True)
    assert provider.call_count == 2
    assert read("review")["metadata"]["assessment"]["route_source"] == "inherited_unreported"
    assert "runtime_identity_unreported" in read("review")["assessment_comparison"]["configuration_changes"]
    assert read("review")["assessment_comparison"]["kind"] == "unchanged_reassessment"


def test_legacy_reports_cannot_claim_an_edit_caused_a_score_difference(project, evaluation_report):
    before = evaluation_report("partial")
    before["metadata"] = {"job_sha256": "j", "context_sha256": "c", "criteria_sha256": "unused",
                          "rubric_version": "weighted-criteria-v1"}
    after = evaluation_report("matched")
    comparison = evaluation.assessment_comparison(before, after)
    assert comparison["kind"] == "not_recorded"
    assert "no tailoring attribution" in comparison["description"]


def test_shared_helper_contract_does_not_depend_on_stage(project):
    job = prepare_job(load_pipeline_settings(), auto=False)
    sources = capture_candidate_sources()
    assert evaluation.evaluation_instruction("analyze", job, sources=sources) == evaluation.evaluation_instruction("review", job, sources=sources)


def test_unreported_adapter_records_requested_route_without_claiming_actual_model(project, monkeypatch, evaluation_report):
    provider = judge(monkeypatch, evaluation_report)
    original = provider.side_effect

    def unreported(system, prompt, **options):
        response = original(system, prompt, **options)
        options["session"].pop("route", None)
        return response

    provider.side_effect = unreported
    assert ai_step.run("analyze", auto=True)
    recorded = read("analysis")["metadata"]["assessment"]
    assert recorded["provider"] is None and recorded["model"] is None
    assert recorded["requested_provider"] == "openai" and recorded["requested_model"] == "judge-v1"
    assert recorded["route_source"] == "external_unreported"
    assert not list(assessment.CACHE.glob("*.json"))


def test_effective_route_is_frozen_between_cache_lookup_and_generation(project, monkeypatch):
    session = llm.prepare_session("openai", "judge-v1")
    configure(model="changed-later", reasoning_effort="high")
    call = Mock(return_value="{}")
    monkeypatch.setattr(llm, "_call_openai", call)
    assert llm.generate("system", "prompt", session=session) == "{}"
    assert call.call_args.args[3] == "judge-v1"
    assert call.call_args.kwargs["reasoning_effort"] == "low"
    assert session["route"] == {"provider": "openai", "model": "judge-v1", "reasoning_effort": "low"}


def test_corrupt_source_snapshot_cannot_become_a_baseline(project, monkeypatch, evaluation_report):
    judge(monkeypatch, evaluation_report)
    assert ai_step.run("analyze", auto=True)
    report = read("analysis")
    report["metadata"]["candidate_snapshot"]["sources"][0]["content"] += "Uncaptured employer"
    write_artifact(Path(".vita/results/analysis.json"), json_text(report))
    job = prepare_job(load_pipeline_settings(), auto=False)
    assert evaluation.load_baseline(job) is None


@pytest.mark.parametrize("claim", ["Tailoring yielded a 5-point gain.", "Adaptation improved your score.",
                                   "CV edits resulted in 12 extra points."])
def test_model_tailoring_attribution_is_removed_but_achievements_remain(claim):
    from vita.helpers.assessment_narrative import qualitative_text
    text = qualitative_text(claim + " Reduced costs by 40%.")
    assert "40%" in text
    assert "Tailoring" not in text and "Adaptation" not in text and "CV edits" not in text


def test_cli_reassessment_and_separate_commentary_flags(project, monkeypatch, evaluation_report):
    provider = judge(monkeypatch, evaluation_report)
    monkeypatch.setattr(sys, "argv", ["vita", "analyze", "--auto"])
    main()
    monkeypatch.setattr(sys, "argv", ["vita", "review", "--auto", "--reassess", "--qualitative"])
    main()
    assert provider.call_count == 3
    assert read("review")["metadata"]["assessment_execution"]["mode"] == "reassessment"
    assert read("review-qualitative")["assessment_key"] == read("review")["metadata"]["assessment"]["key"]
