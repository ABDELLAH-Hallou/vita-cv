"""Replay issue #37 against an installed wheel; all provider calls are mocked."""

import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from vita.commands import ai_step
from vita.helpers.structured import CATEGORIES


def main():
    report = {
        "schema_version": 1, "overall_score": 100,
        "category_scores": {category: 100 if category == "hard_skills" else 0 for category in CATEGORIES},
        "executive_summary": "Synthetic Python evidence matches the job.",
        "strengths": ["Python"], "gaps": [], "recommendations": ["Describe the Python project."],
        "metrics": {"criteria": [{"id": "python", "job_id": "job-1", "category": "hard_skills",
                                  "criterion": "Python", "importance": "must_have", "status": "matched",
                                  "evidence": "Python engineer", "feedback": "Describe the project."}],
                    "matched_count": 1, "partial_count": 0, "missing_count": 0, "total_count": 1},
    }
    provider = Mock(side_effect=['{"schema_version": 1 "overall_score": 50}', json.dumps(report)])
    with patch.dict(os.environ, {"ENABLE_JD_EXTRACTION": "false"}), patch("vita.commands.ai_step.llm_generate", provider):
        assert ai_step.run("analyze", auto=True)
    assert provider.call_count == 2
    outcome = json.loads(Path(".vita/results/analyze.outcome.json").read_text(encoding="utf-8"))
    assert outcome["status"] == "success" and outcome["recovered"]
    assert [attempt["category"] for attempt in outcome["attempts"]] == ["invalid_json", "valid"]
    assert Path(".vita/results/analysis.json").is_file()
    print("Installed structured-output recovery passed")


if __name__ == "__main__":
    main()
