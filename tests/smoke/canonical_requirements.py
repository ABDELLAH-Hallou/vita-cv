"""Exercise canonical approval and assessment reuse in an installed wheel, offline."""

import os
from pathlib import Path
from unittest.mock import Mock, patch

from vita.commands import ai_step
from vita.helpers import requirements
from vita.helpers.structured import CATEGORIES, json_text, parse_json


def main():
    raw = "# Required\nHubSpot experience is required.\n# Preferred\n6sense is a significant plus.\n# Must-Have or Strong Plus\nAI workflow experience.\n# Employment conditions\nIf working remotely, your own computer is required.\n"
    Path("job.md").write_text(raw, encoding="utf-8")
    proposal = {"schema_version": 1, "items": []}
    for key, line in (("hubspot", 2), ("6sense", 4), ("ai", 6), ("computer", 8)):
        proposal["items"].append({
            "job_id": "job-1", "key": key, "text": raw.splitlines()[line - 1],
            "kind": "capability", "category": "hard_skills", "classification": "required", "ambiguity": "",
            "source_refs": [{"job_id": "job-1", "line_start": line, "line_end": line,
                             "quote": raw.splitlines()[line - 1]}],
        })
    settings = {"VITA_REQUIREMENTS_DIR": str(Path(".vita/smoke-requirements").resolve()), "ENABLE_JD_EXTRACTION": "false"}
    with patch.dict(os.environ, settings):
        data = requirements.save_revision(requirements.compile_revision(proposal, raw))
        requirements.approve_revision(data["revision"], raw)
        results = []
        for cv, status in (("HubSpot engineer", "matched"), ("Other experience", "missing")):
            Path("main.tex").write_text(cv, encoding="utf-8")
            report = {
                "schema_version": 1, "overall_score": 0, "category_scores": {category: 0 for category in CATEGORIES},
                "executive_summary": "Synthetic qualitative assessment.", "strengths": [], "gaps": [], "recommendations": [],
                "metrics": {"criteria": [
                    {**{key: unit[key] for key in ("id", "job_id", "category", "criterion", "importance")},
                     "status": status, "evidence": cv if status == "matched" else "", "feedback": "Clarify evidence."}
                    for unit in data["requirements"]
                ], "matched_count": 0, "partial_count": 0, "missing_count": 0, "total_count": 0},
            }
            with patch("vita.commands.ai_step.llm_generate", Mock(return_value=json_text(report))):
                assert ai_step.run("analyze", auto=True)
            results.append(parse_json(Path(".vita/results/analysis.json").read_text(encoding="utf-8")))
        assert all(result["metrics"]["weighted_available"] == 3 for result in results)
        assert results[0]["metadata"]["criteria_sha256"] == results[1]["metadata"]["criteria_sha256"]
        assert results[0]["metadata"]["requirements_revision"] == data["revision"]
        assert len(results[0]["metrics"]["employment_conditions"]) == 1
        assert [result["overall_score"] for result in results] == [100, 0]
    print("Installed canonical requirement reuse passed")


if __name__ == "__main__":
    main()
