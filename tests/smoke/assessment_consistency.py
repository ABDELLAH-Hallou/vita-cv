"""Mandatory paired unchanged-input quality control; synthetic provider only."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from vita.commands import ai_step
from vita.helpers import requirements
from vita.helpers.candidate_evidence import capture_candidate_sources
from vita.helpers.structured import CATEGORIES, json_text, parse_json, write_artifact


def main():
    original = Path.cwd()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        os.chdir(root)
        try:
            Path(".vita").mkdir()
            Path("main.tex").write_text("Python engineer\n", encoding="utf-8")
            Path("job.md").write_text("Python is required.\n", encoding="utf-8")
            write_artifact(Path(".vita/extensions.json"), json_text({
                "llm_providers": {"openai": {"model": "smoke-judge", "reasoning_effort": "low"}}}))
            environment = {"ENABLE_JD_EXTRACTION": "false", "VITA_REQUIREMENTS_DIR": str(root / "registry"),
                           "ANALYSIS_PROVIDER": "openai", "ANALYSIS_MODEL": "smoke-judge",
                           "REVIEW_PROVIDER": "openai", "REVIEW_MODEL": "smoke-judge"}
            with patch.dict(os.environ, environment):
                doc = requirements.save_revision(requirements.compile_revision({"schema_version": 1, "items": [{
                    "job_id": "job-1", "key": "python", "text": "Python", "kind": "capability", "category": "hard_skills",
                    "classification": "required", "ambiguity": "",
                    "source_refs": [{"job_id": "job-1", "line_start": 1, "line_end": 1, "quote": "Python is required."}],
                }]}, "Python is required.\n"))
                requirements.approve_revision(doc["revision"], "Python is required.\n")
                status = ["partial"]

                def generate(system, prompt, **options):
                    session = options["session"]
                    session["route"] = {"provider": "openai", "model": "smoke-judge", "reasoning_effort": "low"}
                    source = capture_candidate_sources()["sources"][0]
                    criterion = {key: doc["requirements"][0][key] for key in ("id", "job_id", "category", "criterion", "importance")}
                    criterion.update(status=status[0], evidence="Python engineer", feedback="Clarify production scope.",
                                     evidence_kind="direct", evidence_refs=[{"source_id": source["id"], "quote": "Python engineer",
                                                                           "line_start": 1, "line_end": 1}])
                    return json_text({"schema_version": 1, "overall_score": 0, "category_scores": dict.fromkeys(CATEGORIES, 0),
                                      "executive_summary": "Relevant documented experience.", "strengths": [], "gaps": [], "recommendations": [],
                                      "metrics": {"criteria": [criterion], "matched_count": 0, "partial_count": 0,
                                                  "missing_count": 0, "total_count": 1}})

                provider = Mock(side_effect=generate)
                with patch("vita.commands.ai_step.llm_generate", provider):
                    assert ai_step.run("analyze", auto=True)
                    before = parse_json(Path(".vita/results/analysis.json").read_text(encoding="utf-8"))
                    assert ai_step.run("review", auto=True)
                    after = parse_json(Path(".vita/results/review.json").read_text(encoding="utf-8"))
                    control = {"schema_version": 1, "control": "paired cross-stage unchanged-input control",
                               "cv_sha256": before["metadata"]["assessment"]["cv_sha256"],
                               "assessment_key": before["metadata"]["assessment"]["key"],
                               "before": before["overall_score"], "after": after["overall_score"],
                               "status_changes": sum(a["status"] != b["status"] for a, b in zip(
                                   before["metrics"]["criteria"], after["metrics"]["criteria"], strict=True))}
                    assert provider.call_count == 1 and control["before"] == control["after"] and control["status_changes"] == 0
                    assert before["metadata"]["assessment"] == after["metadata"]["assessment"]
                    write_artifact(original / ".vita/results/unchanged-control.json", json_text(control))
                    status[0] = "matched"
                    assert ai_step.run("review", auto=True, reassess=True)
                    reassessed = parse_json(Path(".vita/results/review.json").read_text(encoding="utf-8"))
                    assert reassessed["assessment_comparison"]["kind"] == "unchanged_reassessment"
                    assert "not evidence that tailoring caused an improvement" in reassessed["executive_summary"]
                    assert provider.call_args_list[0].args == provider.call_args_list[1].args
        finally:
            os.chdir(original)
    print("Installed cross-stage consistency and unchanged-input controls passed")


if __name__ == "__main__":
    main()
