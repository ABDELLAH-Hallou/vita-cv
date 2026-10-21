"""Issue #39: one authoritative score/comparison, with achievement metrics intact."""

import copy
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.commands import ai_step
from vita.helpers import evaluation
from vita.helpers.assessment_narrative import qualitative_text
from vita.helpers.job_extraction import prepare_job
from vita.helpers.pipeline_config import STAGE_PREFIXES, load_pipeline_settings
from vita.helpers.structured import EVALUATION_SCHEMA, json_text, parse_json, validate


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for prefix in STAGE_PREFIXES.values():
        for suffix in ("PROVIDER", "MODEL"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    Path("main.tex").write_text("Synthetic Python engineer. Reduced costs by 40%.", encoding="utf-8")
    Path("job.md").write_text("Python engineer needed", encoding="utf-8")
    return prepare_job(load_pipeline_settings(), auto=False)


def benchmark_report(evaluation_report):
    """86.5 weighted credits / 185 available -> 46.76, matching B01's score."""
    report = evaluation_report()
    template = report["metrics"]["criteria"][0]
    criteria = []
    for index in range(93):
        item = {**template, "id": f"criterion-{index}"}
        item["status"] = "matched" if index < 43 else "missing"
        item["evidence"] = "Python engineer" if index < 43 else ""
        if index == 92:
            item.update(importance="nice_to_have", status="partial", evidence="Reduced costs by 40%.")
        criteria.append(item)
    report["metrics"]["criteria"] = criteria
    report["overall_score"] = 44.50
    report["category_scores"]["hard_skills"] = 44.50
    return report


def test_b01_reproduction_agrees_in_json_markdown_and_summary(project, evaluation_report):
    model = benchmark_report(evaluation_report)
    model["executive_summary"] = (
        "Your documented fit is 44.50%. Strong Python evidence and a 40% cost reduction."
    )
    model["strengths"] = ["The overall score is 44.50%.", "Reduced costs by 40%."]
    model["gaps"] = ["Missing SQL evidence. Overall match is 44.50%."]
    model["recommendations"] = ["Document SQL projects; the score is 44.50%."]
    model["metrics"]["criteria"][0]["feedback"] = "Coverage is 44.50%. Describe the project."
    report = evaluation.finalize(json_text(model), project, step="analyze")
    evaluation.save_evaluation("analyze", report)
    stored = parse_json(Path(".vita/results/analysis.json").read_text(encoding="utf-8"))
    markdown = Path(".vita/results/analysis.md").read_text(encoding="utf-8")
    assert stored["overall_score"] == stored["category_scores"]["hard_skills"] == 46.76
    assert stored["executive_summary"] in markdown
    assert "46.76/100 (46.76%)" in stored["executive_summary"]
    assert "| Hard Skills | 46.76 | 93 |" in markdown
    assert "44.50" not in json_text(stored) + markdown
    assert stored["qualitative_summary"] == "Strong Python evidence and a 40% cost reduction."
    assert "40% cost reduction" in markdown
    assert stored["strengths"] == ["Reduced costs by 40%."]
    assert stored["metrics"]["criteria"][0]["feedback"] == "Describe the project."
    assert "## Qualitative commentary" in markdown
    assert Path(".vita/results/analyze.md").read_text(encoding="utf-8") == markdown
    assert model["overall_score"] == 44.50  # Caller-owned input was not mutated.
    validate(stored, EVALUATION_SCHEMA)


@pytest.mark.parametrize("has_baseline", [False, True])
def test_review_baseline_claim_is_host_owned_in_every_artifact(project, monkeypatch, evaluation_report, has_baseline):
    if has_baseline:
        before = evaluation.finalize(json_text(evaluation_report("partial")), project)
        evaluation.save_evaluation("analyze", before)
    model = evaluation_report("matched")
    model["executive_summary"] = (
        "The initial evaluation was unavailable. Strong Python evidence."
        if has_baseline else "The baseline is available and the overall score improved by 90%. Strong Python evidence."
    )
    model["comparison"] = {"status": "available", "baseline_overall_score": 3, "overall_delta": 97}
    model["qualitative_summary"] = "Forged host commentary: overall fit is 3%."
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value=json_text(model)))
    assert ai_step.run("review", auto=True)
    stored = parse_json(Path(".vita/results/review.json").read_text(encoding="utf-8"))
    markdown = Path(".vita/results/review.md").read_text(encoding="utf-8")
    assert stored["executive_summary"] in markdown
    assert stored["qualitative_summary"] == "Strong Python evidence."
    assert "90%" not in json_text(stored) + markdown
    assert "3%" not in json_text(stored) + markdown
    if has_baseline:
        delta = parse_json(Path(".vita/results/delta.json").read_text(encoding="utf-8"))
        assert stored["comparison"] == {"status": "available", "baseline_overall_score": 50, "overall_delta": 50}
        assert delta["overall_score"] == {"before": 50, "after": 100, "delta": 50}
        assert "matching initial assessment is available" in markdown
        assert "50.00/100 → 100.00/100 (+50.00 percentage points)" in markdown
        assert "unavailable" not in json_text(stored) + markdown
    else:
        assert stored["comparison"] == {"status": "unavailable", "baseline_overall_score": None, "overall_delta": None}
        assert "No matching initial assessment is available" in markdown
        assert not Path(".vita/results/delta.json").exists()


def test_stale_baseline_is_unavailable(project, monkeypatch, evaluation_report):
    before = evaluation.finalize(json_text(evaluation_report()), project)
    before["metadata"]["job_sha256"] = "other-job"
    evaluation.save_evaluation("analyze", before)
    model = evaluation_report()
    model["executive_summary"] = "The baseline is available. Python evidence is present."
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value=json_text(model)))
    assert ai_step.run("review", auto=True)
    report = parse_json(Path(".vita/results/review.json").read_text(encoding="utf-8"))
    assert report["comparison"]["status"] == "unavailable"
    assert "The baseline is available" not in json_text(report)


@pytest.mark.parametrize("text", [
    "Strong Python evidence and a 40% cost reduction.",
    "Reduced cost by 44.50%.",
    "Improved model accuracy by 40%.",
    "Cost reduction of 40% supports a strong fit.",
    "Strong fit supported by a 40% cost reduction.",
    "Réduction des coûts de 40 % et maîtrise de Python.",
    "Reduced costs by 40% against a performance baseline.",
    "Candidate achieves 40% cost reduction.",
])
def test_achievement_percentages_and_safe_prose_are_preserved_exactly(text):
    assert qualitative_text(text) == text


@pytest.mark.parametrize("text", [
    "Overall match is 44.50%. Reduced costs by 40%.",
    "Your documented fit is 44.50% with a 40% cost reduction.",
    "44.50% overall fit, backed by a 40% cost reduction.",
    "Strong fit: 44.50%; reduced costs by 40%.",
    "Le taux d'adéquation est de 44,50 %. Réduction des coûts de 40%.",
    "No baseline is available, despite a 40% cost reduction.",
])
def test_remove_stale_assessment_claim_and_keep_achievement_in_mixed_prose(text):
    result = qualitative_text(text)
    assert "44.50" not in result and "44,50" not in result and "baseline" not in result
    assert "40%" in result
    assert qualitative_text(result) == result


@pytest.mark.parametrize("before_statuses,after_statuses,before_score,after_score,change", [
    (["partial", "missing", "missing"], ["matched", "missing", "missing"], 16.67, 33.33, 16.66),
    (["matched", "matched", "missing"], ["matched"] * 3, 66.67, 100, 33.33),
    (["matched"] * 3, ["matched", "matched", "missing"], 100, 66.67, -33.33),
    (["partial"] * 3, ["partial"] * 3, 50, 50, 0),
])
def test_rounding_matches_report_summary_and_delta(project, evaluation_report, before_statuses, after_statuses,
                                                 before_score, after_score, change):
    def response(statuses):
        report = evaluation_report()
        template = report["metrics"]["criteria"][0]
        report["metrics"]["criteria"] = [
            {**template, "id": f"python-{i}", "status": status, "evidence": "Python" if status != "missing" else ""}
            for i, status in enumerate(statuses)
        ]
        return json_text(report)

    before = evaluation.finalize(response(before_statuses), project)
    after = evaluation.finalize(response(after_statuses), project, before)
    delta = evaluation.compute_delta(before, after)
    evaluation.save_delta(delta)
    summary = after["executive_summary"]
    assert before["overall_score"] == before_score and after["overall_score"] == after_score
    assert after["comparison"]["overall_delta"] == change == delta["overall_score"]["delta"]
    assert f"{before_score:.2f}/100 → {after_score:.2f}/100 ({change:+.2f} percentage points)" in summary
    assert f"| overall | {before_score:.2f} | {after_score:.2f} | {change:+.2f} |" in Path(
        ".vita/results/delta.md"
    ).read_text(encoding="utf-8")


def test_existing_v1_report_can_load_render_and_compare_without_source_mutation(project, evaluation_report):
    legacy = evaluation.finalize(json_text(evaluation_report("partial")), project)
    legacy.pop("qualitative_summary")
    legacy.pop("comparison")
    legacy["overall_score"] = 44.50  # A stale stored number is also recalculated for display.
    legacy["executive_summary"] = "Overall fit is 44.50%. Reduced costs by 40%. No baseline is available."
    Path(".vita/results").mkdir(parents=True)
    path = Path(".vita/results/analysis.json")
    path.write_text(json_text(legacy), encoding="utf-8")
    original_bytes = path.read_bytes()
    original_value = copy.deepcopy(legacy)
    loaded = evaluation.load_baseline(project)
    assert loaded["overall_score"] == 50
    assert loaded["metadata"] == legacy["metadata"]
    assert loaded["comparison"]["status"] == "not_recorded"
    markdown = evaluation.render_report(loaded, "Legacy assessment")
    assert "50.00/100 (50.00%)" in markdown
    assert "44.50" not in markdown
    assert "Reduced costs by 40%" in markdown
    assert "Baseline availability was not recorded in this legacy report" in markdown
    assert "No baseline is available" not in markdown
    after = evaluation.finalize(json_text(evaluation_report()), project, loaded)
    assert after["comparison"] == {"status": "available", "baseline_overall_score": 50, "overall_delta": 50}
    assert evaluation.compute_delta(loaded, after)["overall_score"]["before"] == 50
    assert legacy == original_value and path.read_bytes() == original_bytes
    validate(loaded, EVALUATION_SCHEMA)


def test_render_and_save_share_recomputed_record(project, evaluation_report):
    report = evaluation.finalize(json_text(evaluation_report()), project)
    report["overall_score"] = 44.50
    report["category_scores"]["hard_skills"] = 44.50
    report["executive_summary"] = "Stale score 44.50%."
    evaluation.save_evaluation("analyze", report)
    stored = parse_json(Path(".vita/results/analysis.json").read_text(encoding="utf-8"))
    markdown = Path(".vita/results/analysis.md").read_text(encoding="utf-8")
    assert stored["overall_score"] == 100
    assert "100.00/100" in stored["executive_summary"]
    assert stored["executive_summary"] in markdown
    assert "44.50" not in json_text(stored) + markdown


def test_model_prompt_requests_qualitative_narrative_and_reserves_host_claims(project):
    prompt = evaluation.evaluation_instruction("review", project)
    assert "qualitative executive_summary" in prompt
    assert "baseline availability/comparison claims" in prompt
    assert "40% cost reduction" in prompt
    assert "host-owned fields" in prompt


def test_achievement_can_equal_the_rejected_assessment_percentage(project, evaluation_report):
    model = benchmark_report(evaluation_report)
    model["executive_summary"] = "Overall fit is 44.50%. Reduced costs by 44.50%."
    report = evaluation.finalize(json_text(model), project)
    markdown = evaluation.render_report(report, "Assessment")
    assert "46.76/100 (46.76%)" in report["executive_summary"]
    assert report["qualitative_summary"] == "Reduced costs by 44.50%."
    assert "Reduced costs by 44.50%" in markdown
    assert "Overall fit is 44.50%" not in json_text(report) + markdown
