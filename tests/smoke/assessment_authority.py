"""Check authoritative assessment rendering in an installed wheel, without AI."""

from pathlib import Path

from vita.helpers.evaluation import finalize, render_report, save_evaluation
from vita.helpers.job_extraction import JobContext
from vita.helpers.structured import CATEGORIES, json_text, parse_json


def main():
    model = {
        "schema_version": 1, "overall_score": 44.50,
        "category_scores": {category: 44.50 for category in CATEGORIES},
        "executive_summary": "Overall fit is 44.50%. Reduced costs by 40%. No baseline is available.",
        "strengths": ["Reduced costs by 40%."], "gaps": [], "recommendations": ["Describe Python work."],
        "metrics": {"criteria": [{"id": "python", "job_id": "job-1", "category": "hard_skills",
                                  "criterion": "Python", "importance": "must_have", "status": "partial",
                                  "evidence": "Python engineer", "feedback": "Describe the project."}],
                    "matched_count": 0, "partial_count": 1, "missing_count": 0, "total_count": 1},
    }
    job = JobContext("Synthetic job", "job-hash", "context-hash", ("job-1",), False)
    before = finalize(json_text(model), job)
    after = finalize(json_text(model), job, before, step="review")
    save_evaluation("review", after)
    report = parse_json(Path(".vita/results/review.json").read_text(encoding="utf-8"))
    markdown = Path(".vita/results/review.md").read_text(encoding="utf-8")
    assert report["overall_score"] == 50
    assert "50.00/100 (50.00%)" in report["executive_summary"]
    assert report["executive_summary"] in markdown
    assert "44.50" not in json_text(report) + markdown
    assert "No baseline is available" not in json_text(report) + markdown
    assert "Reduced costs by 40%" in markdown
    assert report["comparison"]["status"] == "available"
    legacy = dict(model)
    assert "not recorded in this legacy report" in render_report(legacy, "Legacy")
    print("Installed assessment-authority smoke test passed")


if __name__ == "__main__":
    main()
