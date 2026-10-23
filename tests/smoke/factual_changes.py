"""Replay Q07 against an installed wheel with synthetic sources and no network."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from vita.commands import ai_step, facts
from vita.helpers import factual_changes as fc


@contextmanager
def temporary_project():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as temporary:
        try:
            os.chdir(temporary)
            yield
        finally:
            os.chdir(previous)


def check():
    os.environ["ENABLE_JD_EXTRACTION"] = "false"
    source = "\\documentclass{article}\n\\begin{document}\nOOP best practices; Sen 2017; TTR; revenue 1M; Certificate in progress\n\\end{document}"
    with temporary_project():
        Path(".vita").mkdir()
        Path(".vita/config.json").write_text("{}", encoding="utf-8")
        Path("main.tex").write_text(source, encoding="utf-8")
        Path("job.md").write_text("Architect wanted", encoding="utf-8")
        proposed = source.replace("OOP best practices", "Object Oriented Design practices")
        ai_step.llm_generate = lambda *args, **kwargs: "```latex\n" + proposed + "\n```"
        assert ai_step.run("adapt", auto=True) is False
        assert Path("main.tex").read_text(encoding="utf-8") == source
        report = json.loads(Path(".vita/results/adapt.facts.json").read_text(encoding="utf-8"))
        assert report["contract_version"] == fc.VERSION
        assert report["changes"][0]["verification"] == "confirmation_required"
        assert ai_step.run("review", auto=True) is False
        assert facts.run("reject", "adapt", revision=report["revision"])
        assert Path("main.tex").read_text(encoding="utf-8") == source


if __name__ == "__main__":
    check()
    print("Installed factual-change gate passed")
