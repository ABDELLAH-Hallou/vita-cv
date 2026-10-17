"""Verify translation instructions reach prompts; do not claim model compliance."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step

CV_CONTENT = {
    "fr": r"""\documentclass{article}
\begin{document}
\section{Profil}Ingénieure en données chez Acme.
\section{Formation}Master en informatique, Université Exemple, 2020.
\section{Publications et articles}Analyse des données \cite{Example2021}.
\section{Engagements personnels}Animation d'ateliers pour une association.
\section{Compétences}Python, SQL.
\label{sec:education}
\texttt{https://example.org/article}
\end{document}""",
    "en": r"""\documentclass{article}
\begin{document}
\section{Profile}Data engineer at Acme.
\section{Education}Master in Computer Science, Example University, 2020.
\section{Publications and articles}Data analysis \cite{Example2021}.
\section{Community contributions}Running workshops for a community group.
\section{Skills}Python, SQL.
\label{sec:education}
\texttt{https://example.org/article}
\end{document}""",
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".vita").mkdir()
    (tmp_path / "job.md").write_text("Acme seeks a data engineer using Python and SQL.", encoding="utf-8")
    return tmp_path


def assert_translation_contract(prompt, target):
    assert f"The entire CV must be written in **{target}**" in prompt
    for section in ("headings", "title/headline", "professional summary", "experience",
                    "education", "projects", "publications/articles", "skills", "awards",
                    "volunteering", "custom sections"):
        assert section in prompt
    assert "Translation applies to the whole document" in prompt
    assert "even where job-tailoring instructions focus on particular sections" in prompt
    assert "Do not leave untranslated source-language prose" in prompt
    for preserved in ("LaTeX commands", "layout", "document structure", "URLs", "citation keys",
                      "label/reference keys", "factual information", "proper nouns"):
        assert preserved in prompt
    assert "text inside LaTeX macro arguments" in prompt
    assert "Do NOT leave English sections behind" not in prompt


@pytest.mark.parametrize("auto", [False, True], ids=["generated-prompt", "provider-prompt"])
@pytest.mark.parametrize("source,language,target", [("fr", "en", "English"), ("en", "fr", "French")])
def test_translation_covers_all_sections_in_both_directions(project, monkeypatch, auto, source, language, target):
    source_cv = CV_CONTENT[source]
    (project / "main.tex").write_text(source_cv, encoding="utf-8")
    # Deliberately echo the source: the test checks instructions, not translation quality.
    provider = Mock(return_value=f"```latex\n{source_cv}\n```")
    monkeypatch.setattr(ai_step, "llm_generate", provider)

    assert ai_step.run("adapt", language=language, auto=auto)
    if auto:
        provider.assert_called_once()
        system, prompt = provider.call_args.args
        assert source_cv in system
        assert r"\cite{Example2021}" in system
        assert r"\label{sec:education}" in system
    else:
        provider.assert_not_called()
        prompt = (project / ".vita/prompts/adapt.md").read_text(encoding="utf-8")
        assert prompt == (project / ".vita/current_prompt.md").read_text(encoding="utf-8")
        assert (project / "main.tex").read_text(encoding="utf-8") == source_cv
    assert_translation_contract(prompt, target)


@pytest.mark.parametrize("auto", [False, True])
def test_helper_without_language_keeps_existing_no_translation_override(project, monkeypatch, auto):
    (project / "main.tex").write_text(CV_CONTENT["fr"], encoding="utf-8")
    provider = Mock(return_value=f"```latex\n{CV_CONTENT['fr']}\n```")
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("adapt", auto=auto)
    if auto:
        prompt = provider.call_args.args[1]
    else:
        provider.assert_not_called()
        prompt = Path(".vita/current_prompt.md").read_text(encoding="utf-8")
    assert "CRITICAL LANGUAGE INSTRUCTION" not in prompt


@pytest.mark.parametrize("auto", [False, True])
def test_cli_without_language_keeps_english_default(project, monkeypatch, auto):
    (project / "main.tex").write_text(CV_CONTENT["fr"], encoding="utf-8")
    provider = Mock(return_value=f"```latex\n{CV_CONTENT['fr']}\n```")
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    monkeypatch.setattr(sys, "argv", ["vita", "adapt"] + (["--auto"] if auto else []))
    main()
    if auto:
        prompt = provider.call_args.args[1]
    else:
        provider.assert_not_called()
        prompt = Path(".vita/current_prompt.md").read_text(encoding="utf-8")
    assert_translation_contract(prompt, "English")


def test_translation_respects_custom_cv_entry_and_language_map(project, monkeypatch):
    (project / "profile.tex").write_text(CV_CONTENT["fr"], encoding="utf-8")
    (project / ".vita/config.json").write_text(json.dumps({"tex_entry": "profile.tex"}), encoding="utf-8")
    (project / ".vita/extensions.json").write_text(
        json.dumps({"language_map": {"en-us": "American English"}}), encoding="utf-8"
    )
    provider = Mock(return_value=f"```latex\n{CV_CONTENT['fr']}\n```")
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("adapt", language="EN-US", auto=True)
    system, prompt = provider.call_args.args
    assert CV_CONTENT["fr"] in system
    assert "`profile.tex`" in prompt
    assert_translation_contract(prompt, "American English")
