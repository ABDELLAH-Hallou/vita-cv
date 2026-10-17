"""Structured evaluator fixtures shared by orchestration and contract tests."""

import pytest

from vita.helpers.structured import CATEGORIES


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
