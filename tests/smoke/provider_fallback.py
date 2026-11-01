"""Verify the installed operation fallback with fake providers only."""

import json
import os
import tempfile
from pathlib import Path

from vita.helpers.provider_errors import ProviderError
from vita.helpers.structured_output import run_text


def check():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as temporary:
        try:
            os.chdir(temporary)
            for key in list(os.environ):
                if key.startswith(("VITA_", "EXTRACTION_", "ANALYSIS_", "ADAPT_", "REVIEW_", "COVER_")):
                    os.environ.pop(key)
            os.environ.update(VITA_PROJECT_ROOT=temporary, VITA_DIAGNOSTIC_CONTENT="off",
                              VITA_FALLBACK_ENABLED="true", VITA_FALLBACK_PROVIDER="codex",
                              VITA_FALLBACK_MODEL="gpt-6.1-sol")
            Path(".vita").mkdir()
            Path(".vita/config.json").write_text("{}", encoding="utf-8")
            Path("main.tex").write_text("Synthetic Python CV", encoding="utf-8")
            Path("job.md").write_text("Python role", encoding="utf-8")
            calls = []
            def generate(system, prompt, **kwargs):
                calls.append((kwargs["provider"], kwargs["model"]))
                if kwargs["provider"] == "gemini":
                    raise ProviderError(code="overloaded")
                return "backup output"
            assert run_text(step="adapt", generate=generate, system="Synthetic", prompt="No real candidate",
                            route={"provider": "gemini", "model": "primary-fixture"}) == "backup output"
            assert calls == [("gemini", "primary-fixture"), ("codex", "gpt-6.1-sol")]
            record = json.loads(Path(".vita/results/adapt.outcome.json").read_text(encoding="utf-8"))
            assert [attempt["kind"] for attempt in record["attempts"]] == ["initial", "fallback"]
            assert record["routing"]["effective"]["provider"] == "codex"
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    check()
    print("Installed provider fallback passed")
