"""Structured evaluator fixtures shared by orchestration and contract tests."""

import pytest

from vita.helpers.structured import CATEGORIES


@pytest.fixture
def human_confirmed_edits(monkeypatch):
    """Explicit human-review simulation for pre-existing synthetic workflow tests.

    Production unattended execution never does this. Q07 tests exercise the
    default stop, reject, stale-source, and manual decision boundaries directly.
    These older tests focus on providers, skills, extraction and score deltas.
    """
    from vita.commands import ai_step
    from vita.helpers import factual_changes

    stage = factual_changes.stage

    def reviewed(context, document):
        if stage(context, document):
            return True
        report = factual_changes.load(context["step"])
        assert report["status"] == "confirmation_required"
        decision = factual_changes.decide(context["step"], report["revision"], True)
        return decision["application_status"] == "applied"

    monkeypatch.setattr(ai_step, "stage", reviewed)


@pytest.fixture
def evaluation_report():
    def make(status="matched", job_ids=("job-1",)):
        criteria = [{
            "id": f"{job_id}-python", "job_id": job_id, "category": "hard_skills",
            "criterion": "Python", "importance": "must_have", "status": status,
            "evidence": "Python engineer" if status != "missing" else "",
            "feedback": "Describe relevant Python work.",
        } for job_id in job_ids]
        score = {"matched": 100, "partial": 50, "missing": 0}[status]
        return {
            "schema_version": 1, "overall_score": score,
            "category_scores": {key: score if key == "hard_skills" else 0 for key in CATEGORIES},
            "executive_summary": "The CV demonstrates relevant experience.",
            "strengths": ["Python"] if status == "matched" else [],
            "gaps": ["Python evidence"] if status != "matched" else [],
            "recommendations": ["Describe the Python project and its outcome."],
            "metrics": {"criteria": criteria, "total_count": len(criteria),
                        **{f"{key}_count": len(criteria) if key == status else 0
                           for key in ("matched", "partial", "missing")}},
        }
    return make
