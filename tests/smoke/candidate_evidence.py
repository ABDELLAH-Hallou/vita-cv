"""Installed issue #42 replay using synthetic sources and no AI providers."""

from pathlib import Path

from vita.helpers.candidate_evidence import capture_candidate_sources, digest
from vita.helpers.evaluation import finalize, render_report, save_evaluation
from vita.helpers.job_extraction import JobContext
from vita.helpers.structured import CATEGORIES, json_text, write_artifact


def main():
    Path("main.tex").write_text("Python engineer\n\\input{evidence-work}\n", encoding="utf-8")
    Path("evidence-work.tex").write_text("Built reliable pipelines.\n", encoding="utf-8")
    Path(".vita/cv.yaml").write_text("achievement: Led migration\n", encoding="utf-8")
    write_artifact(Path(".vita/cv-verified.json"), json_text({
        "schema_version": 1, "source_sha256": digest(Path(".vita/cv.yaml").read_text(encoding="utf-8")),
        "verified_spans": [{"line_start": 1, "line_end": 1}],
    }))
    snapshot = capture_candidate_sources("main.tex")
    job = JobContext("Python", "job-hash", "context-hash", ("job-1",), False)
    model = {
        "schema_version": 1, "overall_score": 0, "category_scores": dict.fromkeys(CATEGORIES, 0),
        "executive_summary": "Review candidate evidence.", "strengths": [], "gaps": [], "recommendations": [],
        "metrics": {"criteria": [], "matched_count": 0, "partial_count": 0, "missing_count": 0, "total_count": 0},
    }
    for index, source in enumerate(snapshot["sources"]):
        quote = source["content"].splitlines()[0]
        model["metrics"]["criteria"].append({
            "id": f"criterion-{index}", "job_id": "job-1", "category": "hard_skills",
            "criterion": "Relevant experience", "importance": "must_have", "status": "partial",
            "evidence": quote, "evidence_kind": "direct", "feedback": "More depth needed.",
            "evidence_refs": [{"source_id": source["id"], "quote": quote, "line_start": 1, "line_end": 1}],
        })
    report = finalize(json_text(model), job, sources=snapshot)
    assert len(report["metrics"]["criteria"]) == 3
    assert all(item["evidence_verification"]["status"] == "verified" for item in report["metrics"]["criteria"])
    model["metrics"]["criteria"][0]["evidence"] = "Built BenchmarkNebula at FictionalEmployer"
    control = finalize(json_text(model), job, sources=snapshot)
    assert control["metrics"]["criteria"][0]["evidence_verification"]["status"] == "unverified"
    assert "unverified evidence" in control["executive_summary"]
    save_evaluation("analyze", control)
    Path("evidence-work.tex").write_text("Changed source\n", encoding="utf-8")
    stale = finalize(json_text(model), job, sources=snapshot)
    assert all(item["evidence_verification"]["status"] == "unverified" for item in stale["metrics"]["criteria"])
    assert "changed during assessment" in render_report(stale, "Stale evidence")
    print("Installed candidate-evidence smoke test passed")


if __name__ == "__main__":
    main()
