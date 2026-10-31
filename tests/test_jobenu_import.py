"""Jobenu local imports, isolated Git branches and approval/resume behavior."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step, import_jobs
from vita.helpers import batch_import, factual_changes, requirements
from vita.helpers.config import DEFAULT_CONFIG
from vita.integrations.jobenu import MAX_BYTES, read

LATEX = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}"


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def application(id="one", company="Acme", position="Machine Learning Engineer", **extra):
    return {"id": id, "company": company, "position": position,
            "description": "Original wording: Python, 40% cost reduction; Sen 2017.",
            "url": "https://example.invalid/job/1", "status": "SAVED", "workMode": "HYBRID",
            "location": "Paris", "compensation": "1M (currency unspecified)", "source": "LinkedIn",
            "appliedAt": None, "deadlineAt": None, "nextAction": None, "nextActionAt": None,
            "appliedProfileId": None, "notes": "Candidate note", "isDemo": False,
            "createdAt": "2026-10-30", "updatedAt": "2026-10-31", **extra}


def export_file(root, records=None, stamp="2026-10-31"):
    path = root / "jobenu.json"
    path.write_text(json.dumps({"exportedAt": stamp, "applications": records or [application()]}, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git("init", "-b", "master")
    git("config", "user.name", "Synthetic Import Tester")
    git("config", "user.email", "tester@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "core.autocrlf", "false")
    git("config", "core.hooksPath", str(tmp_path / ".git/hooks"))
    (tmp_path / ".gitignore").write_text(".vita/\njobenu.json\n", encoding="utf-8")
    (tmp_path / "main.tex").write_text(LATEX % "Original Python engineer.", encoding="utf-8")
    (tmp_path / ".vita/skills/adapt").mkdir(parents=True)
    (tmp_path / ".vita/config.json").write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
    (tmp_path / ".vita/extensions.json").write_text(json.dumps({
        "role_aliases": {"Research Unicorn": "ru"},
        "llm_providers": {"openai": {"model": "custom-model-999", "reasoning_effort": "high"}},
    }), encoding="utf-8")
    (tmp_path / ".vita/.env").write_text("ENABLE_JD_EXTRACTION=false\nANALYSIS_PROVIDER=openai\nANALYSIS_MODEL=custom-model-999\n", encoding="utf-8")
    (tmp_path / ".vita/skills/adapt/style.md").write_text("CUSTOM SAVED STYLE", encoding="utf-8")
    (tmp_path / ".vita/results").mkdir()
    (tmp_path / ".vita/results/analysis.json").write_text('{"stale": true}', encoding="utf-8")
    git("add", ".gitignore", "main.tex")
    git("commit", "-m", "Synthetic base")
    for name in list(os.environ):
        if name.startswith(("EXTRACTION_", "ANALYSIS_", "ADAPT_", "REVIEW_", "COVER_", "VITA_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ai_step, "llm_generate", Mock(side_effect=AssertionError("Real providers are forbidden in import tests")))
    return tmp_path


def result(capsys):
    return json.loads(capsys.readouterr().out)


def test_adapter_preserves_metadata_description_and_filters(tmp_path):
    record = application(description="\nFrench: ingénieur. العربية.\n```\nkeep original\n", unknown={"future": 1})
    file = export_file(tmp_path, [record, application("two", isDemo=True), application("three", status="APPLIED")])
    parsed = read(file)
    assert len(parsed.applications) == 1 and parsed.skipped == 2
    app = parsed.applications[0]
    assert app.description == record["description"]
    assert app.metadata == {k: v for k, v in record.items() if k != "description"}
    assert len(read(file, statuses=["ALL"], include_demo=True).applications) == 3


@pytest.mark.parametrize("record,match", [
    (application(description=""), "description"),
    (application(company=123), "company"),
    (application(isDemo="false"), "isDemo"),
    (application(status=[]), "status"),
])
def test_invalid_records_fail_before_import(tmp_path, record, match):
    with pytest.raises(ValueError, match=match):
        read(export_file(tmp_path, [record]))


def test_duplicate_ids_and_large_files(tmp_path):
    with pytest.raises(ValueError, match="repeats"):
        read(export_file(tmp_path, [application(), application()]))
    file = tmp_path / "large.json"
    file.write_bytes(b" " * (MAX_BYTES + 1))
    with pytest.raises(ValueError, match="10-MiB"):
        read(file)


def test_dry_run_is_machine_readable_and_has_no_writes(project, capsys):
    file = export_file(project, [application(position="Machine Learning Engineer, Foundational AI (FAI)"), application("two", "École & Co", "Research Unicorn")])
    before = git("branch", "--format=%(refname)")
    assert import_jobs.run("jobenu", file, dry_run=True, as_json=True) == 0
    data = result(capsys)
    assert data["base_branch"] == "master"
    assert [e["branch"] for e in data["entries"]] == ["etp-acme-ml", "etp-ecole-co-ru"]
    assert not (project / ".vita/imports").exists()
    assert before == git("branch", "--format=%(refname)")


def test_config_base_and_explicit_override(project, capsys):
    git("branch", "gen-ml")
    config = {**DEFAULT_CONFIG, "default_base_branch": "gen-ml"}
    (project / ".vita/config.json").write_text(json.dumps(config), encoding="utf-8")
    file = export_file(project)
    assert import_jobs.run("jobenu", file, dry_run=True, as_json=True) == 0
    assert result(capsys)["base_branch"] == "gen-ml"
    config["integrations"] = {"jobenu": {"base_branch": "master", "language": "fr"}}
    (project / ".vita/config.json").write_text(json.dumps(config), encoding="utf-8")
    assert import_jobs.run("jobenu", file, dry_run=True, as_json=True) == 0
    data = result(capsys)
    assert (data["base_branch"], data["language"]) == ("master", "fr")
    assert import_jobs.run("jobenu", file, dry_run=True, base_branch="gen-ml", as_json=True) == 0
    assert result(capsys)["base_branch"] == "gen-ml"


def test_missing_base_and_missing_explicit_approval(project, capsys):
    file = export_file(project)
    assert import_jobs.run("jobenu", file, dry_run=True, base_branch="absent", as_json=True) == 1
    assert "existing local branch" in result(capsys)["error"]
    assert import_jobs.run("jobenu", file, as_json=True) == 1
    assert "--approval" in result(capsys)["error"]
    assert not (project / ".vita/imports").exists()


def test_human_plan_gate_and_stale_plan(project, capsys):
    file = export_file(project)
    assert import_jobs.run("jobenu", file, approval="human", as_json=True) == 2
    data = result(capsys)
    assert data["status"] == "awaiting_plan_approval"
    assert not (project / ".vita/imports").exists()
    (project / ".vita/skills/adapt/style.md").write_text("Changed preference", encoding="utf-8")
    assert import_jobs.run("jobenu", file, approval="human", approve_plan=True, plan_id=data["plan_id"], as_json=True) == 1
    assert "plan changed" in result(capsys)["error"]


def test_import_branches_have_independent_bases_metadata_and_preferences(project, capsys):
    git("checkout", "-b", "gen-ml")
    base_cv = LATEX % "Selected ML base."
    (project / "main.tex").write_text(base_cv, encoding="utf-8")
    git("commit", "-am", "ML CV")
    base = git("rev-parse", "HEAD")
    git("checkout", "master")
    # Dirty parent files are preserved, not committed or copied into a CV.
    (project / "main.tex").write_text("UNCOMMITTED PARENT WORK", encoding="utf-8")
    file = export_file(project, [application(), application("two", "Beta", "Data Scientist Junior (H/F)")])
    assert import_jobs.run("jobenu", file, approval="auto", base_branch="gen-ml", as_json=True) == 0
    data = result(capsys)
    for item in data["results"]:
        workspace = Path(item["workspace"])
        assert item["base_commit"] == base
        assert (workspace / "main.tex").read_text(encoding="utf-8") == base_cv
        md = (workspace / "job.md").read_text(encoding="utf-8")
        assert "Original wording: Python, 40% cost reduction; Sen 2017." in md
        for field in ("compensation", "workMode", "url", "source", "notes", "createdAt", "nextActionAt"):
            assert '"'+field+'"' in md
        assert (workspace / ".vita/.env").read_bytes() == (project / ".vita/.env").read_bytes()
        assert (workspace / ".vita/extensions.json").read_bytes() == (project / ".vita/extensions.json").read_bytes()
        assert (workspace / ".vita/skills/adapt/style.md").is_file()
        assert not (workspace / ".vita/results/analysis.json").exists()
        with batch_import.project(workspace):
            assert git("rev-parse", "HEAD~1") == base
            assert git("show", "HEAD:job.md") == md.strip()
    assert git("branch", "--show-current") == "master"
    assert (project / "main.tex").read_text(encoding="utf-8") == "UNCOMMITTED PARENT WORK"
    registry = json.loads((project / ".vita/companies.json").read_text())
    assert registry["acme"]["branch_bases"]["etp-acme-ml"] == "gen-ml"


def test_reimport_is_idempotent_and_changed_content_requires_new_revision(project, capsys):
    file = export_file(project)
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 0
    first = result(capsys)["results"][0]
    old_job = (Path(first["workspace"]) / "job.md").read_bytes()
    export_file(project, stamp="2026-11-01")
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 0
    again = result(capsys)["results"][0]
    assert again["workspace"] == first["workspace"]
    assert again["action"] == "existing"
    file = export_file(project, [application(description="Changed JD")])
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 1
    assert result(capsys)["status"] == "conflict"
    assert import_jobs.run("jobenu", file, approval="auto", new_revision=True, as_json=True) == 0
    revised = result(capsys)["results"][0]
    assert revised["branch"] != first["branch"]
    assert (Path(first["workspace"]) / "job.md").read_bytes() == old_job


def test_same_job_different_base_is_a_new_variant(project, capsys):
    file = export_file(project)
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 0
    first = result(capsys)["results"][0]
    git("checkout", "-b", "gen-other")
    (project / "main.tex").write_text(LATEX % "Other baseline", encoding="utf-8")
    git("commit", "-am", "Other baseline")
    assert import_jobs.run("jobenu", file, approval="auto", base_branch="gen-other", as_json=True) == 0
    second = result(capsys)["results"][0]
    assert second["base_commit"] != first["base_commit"]
    assert second["workspace"] != first["workspace"]
    assert (Path(second["workspace"]) / "job.md").read_text(encoding="utf-8") == (Path(first["workspace"]) / "job.md").read_text(encoding="utf-8")


def test_collisions_are_deterministic_and_never_overwrite_existing_branch(project, capsys):
    git("branch", "etp-acme-ml")
    original = git("rev-parse", "etp-acme-ml")
    file = export_file(project, [application(), application("two")])
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 0
    first = result(capsys)
    branches = [r["branch"] for r in first["results"]]
    assert len(set(branches)) == 2 and all(b.startswith("etp-acme-ml-") for b in branches)
    assert git("rev-parse", "etp-acme-ml") == original
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 0
    assert branches == [r["branch"] for r in result(capsys)["results"]]


def test_locked_company_aborts_before_any_branch(project, capsys):
    (project / ".vita/companies.json").write_text(json.dumps({"acme": {"locked": True}}))
    assert import_jobs.run("jobenu", export_file(project), approval="auto", as_json=True) == 1
    assert result(capsys)["entries"][0]["action"] == "locked"
    assert not (project / ".vita/imports").exists()


def test_pipeline_isolated_failure_continues_other_jobs_and_skips_completed(project, monkeypatch, capsys):
    file = export_file(project, [application(), application("two", "Beta")])
    calls = []
    def step(name, **kwargs):
        calls.append((Path.cwd(), name, kwargs))
        if name == "analyze" and Path.cwd().joinpath("job.md").read_text().startswith("# Machine Learning Engineer — Acme"):
            return False
        if name == "adapt":
            assert "Original Python engineer" in Path("main.tex").read_text()
            Path("main.tex").write_text(LATEX % "Adapted Beta CV", encoding="utf-8")
        return True
    monkeypatch.setattr(ai_step, "run", step)
    assert import_jobs.run("jobenu", file, approval="auto", run_pipeline=True, as_json=True) == 1
    data = result(capsys)
    assert [r["status"] for r in data["results"]] == ["failed", "complete"]
    assert [n for _, n, _ in calls] == ["analyze", "analyze", "adapt", "review", "cover"]
    assert all(kw["provider"] is None for _, _, kw in calls)
    assert Path.cwd() == project
    calls.clear()
    assert import_jobs.run("jobenu", file, approval="auto", run_pipeline=True, as_json=True) == 1
    result(capsys)
    assert [n for _, n, _ in calls] == ["analyze"]


@pytest.mark.parametrize("approval", ["auto", "human"])
def test_real_mocked_pipeline_preserves_factual_gate_and_resumes(project, monkeypatch, capsys, evaluation_report, approval):
    file = export_file(project)
    def generate(system, prompt, **kwargs):
        if "```latex" in prompt:
            return "```latex\n" + LATEX % ("Letter" if "cover-letter.tex" in prompt else "Tailored Python engineer.") + "\n```"
        return json.dumps(evaluation_report())
    provider = Mock(side_effect=generate)
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert import_jobs.run("jobenu", file, approval=approval, approve_plan=True, run_pipeline=True, as_json=True) == 2
    state = result(capsys)["results"][0]
    assert state["status"] == "awaiting_approval" and state["pending"]["step"] == "adapt"
    workspace = Path(state["workspace"])
    assert "Original Python engineer" in (workspace / "main.tex").read_text()
    before = provider.call_count
    # Switching to auto never approves an unresolved interpretation.
    assert import_jobs.run("jobenu", file, approval="auto", run_pipeline=True, as_json=True) == 2
    result(capsys)
    assert provider.call_count == before
    with batch_import.project(workspace):
        factual_changes.decide("adapt", state["pending"]["revision"], True)
    assert import_jobs.run("jobenu", file, approval=approval, approve_plan=True, run_pipeline=True, as_json=True) == 2
    state = result(capsys)["results"][0]
    assert state["pending"]["step"] == "cover"
    with batch_import.project(workspace):
        factual_changes.decide("cover", state["pending"]["revision"], True)
    assert import_jobs.run("jobenu", file, approval=approval, approve_plan=True, run_pipeline=True, as_json=True) == 0
    assert result(capsys)["results"][0]["status"] == "complete"
    assert (workspace / "cover-letter.tex").exists()
    assert provider.call_args_list[0].kwargs['provider'] == 'openai'
    assert provider.call_args_list[0].kwargs['model'] == 'custom-model-999'


def test_human_mode_stages_even_host_verified_unchanged_document(project, capsys):
    Path("job.md").write_text("Python role", encoding="utf-8")
    context = factual_changes.capture("adapt")
    original = Path("main.tex").read_text()
    assert not factual_changes.stage(context, original, require_approval=True)
    report = factual_changes.load("adapt")
    assert report["status"] == "confirmation_required" and report["changes"] == []
    assert factual_changes.decide("adapt", report["revision"], True)["application_status"] == "applied"


def test_cli_json_dry_run_and_relative_path_from_subdirectory(project, monkeypatch, capsys):
    folder = project / "exports"
    folder.mkdir()
    export_file(folder)
    monkeypatch.chdir(folder)
    monkeypatch.setattr(sys, "argv", ["vita", "import", "jobenu", "jobenu.json", "--approval", "auto", "--json"])
    with pytest.raises(SystemExit) as exit:
        main()
    assert exit.value.code == 0
    assert result(capsys)["results"][0]["branch"] == "etp-acme-ml"
    assert Path.cwd() == folder


@pytest.mark.parametrize("enabled", [True, False])
def test_extraction_toggle_and_explicit_provider(project, monkeypatch, capsys, enabled):
    with (project / ".vita/.env").open("a") as f:
        f.write(f"ENABLE_JD_EXTRACTION={'true' if enabled else 'false'}\n")
    step = Mock(return_value=True)
    monkeypatch.setattr(ai_step, "run", step)
    assert import_jobs.run("jobenu", export_file(project), approval="auto", run_pipeline=True,
                           provider="openrouter", as_json=True) == 0
    result(capsys)
    assert [c.args[0] for c in step.call_args_list] == (["extract"] if enabled else []) + ["analyze", "adapt", "review", "cover"]
    for call in step.call_args_list:
        assert call.kwargs["provider"] == (None if call.args[0] == "extract" else "openrouter")


def test_changed_completed_inputs_need_explicit_rerun(project, monkeypatch, capsys):
    step = Mock(return_value=True)
    monkeypatch.setattr(ai_step, "run", step)
    file = export_file(project)
    assert import_jobs.run("jobenu", file, approval="auto", run_pipeline=True, as_json=True) == 0
    state = result(capsys)["results"][0]
    workspace = Path(state["workspace"])
    (workspace / "main.tex").write_text(LATEX % "User edited CV", encoding="utf-8")
    step.reset_mock()
    assert import_jobs.run("jobenu", file, approval="auto", run_pipeline=True, as_json=True) == 1
    assert "--rerun" in result(capsys)["results"][0]["error"]
    step.assert_not_called()
    assert import_jobs.run("jobenu", file, approval="auto", run_pipeline=True, rerun=True, as_json=True) == 0
    result(capsys)
    assert step.call_count == 4
    assert "User edited CV" in (workspace / "main.tex").read_text()


def requirement_proposal(raw):
    line = next(i for i, text in enumerate(raw.splitlines(), 1) if "Python" in text)
    return {"schema_version": 1, "items": [{
        "job_id": "job-1", "key": "python", "text": "Python", "kind": "capability",
        "category": "hard_skills", "classification": "unclear", "ambiguity": "Importance unspecified.",
        "source_refs": [{"job_id": "job-1", "line_start": line, "line_end": line, "quote": "Python"}],
    }]}


def test_canonical_opt_in_preserved_and_approval_shared_across_bases(project, monkeypatch, capsys):
    old = "Python for an old role."
    requirements.save_revision(requirements.compile_revision(requirement_proposal(old), old))
    step = Mock(return_value=True)
    monkeypatch.setattr(ai_step, "run", step)
    file = export_file(project)
    assert import_jobs.run("jobenu", file, approval="auto", run_pipeline=True, as_json=True) == 2
    first = result(capsys)["results"][0]
    assert first["status"] == "awaiting_requirements_approval"
    step.assert_not_called()
    workspace = Path(first["workspace"])
    with batch_import.project(workspace):
        raw = Path("job.md").read_text(encoding="utf-8")
        revision = requirements.compile_revision(requirement_proposal(raw), raw)
        requirements.save_revision(revision)
        requirements.approve_revision(revision["revision"], raw)
    assert import_jobs.run("jobenu", file, approval="auto", run_pipeline=True, as_json=True) == 0
    result(capsys)
    git("checkout", "-b", "gen-second")
    (project / "main.tex").write_text(LATEX % "Other candidate source", encoding="utf-8")
    git("commit", "-am", "Second base")
    with (project / ".vita/.env").open("a") as f:
        f.write("ENABLE_JD_EXTRACTION=true\n")
    step.reset_mock()
    assert import_jobs.run("jobenu", file, base_branch="gen-second", approval="auto", run_pipeline=True, as_json=True) == 0
    second = result(capsys)["results"][0]
    with batch_import.project(Path(second["workspace"])):
        assert requirements.active_requirements(Path("job.md").read_text())["revision"] == revision["revision"]
    assert [c.args[0] for c in step.call_args_list] == ["analyze", "adapt", "review", "cover"]


def test_unowned_worktree_is_rejected(project, capsys):
    file = export_file(project)
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 0
    entry = result(capsys)["results"][0]
    index_path = project / ".vita/imports/jobenu/index.json"
    index = json.loads(index_path.read_text())
    index["applications"][entry["key"]]["versions"][entry["fingerprint"]]["workspace"] = str(project)
    index_path.write_text(json.dumps(index))
    assert import_jobs.run("jobenu", file, approval="auto", run_pipeline=True, as_json=True) == 1
    assert "outside" in result(capsys)["results"][0]["error"]
    assert "Original Python engineer" in (project / "main.tex").read_text()


def test_lock_and_filtered_empty_batch(project, capsys):
    file = export_file(project, [application(status="APPLIED")])
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 0
    assert result(capsys)["status"] == "empty"
    assert not (project / ".vita/imports").exists()
    file = export_file(project)
    folder = project / ".vita/imports/jobenu"
    folder.mkdir(parents=True)
    (folder / "import.lock").write_text("another process")
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 1
    assert "already running" in result(capsys)["error"]


def test_json_and_errors_never_include_credentials(project, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret-never-print")
    monkeypatch.setattr(ai_step, "run", Mock(side_effect=RuntimeError("fixture-secret-never-print")))
    assert import_jobs.run("jobenu", export_file(project), approval="auto", run_pipeline=True, as_json=True) == 1
    text = capsys.readouterr().out
    assert "fixture-secret-never-print" not in text
    assert json.loads(text)["results"][0]["status"] == "failed"


def test_imported_private_settings_stay_ignored_without_parent_ignore_rule(project, capsys):
    (project / ".gitignore").write_text("", encoding="utf-8")
    git("commit", "-am", "Base without ignore rules")
    file = export_file(project)
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 0
    state = result(capsys)["results"][0]
    with batch_import.project(Path(state["workspace"])):
        untracked = git("ls-files", "--others", "--exclude-standard")
        assert ".vita/" not in untracked
        assert git("show", "--format=", "--name-only", "HEAD") == "job.md"


def test_invalid_base_setting_is_actionable(project, capsys):
    (project / ".vita/config.json").write_text(json.dumps({"default_base_branch": 123}), encoding="utf-8")
    assert import_jobs.run("jobenu", export_file(project), dry_run=True, as_json=True) == 1
    assert "branch name string" in result(capsys)["error"]


def test_stopped_import_commit_has_private_log_and_can_resume(project, monkeypatch, capsys):
    file = export_file(project)
    original = batch_import.git.commit_paths
    monkeypatch.setattr(batch_import.git, "commit_paths", Mock(return_value=batch_import.git.GitResult(False, "", "Synthetic commit failure", 1)))
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 1
    state = result(capsys)["results"][0]
    assert "Synthetic commit failure" in Path(state["execution_log"]).read_text()
    assert not state["import_ready"]
    monkeypatch.setattr(batch_import.git, "commit_paths", original)
    assert import_jobs.run("jobenu", file, approval="auto", as_json=True) == 0
    restored = result(capsys)["results"][0]
    assert restored["workspace"] == state["workspace"] and restored["import_ready"]
