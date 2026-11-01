"""Installed policy approval uses only synthetic text and mocked generation."""

import json
import os
import tempfile
from pathlib import Path

from vita.commands import ai_step, requirements
from vita.helpers import factual_changes


def check():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as temporary:
        try:
            os.chdir(temporary)
            for key in list(os.environ):
                if key.startswith(("VITA_", "EXTRACTION_", "ANALYSIS_", "ADAPT_", "REVIEW_", "COVER_")):
                    os.environ.pop(key)
            os.environ["VITA_PROJECT_ROOT"] = temporary
            os.environ["VITA_DIAGNOSTIC_CONTENT"] = "off"
            os.environ["ENABLE_JD_EXTRACTION"] = "false"
            Path(".vita").mkdir()
            Path("job.md").write_text("Python required", encoding="utf-8")
            source = "\\documentclass{article}\n\\begin{document}\nSen 2017; Python; 1M\n\\end{document}"
            proposed = source.replace("Sen 2017", "September 2017")
            Path("main.tex").write_text(source, encoding="utf-8")
            requirements.generate = lambda *a, **k: json.dumps({"schema_version": 1, "items": [{
                "job_id": "job-1", "key": "python", "text": "Python", "kind": "capability",
                "category": "hard_skills", "classification": "required", "ambiguity": "",
                "source_refs": [{"job_id": "job-1", "line_start": 1, "line_end": 1, "quote": "Python"}],
            }]})
            ai_step.llm_generate = lambda *a, **k: "```latex\n" + proposed + "\n```"
            assert not ai_step.run("adapt", auto=True)  # Existing auto still pauses.
            assert ai_step.run("adapt", auto=True, approval="unattended")
            report = factual_changes.load("adapt")
            assert report["application_status"] == "applied"
            assert report["approval"]["source"] == "unattended_run_policy"
            assert report["changes"][0]["verification"] == "confirmation_required"
            assert Path("main.tex").read_text(encoding="utf-8") == proposed
            assert ai_step.run("cover", auto=True, approval="unattended")
            cover = factual_changes.load("cover")
            assert next(s["content"] for s in cover["candidate_sources"]["sources"] if s["kind"] == "cv") == proposed
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    check()
    print("Installed unattended policy approval passed")
