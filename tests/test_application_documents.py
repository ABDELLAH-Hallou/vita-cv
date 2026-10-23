"""Exercise custom task skills and the complete two-document workflow."""

import json
import shutil
from unittest.mock import Mock

import pytest

from vita.commands import ai_step, build, init, run, sync
from vita.helpers.config import DEFAULT_CONFIG
from vita.helpers.context_builder import build_system_context
from vita.helpers.skills import TASK_SKILLS, skill_context

LATEX = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".vita").mkdir()
    (tmp_path / ".vita/config.json").write_text(
        json.dumps({**DEFAULT_CONFIG, "author": "candidate"}), encoding="utf-8"
    )
    (tmp_path / "main.tex").write_text(LATEX % "Original CV", encoding="utf-8")
    (tmp_path / "job.md").write_text("Acme seeks a Python engineer.", encoding="utf-8")
    return tmp_path


def custom_skill(project, task, filename, text):
    path = project / ".vita/skills" / task / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_custom_skills_override_append_and_stay_in_their_task(project):
    custom_skill(project, "adapt", "resume-tailor.md", "REPLACEMENT: write natural French.")
    custom_skill(project, "adapt", "a-style.md", "ADDITIONAL: select one achievement.")
    custom_skill(project, "adapt", "z-style.md", "LAST: avoid excessive bold.")
    custom_skill(project, "cover", "letter.md", "COVER ONLY: first-person paragraphs.")
    context = skill_context("adapt")
    assert "REPLACEMENT" in context
    assert "The Tailoring Philosophy" not in context
    assert "Tech Resume Philosophy" in context
    assert context.index("ADDITIONAL") < context.index("LAST")
    assert "COVER ONLY" not in context
    assert "COVER ONLY" in skill_context("cover")


def test_empty_custom_skill_keeps_bundled_default(project):
    custom_skill(project, "cover", "cover-letter-generator.md", "  \n")
    assert "Cover Letter Philosophy" in skill_context("cover")


@pytest.mark.parametrize("task", ["analyze", "adapt", "review", "cover"])
def test_manual_and_auto_use_same_task_skills(project, monkeypatch, task, evaluation_report):
    custom_skill(project, task, "my-style.md", f"UNIQUE {task} STYLE")
    scoring_task = "assess" if task in ("analyze", "review") else task
    if scoring_task == "assess":
        custom_skill(project, "assess", "my-judge.md", "SHARED ASSESSMENT STYLE")
    assert ai_step.run(task, language="fr")
    manual = (project / f".vita/prompts/{task}.md").read_text(encoding="utf-8")
    response = (json.dumps(evaluation_report()) if task in ("analyze", "review")
                else "Changes\n```latex\n" + LATEX % "Updated" + "\n```")
    provider = Mock(return_value=response)
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run(task, auto=True, language="fr", provider="codex")
    system, prompt = provider.call_args.args
    assert skill_context(scoring_task) in manual
    assert skill_context(scoring_task) in system
    if scoring_task == "assess":
        assert f"UNIQUE {task} STYLE" not in manual + system + prompt
    assert provider.call_args.kwargs["provider"] == "codex"
    if task in ("analyze", "review"):
        assert "response_schema" in provider.call_args.kwargs
    else:
        assert set(provider.call_args.kwargs) == {"provider", "session"}
        assert provider.call_args.kwargs["session"]["request"]["attempt"] == 1
    if task in ("cover", "adapt"):
        assert "**French**" in manual
        assert "**French**" in prompt


def test_full_pipeline_uses_adapted_cv_for_cover_and_same_provider(project, monkeypatch, evaluation_report):
    calls = []

    def generate(system, prompt, provider=None):
        calls.append((system, prompt, provider))
        if "TASK SKILLS" in system and "Cover Letter Philosophy" in system:
            assert "Tailored CV" in system
            assert "Original CV" not in system
            assert "Acme seeks a Python engineer" in prompt
            assert "**French**" in prompt
            return "Letter created.\n```latex\n" + LATEX % "Madame, Monsieur" + "\n```"
        if "exactly one ```latex" in prompt:
            return "CV updated.\n```latex\n" + LATEX % "Tailored CV" + "\n```"
        return json.dumps(evaluation_report())

    monkeypatch.setattr(ai_step, "llm_generate", generate)
    assert run.run(auto=True, language="fr", provider="codex")
    assert len(calls) == 4
    assert all(provider == "codex" for _, _, provider in calls)
    assert "Tailored CV" in (project / "main.tex").read_text(encoding="utf-8")
    assert "Madame, Monsieur" in (project / "cover-letter.tex").read_text(encoding="utf-8")
    assert all((project / f".vita/results/{task}.md").is_file() for task in ("analyze", "adapt", "review", "cover"))


def test_manual_pipeline_preserves_every_prompt_and_order(project):
    assert run.run(language="fr")
    instructions = (project / ".vita/current_prompt.md").read_text(encoding="utf-8")
    positions = []
    for task in ("analyze", "adapt", "review", "cover"):
        assert (project / f".vita/prompts/{task}.md").is_file()
        positions.append(instructions.index(f".vita/prompts/{task}.md"))
    assert positions == sorted(positions)


def test_pipeline_stops_on_failure(project, monkeypatch):
    provider = Mock(side_effect=RuntimeError("Provider unavailable"))
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert run.run(auto=True, provider="codex") is False
    assert provider.call_count == 1
    assert not (project / "cover-letter.tex").exists()


@pytest.mark.parametrize("response", [
    "No document", "```latex\n\n```", "```latex\nBody only\n```",
    "```latex\nfirst\n```\n```latex\nsecond\n```",
])
def test_invalid_letter_preserves_existing_files(project, monkeypatch, response):
    letter = project / "cover-letter.tex"
    letter.write_text("Previous letter", encoding="utf-8")
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value=response))
    assert ai_step.run("cover", auto=True) is False
    assert letter.read_text(encoding="utf-8") == "Previous letter"
    assert "Original CV" in (project / "main.tex").read_text(encoding="utf-8")


def test_cover_accepts_crlf_fence_and_custom_paths(project, monkeypatch):
    (project / "main.tex").rename(project / "resume.tex")
    config = {**DEFAULT_CONFIG, "tex_entry": "resume.tex", "cover_tex_entry": "letters/acme.tex"}
    (project / ".vita/config.json").write_text(json.dumps(config), encoding="utf-8")
    provider = Mock(return_value="```latex \r\n" + LATEX % "Letter" + "\r\n```")
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("cover", auto=True)
    assert (project / "letters/acme.tex").is_file()
    system, prompt = provider.call_args.args
    assert "FILE: resume.tex" in system
    assert "`letters/acme.tex`" in prompt


@pytest.mark.parametrize("missing", ["main.tex", "job.md", "empty-job", "same-source"])
def test_cover_requires_sources_and_does_not_overwrite_cv(project, monkeypatch, missing):
    if missing == "empty-job":
        (project / "job.md").write_text(" \n", encoding="utf-8")
    elif missing == "same-source":
        config = {**DEFAULT_CONFIG, "cover_tex_entry": "main.tex"}
        (project / ".vita/config.json").write_text(json.dumps(config), encoding="utf-8")
    else:
        (project / missing).unlink()
    provider = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("cover", auto=True) is False
    provider.assert_not_called()


def test_cover_multiple_jobs_and_knowledge_are_grounded(project, monkeypatch):
    (project / "job.md").write_text("# Job 1\nPython\n# Job 2\nData", encoding="utf-8")
    (project / ".vita/cv.yaml").write_text("achievement: Known achievement", encoding="utf-8")
    provider = Mock(return_value="```latex\n" + LATEX % "Letter" + "\n```")
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("cover", auto=True)
    prompt = provider.call_args.args[1]
    assert "ONE optimized cover letter" in prompt
    assert "Known achievement" in prompt
    assert "never as proof" in prompt


def test_context_loads_modular_cv_once_and_ignores_commented_inputs(project):
    (project / "main.tex").write_text(
        "\\input{experience}\n\\include{experience}\n%\\input{ignored}\n", encoding="utf-8"
    )
    (project / "experience.tex").write_text("True experience\n\\input{main}", encoding="utf-8")
    (project / "ignored.tex").write_text("Should not be included", encoding="utf-8")
    context = build_system_context("", step="cover")
    assert context.count("True experience") == 1
    assert "Should not be included" not in context


def test_sync_and_init_scaffold_task_folders_and_preserve_custom_skills(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(init.git, "init", lambda: None)
    init.run()
    assert all((tmp_path / ".vita/skills" / task).is_dir() for task in TASK_SKILLS)
    skill = custom_skill(tmp_path, "cover", "mine.md", "My own style")
    (tmp_path / ".vita/skills/adapt").rmdir()
    monkeypatch.setattr(sync.git, "all_branches", lambda: [])
    sync.run(auto=True)
    assert (tmp_path / ".vita/skills/adapt").is_dir()
    assert skill.read_text(encoding="utf-8") == "My own style"


@pytest.mark.parametrize("target,expected", [
    ("resume", ["cv-candidate.pdf"]),
    ("cover", ["cover-letter-candidate.pdf"]),
    ("both", ["cv-candidate.pdf", "cover-letter-candidate.pdf"]),
])
def test_build_selects_documents_and_outputs(project, monkeypatch, target, expected):
    (project / "cover-letter.tex").write_text(LATEX % "Letter", encoding="utf-8")
    commands = []

    def compile_document(cmd):
        commands.append(cmd)
        name = next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("-jobname="))
        (project / "out" / f"{name}.pdf").write_bytes(b"%PDF-test")
        return True

    monkeypatch.setattr(build, "_step", compile_document)
    assert build.run(target)
    assert sorted(path.name for path in (project / "out").glob("*.pdf")) == sorted(expected)
    assert len(commands) == len(expected)


def test_build_both_preflights_sources_and_propagates_compiler_failure(project, monkeypatch):
    compiler = Mock(return_value=False)
    monkeypatch.setattr(build, "_step", compiler)
    assert build.run("both") is False
    compiler.assert_not_called()
    (project / "cover-letter.tex").write_text(LATEX % "Letter", encoding="utf-8")
    assert build.run("both") is False
    assert compiler.call_count == 1


def test_build_does_not_claim_success_without_pdf(project, monkeypatch):
    monkeypatch.setattr(build, "_step", lambda cmd: True)
    assert build.run() is False


@pytest.mark.parametrize("target", ["resume", "cover", "both"])
def test_build_rejects_output_collision(project, monkeypatch, target):
    config = {**DEFAULT_CONFIG, "cover_output_filename": "cv-{author}.pdf"}
    (project / ".vita/config.json").write_text(json.dumps(config), encoding="utf-8")
    compiler = Mock()
    monkeypatch.setattr(build, "_step", compiler)
    assert build.run(target) is False
    compiler.assert_not_called()


@pytest.mark.parametrize("arguments,target", [
    ([], "resume"), (["-r"], "resume"), (["--resume"], "resume"),
    (["-c"], "cover"), (["--cover"], "cover"), (["both"], "both"),
])
def test_cli_build_options(project, monkeypatch, arguments, target):
    from vita.__main__ import main

    compiler = Mock(return_value=True)
    monkeypatch.setattr(build, "run", compiler)
    monkeypatch.setattr("sys.argv", ["vita", "build", *arguments])
    main()
    compiler.assert_called_once_with(target)


@pytest.mark.parametrize("arguments", [["both", "-r"], ["both", "-c"], ["-r", "-c"]])
def test_cli_rejects_ambiguous_build_options(project, monkeypatch, arguments):
    from vita.__main__ import main

    compiler = Mock()
    monkeypatch.setattr(build, "run", compiler)
    monkeypatch.setattr("sys.argv", ["vita", "build", *arguments])
    with pytest.raises(SystemExit, match="2"):
        main()
    compiler.assert_not_called()


def test_cli_build_failure_returns_nonzero(project, monkeypatch):
    from vita.__main__ import main

    monkeypatch.setattr(build, "run", lambda target: False)
    monkeypatch.setattr("sys.argv", ["vita", "build", "both"])
    with pytest.raises(SystemExit, match="1"):
        main()


def test_pipeline_reuses_configured_model_for_cover(project, monkeypatch, evaluation_report):
    from vita.helpers import llm

    monkeypatch.setattr(llm, "load_env", lambda: {})
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"codex": {"model": "configured-model"}})
    backend = Mock(side_effect=[
        json.dumps(evaluation_report()), "```latex\n" + LATEX % "CV" + "\n```",
        json.dumps(evaluation_report()), "```latex\n" + LATEX % "Cover" + "\n```",
    ])
    monkeypatch.setattr(llm, "_call_codex_cli", backend)
    assert run.run(auto=True, language="en", provider="codex")
    assert backend.call_count == 4
    assert all(call.args[2] == "configured-model" for call in backend.call_args_list)
    assert "**English**" in backend.call_args_list[1].args[1]
    assert "**English**" in backend.call_args_list[3].args[1]


@pytest.mark.skipif(shutil.which("latexmk") is None, reason="Requires a local TeX installation")
def test_real_latex_compilation_of_both_documents(project):
    (project / "main.tex").write_text(LATEX % "Curriculum vitae", encoding="utf-8")
    (project / "cover-letter.tex").write_text(
        LATEX % "Madame, Monsieur, voici ma lettre de motivation.", encoding="utf-8"
    )
    assert build.run("both")
    for filename in ("cv-candidate.pdf", "cover-letter-candidate.pdf"):
        pdf = project / "out" / filename
        assert pdf.read_bytes().startswith(b"%PDF-")
