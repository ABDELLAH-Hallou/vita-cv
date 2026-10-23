"""Contracts, cache invalidation, routing, and end-to-end evaluator deltas."""

import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.commands import ai_step, run
from vita.helpers import env, evaluation, job_extraction, llm
from vita.helpers.job_extraction import fingerprint, prepare_job
from vita.helpers.pipeline_config import STAGE_PREFIXES, load_pipeline_settings
from vita.helpers.structured import EVALUATION_SCHEMA, JOB_SCHEMA, parse_json, validate
from vita.helpers.toon import encode_job


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for prefix in STAGE_PREFIXES.values():
        for suffix in ("PROVIDER", "MODEL"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    monkeypatch.delenv("ENABLE_JD_EXTRACTION", raising=False)
    Path(".vita").mkdir()
    Path("main.tex").write_text(r"\documentclass{article}\begin{document}Original CV\end{document}", encoding="utf-8")
    Path("job.md").write_text("Acme needs Python. RAW_ONLY_MARKER", encoding="utf-8")
    return tmp_path


@pytest.fixture
def job_data(workspace):
    return {
        "schema_version": 1, "source_sha256": fingerprint(Path("job.md").read_text(encoding="utf-8")),
        "jobs": [{"id": "job-1", "title": "Engineer", "company": "Acme", "location": None,
                  "date_posted": None, "hard_skills": ["Python"], "soft_skills": [],
                  "requirements": {"must_have": ["Python"], "nice_to_have": []},
                  "responsibilities": ["Build services"], "summary": "Python engineering"}],
    }


def cache(data):
    Path(".vita/results").mkdir(exist_ok=True)
    Path(".vita/results/job.json").write_text(json.dumps(data), encoding="utf-8")


def test_env_comments_quotes_process_precedence_and_no_cross_project_leak(workspace, monkeypatch):
    Path(".vita/.env").write_text(
        'ENABLE_JD_EXTRACTION=true # enable\nEXTRACTION_PROVIDER="openrouter" # route\n'
        "EXTRACTION_MODEL='vendor/model'\nOPENAI_API_KEY=with#hash\n", encoding="utf-8"
    )
    assert env.read_env_file()["OPENAI_API_KEY"] == "with#hash"
    settings = load_pipeline_settings()
    assert settings.extraction_enabled
    assert settings.route("extract").model == "vendor/model"
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    assert not load_pipeline_settings().extraction_enabled
    monkeypatch.delenv("ENABLE_JD_EXTRACTION")
    Path(".vita/.env").write_text("", encoding="utf-8")
    assert not load_pipeline_settings().extraction_enabled
    assert load_pipeline_settings().route("extract").provider == "gemini"


@pytest.mark.parametrize("toggle,expected", [("true", True), ("FALSE", False), ("1", True), ("off", False)])
def test_extraction_toggle(workspace, monkeypatch, toggle, expected):
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", toggle)
    assert load_pipeline_settings().extraction_enabled is expected


def test_invalid_toggle_fails_without_model_call(workspace, monkeypatch):
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "sometimes")
    generate = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", generate)
    assert run.run(auto=True) is False
    generate.assert_not_called()


def test_stage_routing_and_provider_override_do_not_mix_vendor_models(workspace, monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "openai")
    monkeypatch.setenv("ANALYSIS_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("ADAPT_PROVIDER", "codex")
    monkeypatch.setenv("COVER_MODEL", "configured-cover")
    settings = load_pipeline_settings()
    assert settings.route("review") == settings.route("analyze")
    assert settings.route("analyze", "gemini").model is None
    assert settings.route("analyze", "openai").model == "gpt-4o-mini"
    assert settings.route("adapt").provider == "codex"
    assert settings.route("cover").model == "configured-cover"
    monkeypatch.setenv("REVIEW_PROVIDER", "openrouter")
    assert load_pipeline_settings().route("review").model is None


@pytest.mark.parametrize("provider,url,model", [
    ("openai", "https://api.openai.com/v1/chat/completions", "gpt-4.1-nano"),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions", "vendor/model"),
])
def test_direct_provider_adapters_without_extensions_entry(workspace, monkeypatch, provider, url, model):
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"gemini": {"model": "existing"}})
    monkeypatch.setattr(llm, "load_env", lambda: {f"{provider.upper()}_API_KEY": "test-secret"})
    post = Mock(return_value={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
    monkeypatch.setattr(llm, "_post", post)
    assert llm.generate("system", "prompt", provider=provider, model=model) == "{}"
    actual_url, headers, body = post.call_args.args
    assert actual_url == url
    assert headers["Authorization"] == "Bearer test-secret"
    assert body["model"] == model
    assert "temperature" not in body


def test_existing_gemini_config_and_stage_override(workspace, monkeypatch):
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"gemini": {"model": "existing-model"}})
    monkeypatch.setattr(llm, "load_env", lambda: {"GEMINI_API_KEY": "test-key"})
    backend = Mock(return_value="result")
    monkeypatch.setattr(llm, "_call_gemini", backend)
    llm.generate("s", "u")
    assert backend.call_args.args[-1] == "existing-model"
    llm.generate("s", "u", model="gemini-2.5-flash")
    assert backend.call_args.args[-1] == "gemini-2.5-flash"


def test_extraction_only_sends_job_and_preserves_json_toon(workspace, monkeypatch, job_data):
    provider = Mock(return_value=json.dumps(job_data))
    monkeypatch.setattr(job_extraction, "generate", provider)
    assert ai_step.run("extract", auto=True)
    system, prompt = provider.call_args.args
    assert "Original CV" not in system + prompt
    assert "RAW_ONLY_MARKER" in prompt
    assert {key: provider.call_args.kwargs[key] for key in ("provider", "model")} == {
        "provider": "gemini", "model": "gemini-2.5-flash",
    }
    assert provider.call_args.kwargs["response_schema"] == JOB_SCHEMA
    saved = parse_json(Path(".vita/results/job.json").read_text(encoding="utf-8"))
    assert saved == job_data
    assert Path(".vita/results/job.toon").read_text(encoding="utf-8") == encode_job(saved)


def test_disabled_extraction_uses_valid_cache_and_repairs_toon(workspace, monkeypatch, job_data):
    cache(job_data)
    Path(".vita/results/job.toon").write_text("STALE", encoding="utf-8")
    provider = Mock()
    monkeypatch.setattr(job_extraction, "generate", provider)
    context = prepare_job(load_pipeline_settings(), auto=True)
    assert context.structured
    assert "RAW_ONLY_MARKER" not in context.text
    assert "hard_skills[1]: Python" in context.text
    assert "STALE" not in Path(".vita/results/job.toon").read_text(encoding="utf-8")
    provider.assert_not_called()


def test_changed_job_or_invalid_cache_falls_back_to_raw_when_disabled(workspace, monkeypatch, job_data):
    cache(job_data)
    Path("job.md").write_text("Different employer", encoding="utf-8")
    provider = Mock()
    monkeypatch.setattr(job_extraction, "generate", provider)
    assert "Different employer" in prepare_job(load_pipeline_settings(), auto=True).text
    Path(".vita/results/job.json").write_text("invalid JSON", encoding="utf-8")
    assert not prepare_job(load_pipeline_settings(), auto=True).structured
    provider.assert_not_called()


def test_enabled_extraction_failure_stops_pipeline_and_preserves_cache(workspace, monkeypatch, job_data):
    cache(job_data)
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "true")
    monkeypatch.setattr(job_extraction, "generate", Mock(return_value='{"jobs": []}'))
    evaluator = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", evaluator)
    assert run.run(auto=True) is False
    evaluator.assert_not_called()
    assert parse_json(Path(".vita/results/job.json").read_text(encoding="utf-8")) == job_data


@pytest.mark.parametrize("enabled", [True, False])
def test_pipeline_toggle_dual_outputs_and_comparable_delta(workspace, monkeypatch, job_data, evaluation_report, enabled, human_confirmed_edits):
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", str(enabled).lower())
    monkeypatch.setenv("EXTRACTION_PROVIDER", "openrouter")
    monkeypatch.setenv("EXTRACTION_MODEL", "vendor/fast")
    monkeypatch.setenv("ANALYSIS_PROVIDER", "openai")
    monkeypatch.setenv("ANALYSIS_MODEL", "gpt-4o")
    extractor = Mock(return_value=json.dumps(job_data))
    monkeypatch.setattr(job_extraction, "generate", extractor)
    calls = []

    def generate(system, prompt, **kwargs):
        calls.append((system, prompt, kwargs))
        if enabled:
            assert "JOB METADATA (TOON)" in prompt
            assert "RAW_ONLY_MARKER" not in prompt + system
        else:
            assert "RAW_ONLY_MARKER" in prompt
        if "STRUCTURED EVALUATION CONTRACT" in prompt:
            if len(calls) == 1:
                return json.dumps(evaluation_report("partial"))
            assert "Adapted CV" in system + prompt
            assert "LOCKED JD CRITERIA" in prompt
            return json.dumps(evaluation_report("matched"))
        return "```latex\n\\documentclass{article}\n\\begin{document}\nAdapted CV\n\\end{document}\n```"

    monkeypatch.setattr(ai_step, "llm_generate", generate)
    assert run.run(auto=True, language="fr")
    assert extractor.call_count == int(enabled)
    if enabled:
        assert {key: extractor.call_args.kwargs[key] for key in ("provider", "model")} == {
            "provider": "openrouter", "model": "vendor/fast",
        }
    for call in (calls[0], calls[2]):
        assert {key: call[2][key] for key in ("provider", "model")} == {"provider": "openai", "model": "gpt-4o"}
        assert "response_schema" in call[2]
    before = parse_json(Path(".vita/results/analysis.json").read_text(encoding="utf-8"))
    after = parse_json(Path(".vita/results/review.json").read_text(encoding="utf-8"))
    assert set(before) == set(after)
    validate(before, EVALUATION_SCHEMA)
    validate(after, EVALUATION_SCHEMA)
    delta = parse_json(Path(".vita/results/delta.json").read_text(encoding="utf-8"))
    assert delta["overall_score"] == {"before": 50, "after": 100, "delta": 50}
    assert "| Hard Skills | 100.00 |" in Path(".vita/results/review.md").read_text(encoding="utf-8")
    assert Path(".vita/results/analysis.md").read_text(encoding="utf-8") == Path(".vita/results/analyze.md").read_text(encoding="utf-8")


def test_manual_enabled_pipeline_does_not_call_provider_and_orders_extraction(workspace, monkeypatch):
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "true")
    provider = Mock()
    monkeypatch.setattr(job_extraction, "generate", provider)
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert run.run()
    provider.assert_not_called()
    index = Path(".vita/current_prompt.md").read_text(encoding="utf-8")
    assert index.index("extract.md") < index.index("analyze.md")
    for task in ("analyze", "adapt", "review"):
        prompt = Path(f".vita/prompts/{task}.md").read_text(encoding="utf-8")
        assert "job.toon" in prompt
        assert "RAW_ONLY_MARKER" not in prompt


@pytest.mark.parametrize("bad", ['{"x":1,"x":2}', '{"x":NaN}', 'Text {"x":1}', '[]'])
def test_reject_ambiguous_or_non_json_output(bad):
    with pytest.raises(ValueError):
        parse_json(bad)


@pytest.mark.parametrize("score", [True, "80", -1, 101, float("inf")])
def test_evaluation_scores_require_finite_numeric_range(evaluation_report, score):
    report = evaluation_report()
    report["overall_score"] = score
    with pytest.raises(ValueError):
        evaluation.validate_evaluation(report)


def test_review_cannot_change_taxonomy_and_delta_rejects_different_job(workspace, evaluation_report):
    job = prepare_job(load_pipeline_settings(), auto=True)
    before = evaluation.finalize(json.dumps(evaluation_report("partial")), job)
    altered = evaluation_report()
    altered["metrics"]["criteria"][0]["criterion"] = "Easier requirement"
    with pytest.raises(ValueError, match="baseline criteria"):
        evaluation.finalize(json.dumps(altered), job, before)
    after = evaluation.finalize(json.dumps(evaluation_report()), job, before)
    after["metadata"]["job_sha256"] = "other-job"
    with pytest.raises(ValueError, match="different jobs"):
        evaluation.compute_delta(before, after)


def test_bad_evaluation_does_not_overwrite_successful_reports(workspace, monkeypatch, evaluation_report):
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value=json.dumps(evaluation_report())))
    assert ai_step.run("analyze", auto=True)
    original = Path(".vita/results/analysis.json").read_bytes()
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value="invalid output"))
    assert ai_step.run("analyze", auto=True) is False
    assert Path(".vita/results/analysis.json").read_bytes() == original


def test_toon_quotes_delimiters_controls_and_preserves_unicode(job_data):
    data = copy.deepcopy(job_data)
    data["jobs"][0]["hard_skills"] = ["Python", "SQL, BI", "true", "42", "C:\\bin", "#tag", "line\nbreak", "équipe", "\b", r"\b"]
    validate(data, JOB_SCHEMA)
    text = encode_job(data)
    assert 'hard_skills[10]: Python,"SQL, BI","true","42","C:\\\\bin","#tag","line\\nbreak",équipe,"\\u0008","\\\\b"' in text
    assert "soft_skills: []" in text
    assert "jobs[1]:\n  - id: job-1" in text
    assert not text.endswith("\n")


def test_multiple_jobs_preserve_order_and_require_complete_evaluation(workspace, job_data, evaluation_report):
    raw = "# Job 1\nPython engineer\n# Job 2\nData engineer with SQL"
    Path("job.md").write_text(raw, encoding="utf-8")
    job_data["source_sha256"] = fingerprint(raw)
    second = copy.deepcopy(job_data["jobs"][0])
    second.update(id="job-2", title="Data engineer", hard_skills=["SQL"])
    job_data["jobs"].append(second)
    job_extraction.validate_job(job_data, raw)
    cache(job_data)
    job = prepare_job(load_pipeline_settings(), auto=True)
    assert job.ids == ("job-1", "job-2")
    assert "jobs[2]:" in job.text
    report = evaluation.finalize(json.dumps(evaluation_report(job_ids=job.ids)), job)
    assert report["metrics"]["total_count"] == 2
    with pytest.raises(ValueError, match="every supplied job"):
        evaluation.finalize(json.dumps(evaluation_report()), job)
    job_data["jobs"].reverse()
    with pytest.raises(ValueError, match="ordered ID"):
        job_extraction.validate_job(job_data, raw)


def test_delta_supports_regression_and_new_analysis_clears_old_delta(workspace, monkeypatch, evaluation_report):
    job = prepare_job(load_pipeline_settings(), auto=True)
    before = evaluation.finalize(json.dumps(evaluation_report()), job)
    after = evaluation.finalize(json.dumps(evaluation_report("missing")), job, before)
    delta = evaluation.compute_delta(before, after)
    assert delta["overall_score"]["delta"] == -100
    evaluation.save_delta(delta)
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value=json.dumps(evaluation_report())))
    assert ai_step.run("analyze", auto=True)
    assert not Path(".vita/results/delta.json").exists()
    assert not Path(".vita/results/delta.md").exists()


def test_extraction_custom_skill_is_task_scoped(workspace, monkeypatch, job_data, evaluation_report):
    Path(".vita/skills/extract").mkdir(parents=True)
    Path(".vita/skills/extract/taxonomy.md").write_text("EXTRACT_ONLY_GUIDANCE", encoding="utf-8")
    extractor = Mock(return_value=json.dumps(job_data))
    monkeypatch.setattr(job_extraction, "generate", extractor)
    assert ai_step.run("extract", auto=True)
    assert "EXTRACT_ONLY_GUIDANCE" in extractor.call_args.args[0]
    evaluator = Mock(return_value=json.dumps(evaluation_report()))
    monkeypatch.setattr(ai_step, "llm_generate", evaluator)
    assert ai_step.run("analyze", auto=True)
    assert "EXTRACT_ONLY_GUIDANCE" not in " ".join(evaluator.call_args.args)


@pytest.mark.parametrize("choice", [
    {"finish_reason": "length", "message": {"content": "truncated"}},
    {"finish_reason": "content_filter", "message": {"content": ""}},
    {"finish_reason": "stop", "message": {"content": None, "refusal": "Unavailable"}},
])
def test_provider_incomplete_response_is_rejected(monkeypatch, choice):
    monkeypatch.setattr(llm, "_post", Mock(return_value={"choices": [choice]}))
    with pytest.raises(RuntimeError):
        llm._call_openai("s", "u", "test-key", "model")


def test_huge_numeric_score_rejected_without_overflow(evaluation_report):
    report = evaluation_report()
    report["overall_score"] = 10 ** 400
    with pytest.raises(ValueError):
        evaluation.validate_evaluation(report)


def test_standalone_analysis_extracts_once_and_reuses_cache(workspace, monkeypatch, job_data, evaluation_report):
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "true")
    extractor = Mock(return_value=json.dumps(job_data))
    monkeypatch.setattr(job_extraction, "generate", extractor)
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value=json.dumps(evaluation_report())))
    assert ai_step.run("analyze", auto=True)
    assert ai_step.run("analyze", auto=True)
    extractor.assert_called_once()


def test_standalone_analysis_stops_when_enabled_extraction_fails(workspace, monkeypatch):
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "true")
    monkeypatch.setattr(job_extraction, "generate", Mock(return_value="bad JSON"))
    evaluator = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", evaluator)
    assert ai_step.run("analyze", auto=True) is False
    evaluator.assert_not_called()


def test_edited_context_invalidates_comparison(workspace, job_data, evaluation_report):
    cache(job_data)
    job = prepare_job(load_pipeline_settings(), auto=True)
    report = evaluation.finalize(json.dumps(evaluation_report()), job)
    evaluation.save_evaluation("analyze", report)
    assert evaluation.load_baseline(job) == report
    job_data["jobs"][0]["requirements"]["must_have"].append("SQL")
    cache(job_data)
    updated = prepare_job(load_pipeline_settings(), auto=True)
    assert evaluation.load_baseline(updated) is None
