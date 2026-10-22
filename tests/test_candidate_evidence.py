"""Issue #42: verify source support without pretending to verify qualifications."""

import copy
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.commands import ai_step
from vita.helpers import evaluation
from vita.helpers.candidate_evidence import capture_candidate_sources, digest
from vita.helpers.job_extraction import prepare_job
from vita.helpers.pipeline_config import load_pipeline_settings
from vita.helpers.structured import EVALUATION_OUTPUT_SCHEMA, json_text, parse_json, write_artifact


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    Path(".vita").mkdir()
    Path("sections").mkdir()
    Path("main.tex").write_text("Candidate CV\nPython engineer\n\\input{sections/work}\n", encoding="utf-8")
    Path("sections/work.tex").write_text("Built legitimate data pipelines.\nReduced costs by 40%.\n", encoding="utf-8")
    Path("job.md").write_text("Python engineer needed", encoding="utf-8")
    Path(".vita/cv.yaml").write_text("verified: Led data migration\nunconfirmed: PhD\n", encoding="utf-8")
    approve_knowledge()
    return prepare_job(load_pipeline_settings(), auto=False)


def approve_knowledge():
    write_artifact(Path(".vita/cv-verified.json"), json_text({
        "schema_version": 1, "source_sha256": digest(Path(".vita/cv.yaml").read_text(encoding="utf-8")),
        "verified_spans": [{"line_start": 1, "line_end": 1}],
    }))


def response(evaluation_report, snapshot, *, path="main.tex", quote="Python engineer", start=2, end=2,
             kind="direct", status="matched"):
    report = evaluation_report(status)
    source = next(source for source in snapshot["sources"] if source["path"] == path)
    report["metrics"]["criteria"][0].update(
        evidence=quote, evidence_kind=kind,
        evidence_refs=[{"source_id": source["id"], "quote": quote, "line_start": start, "line_end": end}],
    )
    return report


def criterion(report):
    return report["metrics"]["criteria"][0]


def finish(model, job, sources=None, **kwargs):
    return evaluation.finalize(json_text(model), job, sources=sources, **kwargs)


@pytest.mark.parametrize("path,quote,start,end", [
    ("main.tex", "Python engineer", 2, 2),
    ("main.tex", "Python engineer", None, None),
    ("sections/work.tex", "Built legitimate data pipelines.", 1, 1),
    ("sections/work.tex", "Built legitimate data pipelines.\nReduced costs by 40%.", 1, 2),
    (".vita/cv.yaml", "Led data migration", 1, 1),
    (".vita/cv.yaml", "Led data migration", None, None),
])
def test_legitimate_main_include_and_verified_knowledge(project, evaluation_report, path, quote, start, end):
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources, path=path, quote=quote, start=start, end=end)
    report = finish(model, project, sources)
    assert criterion(report)["evidence_verification"]["status"] == "verified"
    assert criterion(report)["status"] == "matched"
    md = evaluation.render_report(report, "Evidence")
    assert "real-world employment" in md and "verified / direct" in md
    assert evaluation.markdown_text(path) in md
    assert criterion(model).get("evidence_verification") is None


def test_issue42_fictional_employer_negative_control_then_legitimate_rerun(project, evaluation_report):
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources)
    legitimate = finish(model, project, sources)
    assert criterion(legitimate)["evidence_verification"]["status"] == "verified"
    # Exactly the issue's mutation: valid report, replace only the evidence string.
    fictional = copy.deepcopy(legitimate)
    criterion(fictional)["evidence"] = "Built BenchmarkNebula at FictionalEmployer"
    forged = finish(fictional, project, sources)
    assert criterion(forged)["evidence_verification"]["status"] == "unverified"
    assert "must equal" in criterion(forged)["evidence_verification"]["reason"]
    assert "unverified evidence" in forged["executive_summary"]
    evaluation.save_evaluation("analyze", forged)
    saved = parse_json(Path(".vita/results/analysis.json").read_text(encoding="utf-8"))
    assert criterion(saved)["evidence_verification"]["status"] == "unverified"
    assert "unverified / direct" in Path(".vita/results/analysis.md").read_text(encoding="utf-8")
    rerun = finish(model, project, sources)
    assert criterion(rerun)["evidence_verification"]["status"] == "verified"


@pytest.mark.parametrize("fault,reason", [
    ("fictional_quote", "absent"), ("unknown_source", "Unknown or stale"),
    ("out_of_bounds", "out of bounds"), ("reversed", "out of bounds"),
    ("half_span", "incomplete"), ("wrong_span", "absent"),
    ("unverified_knowledge", "outside verified"), ("unverified_quote_only", "absent"),
    ("no_refs", "No captured source"), ("unspecified", "direct support versus inference"),
])
def test_unsupported_evidence_is_explicitly_unverified(project, evaluation_report, fault, reason):
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources)
    item = criterion(model)
    ref = item["evidence_refs"][0]
    if fault == "fictional_quote":
        item["evidence"] = ref["quote"] = "Built BenchmarkNebula at FictionalEmployer"
    elif fault == "unknown_source":
        ref["source_id"] = "job.md"
    elif fault == "out_of_bounds":
        ref["line_end"] = 999
    elif fault == "reversed":
        ref.update(line_start=3, line_end=2)
    elif fault == "half_span":
        ref["line_start"] = None
    elif fault == "wrong_span":
        ref.update(line_start=1, line_end=1)
    elif fault.startswith("unverified_"):
        model = response(evaluation_report, sources, path=".vita/cv.yaml", quote="PhD", start=2, end=2)
        if fault == "unverified_quote_only":
            criterion(model)["evidence_refs"][0].update(line_start=None, line_end=None)
    elif fault == "no_refs":
        item["evidence_refs"] = []
    else:
        item["evidence_kind"] = "unspecified"
    item = criterion(finish(model, project, sources))
    assert item["evidence_verification"]["status"] == "unverified"
    assert reason in item["evidence_verification"]["reason"]


@pytest.mark.parametrize("change", ["main", "include", "knowledge", "approval", "include_graph"])
def test_sources_changed_after_capture_are_stale(project, evaluation_report, change):
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources)
    paths = {"main": "main.tex", "include": "sections/work.tex", "knowledge": ".vita/cv.yaml"}
    if change in paths:
        with Path(paths[change]).open("a", encoding="utf-8") as stream:
            stream.write("\nChanged after provider prompt")
    elif change == "approval":
        Path(".vita/cv-verified.json").unlink()
    else:
        Path("main.tex").write_text("Python engineer\n", encoding="utf-8")
    report = finish(model, project, sources)
    assert report["metadata"]["candidate_capture_status"] == "stale"
    assert "changed during assessment" in criterion(report)["evidence_verification"]["reason"]
    assert criterion(evaluation.canonical_report(report))["evidence_verification"]["status"] == "unverified"


def test_old_source_id_does_not_bind_to_updated_source(project, evaluation_report):
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources)
    Path("main.tex").write_text("Python engineer\nNew version", encoding="utf-8")
    report = finish(model, project)  # Standalone finalize captures the new sources.
    assert "Unknown or stale" in criterion(report)["evidence_verification"]["reason"]


def test_quotes_are_exact_even_with_unicode_separators_and_blank_lines(project, evaluation_report):
    Path("main.tex").write_bytes("Header\r\n\r\nPython\u2028engineer\r\n".encode("utf-8"))
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources, quote="Python\u2028engineer", start=3, end=3)
    assert criterion(finish(model, project, sources))["evidence_verification"]["status"] == "verified"
    criterion(model)["evidence"] = criterion(model)["evidence_refs"][0]["quote"] = "Python\nengineer"
    assert criterion(finish(model, project, sources))["evidence_verification"]["status"] == "unverified"


def test_all_references_must_verify_not_just_one(project, evaluation_report):
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources)
    item = criterion(model)
    item["evidence_refs"].append({**item["evidence_refs"][0], "quote": "FictionalEmployer"})
    item["evidence"] += "\nFictionalEmployer"
    assert criterion(finish(model, project, sources))["evidence_verification"]["status"] == "unverified"


def test_multiple_legitimate_references_verify_together(project, evaluation_report):
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources)
    item = criterion(model)
    source = next(source for source in sources["sources"] if source["path"] == "sections/work.tex")
    item["evidence_refs"].append({"source_id": source["id"], "quote": "Reduced costs by 40%.",
                                  "line_start": 2, "line_end": 2})
    item["evidence"] += "\nReduced costs by 40%."
    assert criterion(finish(model, project, sources))["evidence_verification"]["status"] == "verified"


@pytest.mark.parametrize("kind,status,expected,score", [
    ("direct", "partial", "partial", 50),
    ("inference", "matched", "partial", 50),
    ("inference", "partial", "partial", 50),
])
def test_text_presence_never_promotes_partial_or_inferred_support(project, evaluation_report, kind, status, expected, score):
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources, kind=kind, status=status)
    criterion(model)["criterion"] = "Five years of production Python leadership"
    report = finish(model, project, sources)
    assert criterion(report)["evidence_verification"]["status"] == "verified"
    assert criterion(report)["status"] == expected
    assert report["overall_score"] == score


def test_missing_has_no_evidence_claim(project, evaluation_report):
    sources = capture_candidate_sources()
    model = evaluation_report("missing")
    criterion(model).update(evidence_kind="none", evidence_refs=[])
    report = finish(model, project, sources)
    assert criterion(report)["evidence_verification"]["status"] == "not_applicable"


def test_legacy_remains_readable_and_forged_verification_is_ignored(project, evaluation_report):
    legacy = evaluation_report()
    criterion(legacy)["evidence_verification"] = {"status": "verified", "reason": "Trust me"}
    result = evaluation.canonical_report(legacy)
    assert criterion(result)["evidence_verification"]["status"] == "not_recorded"
    assert result["overall_score"] == 100  # Preserve legacy model-judged scores with a visible warning.
    assert "Legacy report" in evaluation.render_report(result, "Legacy")
    assert criterion(finish(legacy, project))["evidence_verification"]["status"] == "unverified"


def test_snapshot_integrity_is_rechecked_on_render(project, evaluation_report):
    sources = capture_candidate_sources()
    report = finish(response(evaluation_report, sources), project, sources)
    report["metadata"]["candidate_snapshot"]["sources"][0]["content"] += "Injected employer"
    assert criterion(evaluation.canonical_report(report))["evidence_verification"]["status"] == "unverified"
    assert "integrity validation" in evaluation.render_report(report, "Tampered")


@pytest.mark.parametrize("fault", ["absent", "wrong_hash", "out_of_bounds", "malformed"])
def test_unverified_or_stale_knowledge_never_enters_eligible_sources(project, fault):
    if fault == "absent":
        Path(".vita/cv-verified.json").unlink()
    elif fault == "malformed":
        Path(".vita/cv-verified.json").write_text("not JSON", encoding="utf-8")
    else:
        approval = parse_json(Path(".vita/cv-verified.json").read_text(encoding="utf-8"))
        if fault == "wrong_hash":
            approval["source_sha256"] = "stale"
        else:
            approval["verified_spans"][0]["line_end"] = 999
        write_artifact(Path(".vita/cv-verified.json"), json_text(approval))
    assert all(source["kind"] != "verified_knowledge" for source in capture_candidate_sources()["sources"])


def test_literal_include_graph_and_configured_entry_only(project):
    Path("alternate.tex").write_text("Alternate CV\n\\input{sections/work}\n%\\input{ignored}\n\\input{\\dynamic}\n", encoding="utf-8")
    Path("ignored.tex").write_text("Fictional employer", encoding="utf-8")
    Path("sections/work.tex").write_text("True work\n\\input{alternate}\n", encoding="utf-8")
    write_artifact(Path(".vita/config.json"), json_text({"tex_entry": "alternate.tex"}))
    snapshot = capture_candidate_sources()
    assert {s["path"] for s in snapshot["sources"]} == {"alternate.tex", "sections/work.tex", ".vita/cv.yaml"}


@pytest.mark.parametrize("step", ["analyze", "review"])
def test_auto_and_generated_prompts_capture_same_sources(project, evaluation_report, monkeypatch, step):
    sources = capture_candidate_sources()
    model = response(evaluation_report, sources)
    provider = Mock(return_value=json_text(model))
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run(step, auto=False)
    generated = Path(f".vita/prompts/{step}.md").read_text(encoding="utf-8")
    assert ai_step.run(step, auto=True)
    automatic = provider.call_args.args[1]
    for text in (generated, automatic):
        assert "CAPTURED CANDIDATE SOURCES" in text
        assert sources["sources"][0]["id"] in text
        assert "direct, inference, or none" in text
        assert "presence does not prove complete criterion satisfaction" in text
    name = "analysis" if step == "analyze" else "review"
    report = parse_json(Path(f".vita/results/{name}.json").read_text(encoding="utf-8"))
    assert criterion(report)["evidence_verification"]["status"] == "verified"
    properties = EVALUATION_OUTPUT_SCHEMA["properties"]["metrics"]["properties"]["criteria"]["items"]["properties"]
    assert "evidence_refs" in properties and "evidence_verification" not in properties


def test_review_can_compare_new_cv_snapshot_without_relaxing_job_taxonomy_guards(project, evaluation_report):
    sources = capture_candidate_sources()
    before = finish(response(evaluation_report, sources, status="partial"), project, sources)
    evaluation.save_evaluation("analyze", before)
    Path("main.tex").write_text("New CV\nPython engineer\n", encoding="utf-8")
    current = capture_candidate_sources()
    loaded = evaluation.load_baseline(project)
    assert loaded is not None  # Baseline's older CV capture is legitimate history.
    after = finish(response(evaluation_report, current), project, current, baseline=loaded)
    assert evaluation.compute_delta(before, after)["overall_score"]["delta"] == 50
    wrong_job = copy.deepcopy(after)
    wrong_job["metadata"]["job_sha256"] = "different-job"
    with pytest.raises(ValueError, match="different jobs"):
        evaluation.compute_delta(before, wrong_job)
    altered = response(evaluation_report, current)
    criterion(altered)["criterion"] = "Altered taxonomy"
    with pytest.raises(ValueError, match="baseline criteria"):
        finish(altered, project, current, baseline=loaded)
