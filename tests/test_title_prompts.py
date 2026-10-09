"""Check title guidance reaches manual and autonomous CV workflows."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vita.commands.ai_step import run


class TitlePromptTests(unittest.TestCase):
    def setUp(self):
        original_cwd = Path.cwd()
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.addCleanup(os.chdir, original_cwd)
        os.chdir(workspace.name)
        Path("main.tex").write_text(
            r"\textbf{Applied AI Engineer | Production AI Agents \& Enterprise AI Systems}",
            encoding="utf-8",
        )

    def check_workflow(self, *, auto, multiple_jobs, language=None):
        jobs = "Applied AI Engineer: build production AI agents."
        if multiple_jobs:
            jobs = f"# Job 1\n{jobs}\n# Job 2\nML Engineer: build enterprise AI systems."
        Path("job.md").write_text(jobs, encoding="utf-8")
        for step in ("analyze", "adapt", "review"):
            with self.subTest(step=step):
                with contextlib.redirect_stdout(io.StringIO()), patch(
                    "vita.commands.ai_step.llm_generate", return_value="Mock report"
                ) as generate:
                    run(step, auto=auto, language=language)
                if auto:
                    generate.assert_called_once()
                    prompt = generate.call_args.args[1]
                else:
                    generate.assert_not_called()
                    prompt = Path(".vita/current_prompt.md").read_text(encoding="utf-8")
                self.assertIn("exactly one role name", prompt)
                self.assertIn("summary or skills", prompt)
                self.assertIn("Applied AI Engineer | Production AI Agents & Enterprise AI Systems", prompt)
                self.assertNotIn("keywords that should appear in the title/headline", prompt)
                if step in ("analyze", "adapt"):
                    self.assertNotIn("{{JOB_DESCRIPTION}}", prompt)
                    if multiple_jobs:
                        self.assertIn("Multiple job descriptions detected (2 jobs)", prompt)
                if language and step == "adapt":
                    self.assertIn("The entire CV must be written in **French**", prompt)

    def test_manual_single_job(self):
        self.check_workflow(auto=False, multiple_jobs=False)

    def test_manual_multiple_jobs(self):
        self.check_workflow(auto=False, multiple_jobs=True)

    def test_autonomous_single_job(self):
        self.check_workflow(auto=True, multiple_jobs=False)

    def test_autonomous_multiple_jobs_with_translation(self):
        self.check_workflow(auto=True, multiple_jobs=True, language="fr")


if __name__ == "__main__":
    unittest.main()
