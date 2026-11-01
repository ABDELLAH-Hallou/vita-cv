"""Deterministic provider fallback; no HTTP, CLI generation or personal sources."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step, providers, run
from vita.commands import fallback as amend
from vita.helpers import evaluation, fallback, llm, requirements
from vita.helpers import factual_changes as facts
from vita.helpers.provider_errors import ProviderError
from vita.helpers.structured_output import StructuredOutputError, run_structured, run_text

LATEX = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}"
JD = "Python is required."
PRIMARY = {"provider": "gemini", "model": "primary-model"}
CODEX_ADAPTER = llm._call_codex_cli


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith(("VITA_", "EXTRACTION_", "ANALYSIS_", "ADAPT_", "REVIEW_", "COVER_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VITA_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("VITA_DIAGNOSTIC_CONTENT", "off")
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    monkeypatch.setenv("VITA_PROVIDER_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("VITA_PROVIDER_RETRY_MAX_SECONDS", "0")
    Path(".vita").mkdir()
    Path(".vita/config.json").write_text("{}", encoding="utf-8")
    Path("main.tex").write_text(LATEX % "Original Python CV", encoding="utf-8")
    Path("job.md").write_text(JD, encoding="utf-8")
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=AssertionError("No live HTTP")))
    monkeypatch.setattr(llm, "_call_codex_cli", Mock(side_effect=AssertionError("No live Codex")))
    return tmp_path


def enable(monkeypatch, **extra):
    for key, value in {"VITA_FALLBACK_ENABLED": "true", "VITA_FALLBACK_PROVIDER": "codex",
                       "VITA_FALLBACK_MODEL": "gpt-6.1-sol", **extra}.items():
        monkeypatch.setenv(key, value)


def outcome(step="adapt"):
    return json.loads(Path(f".vita/results/{step}.outcome.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("error", [None, "overloaded", "timeout", "rate_limit", "connection", "server_error"])
def test_primary_success_or_eligible_backup(project, monkeypatch, error):
    enable(monkeypatch, VITA_FALLBACK_REASONING_EFFORT="high")
    calls = []
    def fake(system, prompt, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1 and error:
            raise ProviderError(code=error, status=503)
        return "valid output"
    assert run_text(step="adapt", generate=fake, system="private prompt", prompt="secret CV", route=PRIMARY) == "valid output"
    assert len(calls) == (2 if error else 1)
    result = outcome()
    if error:
        assert calls[-1]["provider"] == "codex" and calls[-1]["model"] == "gpt-6.1-sol"
        assert calls[-1]["reasoning_effort"] == "high"
        assert [a["kind"] for a in result["attempts"]] == ["initial", "fallback"]
        assert result["attempts"][1]["parent_attempt_id"] == result["attempts"][0]["attempt_id"]
        assert result["attempts"][1]["fallback_reason"] == error
        assert result["routing"]["effective"]["model"] == "gpt-6.1-sol"
    assert "secret CV" not in json.dumps(result)


def test_shared_budget_exhaustion_has_no_loops(project, monkeypatch):
    enable(monkeypatch)
    fake = Mock(side_effect=ProviderError(code="overloaded"))
    with pytest.raises(StructuredOutputError):
        run_text(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY)
    result = outcome()
    assert [c.kwargs["provider"] for c in fake.call_args_list] == ["gemini", "codex", "codex"]
    assert [a["kind"] for a in result["attempts"]] == ["initial", "fallback", "retry"]
    assert result["attempt_count"] == result["max_attempts"] == 3
    assert result["error"]["exhausted"]


@pytest.mark.parametrize("category", ["authentication", "invalid_model", "quota_exceeded", "permission", "configuration", "refusal", "invalid_request"])
def test_ineligible_failures_do_not_use_backup(project, monkeypatch, category):
    enable(monkeypatch)
    fake = Mock(side_effect=ProviderError(code=category))
    with pytest.raises(StructuredOutputError):
        run_text(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY)
    assert fake.call_count == 1


@pytest.mark.parametrize("category", ["authentication", "invalid_model", "quota_exceeded", "permission"])
def test_nontransient_categories_require_explicit_selection(project, monkeypatch, category):
    enable(monkeypatch, VITA_FALLBACK_CATEGORIES=category)
    fake = Mock(side_effect=[ProviderError(code=category), "valid"])
    assert run_text(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY) == "valid"
    assert not outcome()["attempts"][0]["error"]["retryable"]
    assert outcome()["attempts"][1]["kind"] == "fallback"


@pytest.mark.parametrize("key,value", [("VITA_FALLBACK_MODEL", ""), ("VITA_FALLBACK_PROVIDER", "unknown"),
    ("VITA_FALLBACK_REASONING_EFFORT", "nonsense"), ("VITA_FALLBACK_CATEGORIES", "validation_error"),
    ("VITA_FALLBACK_ENABLED", "perhaps")])
def test_invalid_configuration_stops_before_generation(project, monkeypatch, key, value):
    enable(monkeypatch, **{key: value})
    fake = Mock(return_value="unused")
    with pytest.raises(StructuredOutputError):
        run_text(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY)
    fake.assert_not_called()
    assert outcome()["error"]["category"] == "configuration"


def test_settings_precedence_and_disabled_default(project, monkeypatch):
    assert not fallback.load_policy("adapt")["enabled"]
    Path(".vita/.env").write_text("VITA_FALLBACK_ENABLED=true\nVITA_FALLBACK_PROVIDER=codex\nVITA_FALLBACK_MODEL=file-model\nADAPT_FALLBACK_MODEL=stage-file-model\n", encoding="utf-8")
    assert fallback.load_policy("adapt")["backup"]["model"] == "stage-file-model"
    monkeypatch.setenv("ADAPT_FALLBACK_MODEL", "process-stage-model")
    assert fallback.load_policy("adapt")["backup"]["model"] == "process-stage-model"
    monkeypatch.setenv("ADAPT_FALLBACK_ENABLED", "false")
    assert not fallback.load_policy("adapt")["enabled"]
    assert fallback.load_policy("cover")["enabled"]
    assert not fallback.load_policy("provider-check")["enabled"]
    monkeypatch.setenv("ANALYSIS_FALLBACK_MODEL", "inherited-analysis-backup")
    assert fallback.load_policy("review")["backup"]["model"] == "inherited-analysis-backup"
    monkeypatch.setenv("REVIEW_FALLBACK_MODEL", "review-specific-backup")
    assert fallback.load_policy("review")["backup"]["model"] == "review-specific-backup"


def test_disabled_and_no_remaining_budget_never_switch(project, monkeypatch):
    fake = Mock(side_effect=ProviderError(code="overloaded"))
    with pytest.raises(StructuredOutputError):
        run_text(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY)
    assert all(c.kwargs["provider"] == "gemini" for c in fake.call_args_list)
    enable(monkeypatch, VITA_PROVIDER_MAX_ATTEMPTS="1")
    fake.reset_mock()
    with pytest.raises(StructuredOutputError):
        run_text(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY)
    assert fake.call_count == 1


def test_format_recovery_does_not_switch_or_publish_partial_output(project, monkeypatch):
    enable(monkeypatch)
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    fake = Mock(side_effect=['{"answer":', ProviderError(code="overloaded"), '{"answer":"backup"}'])
    save = Mock()
    result = run_structured(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY,
                            schema=schema, finalize=lambda x: x, save=save)
    assert result == {"answer": "backup"}
    save.assert_called_once_with(result)
    assert fake.call_args_list[0].args == fake.call_args_list[2].args
    assert "FORMAT RETRY" in fake.call_args_list[1].args[1]
    fake = Mock(return_value='{"answer":')
    with pytest.raises(StructuredOutputError):
        run_structured(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY,
                       schema=schema, finalize=lambda x: x, save=Mock())
    assert all(c.kwargs["provider"] == "gemini" for c in fake.call_args_list)


def test_concurrent_edit_before_backup_stops_generation(project, monkeypatch):
    enable(monkeypatch)
    def fake(*a, **k):
        Path("main.tex").write_text("Concurrent edit", encoding="utf-8")
        raise ProviderError(code="overloaded")
    generate = Mock(side_effect=fake)
    with pytest.raises(StructuredOutputError) as error:
        run_text(step="adapt", generate=generate, system="S", prompt="P", route=PRIMARY)
    assert error.value.code == "source_conflict"
    assert generate.call_count == 1
    assert fallback.outcome_view("adapt")["error"]["category"] == "source_conflict"


def test_concurrent_edit_during_backup_never_publishes(project, monkeypatch):
    enable(monkeypatch)
    calls = []
    def fake(*a, **k):
        calls.append(k["provider"])
        if k["provider"] == "gemini":
            raise ProviderError(code="overloaded")
        Path("main.tex").write_text("Concurrent edit", encoding="utf-8")
        return "backup output"
    with pytest.raises(StructuredOutputError) as error:
        run_text(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY)
    assert error.value.code == "source_conflict"
    assert calls == ["gemini", "codex"]
    assert Path("main.tex").read_text(encoding="utf-8") == "Concurrent edit"


def test_atomic_save_failure_is_not_a_fallback_reason(project, monkeypatch):
    enable(monkeypatch)
    fake = Mock(return_value='{"answer":"valid"}')
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    with pytest.raises(StructuredOutputError) as error:
        run_structured(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY,
                       schema=schema, finalize=lambda x: x, save=Mock(side_effect=OSError("synthetic")))
    assert error.value.code == "artifact_error" and fake.call_count == 1


def test_billing_and_same_provider_retry_after(project, monkeypatch):
    from vita.helpers import structured_output
    from vita.helpers.provider_errors import http_category
    assert http_category(402) == "quota_exceeded"
    enable(monkeypatch, VITA_FALLBACK_PROVIDER="gemini", VITA_FALLBACK_MODEL="backup-model")
    monkeypatch.setenv("VITA_PROVIDER_RETRY_MAX_SECONDS", "5")
    sleeps = Mock()
    monkeypatch.setattr(structured_output.time, "sleep", sleeps)
    fake = Mock(side_effect=[ProviderError(code="rate_limit", retry_after=4), "valid"])
    assert run_text(step="adapt", generate=fake, system="S", prompt="P", route=PRIMARY) == "valid"
    sleeps.assert_called_once_with(4)


def test_codex_explicit_billing_status_is_classified(project, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(llm, "_find_codex_cli", lambda: "synthetic-codex")
    monkeypatch.setattr(llm.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=1, stderr="HTTP 402 payment required", stdout="")))
    with pytest.raises(ProviderError) as error:
        CODEX_ADAPTER("Synthetic", "No candidate data", "primary-model")
    assert error.value.code == "quota_exceeded" and error.value.status == 402


def test_codex_backup_uses_login_without_api_key(project, monkeypatch):
    enable(monkeypatch, VITA_FALLBACK_REASONING_EFFORT="high")
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_call_gemini", Mock(side_effect=ProviderError(code="overloaded")))
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-private-key")
    codex = Mock(return_value="backup result")
    monkeypatch.setattr(llm, "_call_codex_cli", codex)
    assert run_text(step="adapt", generate=llm.generate, system="S", prompt="P", route=PRIMARY) == "backup result"
    assert codex.call_args.args[2] == "gpt-6.1-sol"
    assert codex.call_args.kwargs["reasoning_effort"] == "high"
    assert "synthetic-private-key" not in json.dumps(outcome())
    assert "synthetic-private-key" not in json.dumps(fallback.outcome_view("adapt"))


def test_backup_preparation_preserves_primary_registry(project, monkeypatch):
    enable(monkeypatch)
    Path(".vita/config.json").write_text('{"auto_add_codex_provider":true}', encoding="utf-8")
    original = '{"llm_providers":{"gemini":{"model":"primary-model"}}}'
    Path(".vita/extensions.json").write_text(original, encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    monkeypatch.setattr(llm, "_call_gemini", Mock(return_value="primary success"))
    assert run_text(step="adapt", generate=llm.generate, system="S", prompt="P", route=PRIMARY) == "primary success"
    assert Path(".vita/extensions.json").read_text(encoding="utf-8") == original
    llm._call_codex_cli.assert_not_called()


def test_missing_backup_api_credential_fails_before_generation(project, monkeypatch):
    enable(monkeypatch, VITA_FALLBACK_PROVIDER="openai", VITA_FALLBACK_MODEL="backup-model")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    primary = Mock(return_value="primary")
    monkeypatch.setattr(llm, "_call_gemini", primary)
    with pytest.raises(StructuredOutputError):
        run_text(step="adapt", generate=llm.generate, system="S", prompt="P", route=PRIMARY)
    primary.assert_not_called()
    assert outcome()["attempt_count"] == 0 and outcome()["error"]["category"] == "configuration"


def test_generation_check_remains_exact(project, monkeypatch, capsys):
    enable(monkeypatch)
    monkeypatch.setattr(llm, "_call_gemini", Mock(side_effect=ProviderError(code="overloaded")))
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-private-key")
    assert not providers.run(provider="gemini", model="primary-model", generate=True, as_json=True)
    llm._call_codex_cli.assert_not_called()
    assert json.loads(capsys.readouterr().out)["provider"] == "gemini"


def test_assessment_records_real_backup_provenance_without_primary_cache_reuse(project, monkeypatch, evaluation_report):
    enable(monkeypatch, VITA_FALLBACK_REASONING_EFFORT="high")
    data = canonical()
    monkeypatch.setenv("ANALYSIS_PROVIDER", "gemini")
    monkeypatch.setenv("ANALYSIS_MODEL", "primary-model")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    report = evaluation_report("missing")
    report["metrics"]["criteria"] = [
        {**{k: unit[k] for k in evaluation.TAXONOMY_FIELDS}, "status": "missing", "evidence": "", "feedback": "Add evidence."}
        for unit in data["requirements"]]
    monkeypatch.setattr(llm, "_call_gemini", Mock(side_effect=ProviderError(code="overloaded")))
    codex = Mock(return_value=json.dumps(report))
    monkeypatch.setattr(llm, "_call_codex_cli", codex)
    monkeypatch.setattr(ai_step, "llm_generate", llm.generate)
    assert ai_step.run("analyze", auto=True)
    saved = json.loads(Path(".vita/results/analysis.json").read_text(encoding="utf-8"))
    provenance = saved["metadata"]["assessment"]
    assert provenance["requested_provider"] == "gemini" and provenance["provider"] == "codex"
    assert provenance["model"] == "gpt-6.1-sol" and provenance["reasoning_effort"] == "high"
    assert provenance["route_source"] == "resolved"
    assert saved["metadata"]["assessment_execution"]["operation_run_id"] == outcome("analyze")["run_id"]
    assert ai_step.run("analyze", auto=True)
    assert codex.call_count == 2  # A backup assessment is never mislabeled as a primary cache hit.


def canonical():
    proposal = {"schema_version": 1, "items": [{"job_id": "job-1", "key": "python", "text": "Python",
        "kind": "capability", "category": "hard_skills", "classification": "required", "ambiguity": "",
        "source_refs": [{"job_id": "job-1", "line_start": 1, "line_end": 1, "quote": "Python"}]}]}
    data = requirements.save_revision(requirements.compile_revision(proposal, JD))
    requirements.approve_revision(data["revision"], JD)
    return data


def pipeline_provider(monkeypatch, evaluation_report, *, backup_fails=False):
    for stage in ("ANALYSIS", "ADAPT", "REVIEW", "COVER"):
        monkeypatch.setenv(stage + "_PROVIDER", "gemini")
        monkeypatch.setenv(stage + "_MODEL", "primary-model")
    data = canonical()
    cover_inputs = []
    def fake(system, prompt, **kw):
        if "You MUST output the complete" in prompt:
            if "You MUST output the complete cover-letter.tex" in prompt:
                cover_inputs.append(Path("main.tex").read_text(encoding="utf-8"))
                if kw["provider"] == "gemini" or backup_fails:
                    raise ProviderError(code="overloaded")
                return "```latex\n" + LATEX % "Matching Python letter" + "\n```"
            return "```latex\n" + LATEX % "Applied Python CV" + "\n```"
        report = evaluation_report("missing")
        report["metrics"]["criteria"] = [
            {**{k: unit[k] for k in evaluation.TAXONOMY_FIELDS}, "status": "missing", "evidence": "", "feedback": "Add evidence."}
            for unit in data["requirements"]]
        return json.dumps(report)
    generate = Mock(side_effect=fake)
    monkeypatch.setattr(ai_step, "llm_generate", generate)
    return generate, cover_inputs


def test_failed_step_amendment_preserves_completed_stages_and_approvals(project, monkeypatch, capsys, evaluation_report):
    generate, sources = pipeline_provider(monkeypatch, evaluation_report)
    assert not run.run(auto=True, approval="unattended")
    old = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    assert old["completed_steps"] == ["analyze", "adapt", "review"]
    assert old["current_step"] == "cover"
    decision = facts.load("adapt")["approval"]
    capsys.readouterr()
    assert amend.run("cover", provider="codex", model="gpt-6.1-sol", as_json=True) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["preserved_steps"] == old["completed_steps"]
    assert amend.run("cover", provider="codex", model="gpt-6.1-sol", apply=True, plan_id=plan["plan_id"], as_json=True) == 0
    capsys.readouterr()
    changed = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    assert changed["checkpoint"] == old["checkpoint"]
    generate.reset_mock()
    assert run.run(auto=True, approval="unattended", resume=True)
    assert generate.call_count == 2
    assert all("Applied Python CV" in source for source in sources)
    assert facts.load("adapt")["approval"] == decision
    current = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    assert current["authorization"]["run_id"] == old["authorization"]["run_id"]
    assert current["operation_outcomes"]["cover"]["parent_run_id"] == old["operation_outcomes"]["cover"]["run_id"]
    generate.reset_mock()
    assert run.run(auto=True, approval="unattended", resume=True)
    generate.assert_not_called()


def test_stale_amendment_and_repeated_failure_keep_lineage(project, monkeypatch, capsys, evaluation_report):
    generate, _ = pipeline_provider(monkeypatch, evaluation_report, backup_fails=True)
    assert not run.run(auto=True, approval="unattended")
    capsys.readouterr()
    assert amend.run("cover", provider="codex", model="gpt-6.1-sol", as_json=True) == 0
    plan = json.loads(capsys.readouterr().out)
    assert amend.run("cover", provider="codex", model="different-model", apply=True, plan_id=plan["plan_id"], as_json=True) == 1
    capsys.readouterr()
    assert amend.run("cover", provider="codex", model="gpt-6.1-sol", apply=True, plan_id=plan["plan_id"], as_json=True) == 0
    capsys.readouterr()
    previous = outcome("cover")["run_id"]
    assert not run.run(auto=True, approval="unattended", resume=True)
    assert outcome("cover")["parent_run_id"] == previous
    assert not Path("cover-letter.tex").exists()
    # An edited adapted source blocks both ordinary resume and amendment.
    Path("main.tex").write_text("Concurrent user edit", encoding="utf-8")
    generate.reset_mock()
    assert not run.run(auto=True, approval="unattended", resume=True)
    generate.assert_not_called()
    capsys.readouterr()
    assert amend.run("cover", provider="codex", model="gpt-6.1-sol", as_json=True) == 1


def test_capability_discovery_is_native_json(project, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["vita", "fallback", "capabilities", "--json"])
    main()
    caps = json.loads(capsys.readouterr().out)
    assert caps["version"] == fallback.VERSION and caps["max_backups"] == 1
    assert not caps["default_enabled"]
    assert caps["shared_attempt_budget"]["maximum"] == 5


def test_corrupt_prior_outcome_has_safe_native_failure(project, monkeypatch, capsys):
    Path(".vita/results").mkdir()
    Path(".vita/results/adapt.outcome.json").write_text('{"secret":"private-provider-response"}', encoding="utf-8")
    provider = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    monkeypatch.setattr(sys, "argv", ["vita", "adapt", "--auto", "--json"])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed" and result["operation"] is None
    assert "private-provider-response" not in json.dumps(result)
    provider.assert_not_called()


def test_rejected_and_invalid_tex_proposals_do_not_switch(project, monkeypatch):
    enable(monkeypatch)
    canonical()
    document = LATEX % "Rejected generated wording"
    assert not facts.stage(facts.capture("adapt"), document)
    facts.decide("adapt", facts.load("adapt")["revision"], False)
    provider = Mock(return_value="```latex\n" + document + "\n```")
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert not ai_step.run("adapt", auto=True, approval="unattended")
    assert facts.load("adapt")["status"] == "rejected"
    assert provider.call_count == 1
    provider.reset_mock()
    provider.return_value = "```latex\n" + LATEX % r"\textbf{Broken group" + "\n```"
    assert not ai_step.run("adapt", auto=True, approval="unattended")
    assert provider.call_count == 1
    assert facts.load("adapt")["application_status"] == "not_applied"


def test_backup_publication_failure_resumes_saved_draft_without_generation(project, monkeypatch, evaluation_report):
    enable(monkeypatch)
    generate, _ = pipeline_provider(monkeypatch, evaluation_report)
    write = facts.write_artifact
    def fail_letter(path, text):
        if path == Path("cover-letter.tex"):
            raise OSError("Synthetic atomic publication failure")
        return write(path, text)
    monkeypatch.setattr(facts, "write_artifact", fail_letter)
    assert not run.run(auto=True, approval="unattended")
    state = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    assert state["pending"]["step"] == "cover" and state["status"] == "failed"
    assert state["operation_outcomes"]["cover"]["routing"]["effective"]["provider"] == "codex"
    draft = facts.load("cover")
    assert draft["status"] == "approved" and draft["application_status"] == "not_applied"
    monkeypatch.setattr(facts, "write_artifact", write)
    generate.reset_mock()
    assert run.run(auto=True, approval="unattended", resume=True)
    generate.assert_not_called()
    assert facts.load("cover")["revision"] == draft["revision"]


def test_fresh_restart_has_new_run_and_matching_source(project, monkeypatch, evaluation_report):
    enable(monkeypatch)
    pipeline_provider(monkeypatch, evaluation_report, backup_fails=True)
    assert not run.run(auto=True, approval="unattended")
    old = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    generate, sources = pipeline_provider(monkeypatch, evaluation_report)
    assert run.run(auto=True, approval="unattended")
    new = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    assert old["authorization"]["run_id"] != new["authorization"]["run_id"]
    assert generate.call_count >= 3 and all("Applied Python CV" in text for text in sources)
    assert list(Path(".vita/workflows").glob("*.json"))
