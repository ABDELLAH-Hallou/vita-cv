"""Issue #37: synthetic failure replay; never call a live AI provider."""

import copy
import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step, run
from vita.helpers import job_extraction, llm
from vita.helpers.evaluation import finalize, save_evaluation
from vita.helpers.job_extraction import fingerprint, prepare_job
from vita.helpers.pipeline_config import STAGE_PREFIXES, load_pipeline_settings
from vita.helpers.provider_errors import ProviderError, UnsupportedSchema
from vita.helpers.structured import (
    EVALUATION_OUTPUT_SCHEMA,
    JOB_SCHEMA,
    generation_schema,
    parse_json,
)

MALFORMED = '{"schema_version": 1 "overall_score": 50}'  # Sanitized fixture from issue #37.


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for prefix in STAGE_PREFIXES.values():
        for suffix in ("PROVIDER", "MODEL"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    Path(".vita").mkdir()
    Path("main.tex").write_text("Synthetic Python engineer CV", encoding="utf-8")
    Path("job.md").write_text("Python engineer needed", encoding="utf-8")
    monkeypatch.setattr(llm, "load_env", lambda: {"OPENAI_API_KEY": "test-secret", "GEMINI_API_KEY": "test-secret",
                                               "OPENROUTER_API_KEY": "test-secret", "GROQ_API_KEY": "test-secret"})
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"codex": {"model": "gpt-6.1-sol", "reasoning_effort": "low"}})
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=AssertionError("No live HTTP")))
    monkeypatch.setattr(llm.subprocess, "run", Mock(side_effect=AssertionError("No live Codex")))
    return tmp_path


def outcome(step="analyze"):
    return parse_json(Path(f".vita/results/{step}.outcome.json").read_text(encoding="utf-8"))


def cached_job():
    data = {"schema_version": 1, "source_sha256": fingerprint(Path("job.md").read_text(encoding="utf-8")),
            "jobs": [{"id": "job-1", "title": "Engineer", "company": None, "location": None,
                      "date_posted": None, "hard_skills": ["Python"], "soft_skills": [],
                      "requirements": {"must_have": ["Python"], "nice_to_have": []},
                      "responsibilities": [], "summary": "Python engineering"}]}
    Path(".vita/results").mkdir(exist_ok=True)
    Path(".vita/results/job.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def test_issue37_codex_replay_recovers_and_completes_pipeline(project, monkeypatch, evaluation_report, human_confirmed_edits):
    cached_job()
    original_cache = Path(".vita/results/job.json").read_bytes()
    monkeypatch.setattr(llm, "_find_codex_cli", lambda: "mock-codex")
    calls = []
    schemas = []

    def codex(cmd, **kwargs):
        calls.append((cmd, kwargs["input"]))
        if "--output-schema" in cmd:
            schemas.append(json.loads(Path(cmd[cmd.index("--output-schema") + 1]).read_text(encoding="utf-8")))
            response = MALFORMED if len(schemas) == 1 else json.dumps(evaluation_report())
        else:
            response = "```latex\n\\documentclass{article}\n\\begin{document}\nSynthetic Python engineer\n\\end{document}\n```"
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(response, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(llm.subprocess, "run", codex)
    assert run.run(auto=True, provider="codex")
    record = outcome()
    assert record["status"] == "success" and record["recovered"] is True
    assert [item["category"] for item in record["attempts"]] == ["invalid_json", "valid"]
    assert record["attempts"][0]["location"]["column"] == 22
    assert len(calls) == 5  # analyze twice, adapt, review, cover; no re-extraction.
    assert all(schema == generation_schema(EVALUATION_OUTPUT_SCHEMA) for schema in schemas)
    for cmd, _ in calls:
        assert cmd[cmd.index("--model") + 1] == "gpt-6.1-sol"
        assert cmd[cmd.index("--config") + 1] == 'model_reasoning_effort="low"'
        assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "Do not invent candidate facts" in calls[1][1]
    assert Path(".vita/results/job.json").read_bytes() == original_cache
    assert Path(".vita/results/analysis.json").is_file()
    assert Path(".vita/results/review.json").is_file()
    assert Path(".vita/results/delta.json").is_file()
    assert not list(Path(".vita/tmp").glob("codex-*"))
    for item in record["attempts"]:
        assert item["route"] == {"provider": "codex", "model": "gpt-6.1-sol", "reasoning_effort": "low"}
        assert item["mode"] == "native_schema"


@pytest.mark.parametrize("bad,category", [
    (MALFORMED, "invalid_json"), ('{"a":1,"a":2}', "invalid_json"), ('{"a":NaN}', "invalid_json"),
    ('[]', "invalid_json"), ('', "invalid_json"), ('{}', "schema_error"),
])
def test_exhaustion_is_bounded_and_preserves_artifacts(project, monkeypatch, evaluation_report, bad, category):
    cached_job()
    job = prepare_job(load_pipeline_settings(), auto=False)
    save_evaluation("analyze", finalize(json.dumps(evaluation_report()), job))
    protected = {path: path.read_bytes() for path in Path(".vita/results").glob("*") if path.is_file()}
    original_cv = Path("main.tex").read_bytes()
    provider = Mock(return_value=bad)
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert run.run(auto=True, provider="codex") is False
    assert provider.call_count == 3
    assert all(path.read_bytes() == contents for path, contents in protected.items())
    assert Path("main.tex").read_bytes() == original_cv
    record = outcome()
    assert record["status"] == "failed"
    assert record["error"]["code"] == "structured_output_invalid"
    assert "rerun this step" in record["error"]["action"]
    assert [item["category"] for item in record["attempts"]] == [category] * 3
    assert not Path(".vita/results/adapt.md").exists()


@pytest.mark.parametrize("fault", ["score", "job", "metadata", "comparison", "qualitative_summary", "taxonomy", "evidence"])
def test_host_checks_remain_authoritative(project, monkeypatch, evaluation_report, fault):
    cached_job()
    job = prepare_job(load_pipeline_settings(), auto=False)
    baseline = finalize(json.dumps(evaluation_report()), job)
    save_evaluation("analyze", baseline)
    invalid = evaluation_report()
    if fault == "score":
        invalid["overall_score"] = 101
    elif fault == "job":
        invalid["metrics"]["criteria"][0]["job_id"] = "unrelated-job"
    elif fault == "metadata":
        invalid["metadata"] = baseline["metadata"]
    elif fault == "comparison":
        invalid["comparison"] = {"status": "available", "baseline_overall_score": 3, "overall_delta": 97}
    elif fault == "qualitative_summary":
        invalid["qualitative_summary"] = "Forged summary"
    elif fault == "taxonomy":
        invalid["metrics"]["criteria"][0]["criterion"] = "Easier criterion"
    else:
        invalid["metrics"]["criteria"][0]["evidence"] = ""
    provider = Mock(side_effect=[json.dumps(invalid), json.dumps(evaluation_report())])
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("review", auto=True)
    assert provider.call_count == 2
    assert outcome("review")["attempts"][0]["category"] in ("schema_error", "validation_error")
    assert outcome("review")["attempts"][0]["detail"] in provider.call_args.args[1]
    report = parse_json(Path(".vita/results/review.json").read_text(encoding="utf-8"))
    assert {key: report["metadata"][key] for key in baseline["metadata"]} == baseline["metadata"]
    assert report["metadata"]["assessment"]["contract_version"] == "assessment-v1"


def test_extraction_retries_format_and_rejects_wrong_provenance(project, monkeypatch):
    good = cached_job()
    wrong = copy.deepcopy(good)
    wrong["source_sha256"] = "wrong-input"
    provider = Mock(side_effect=[MALFORMED, json.dumps(wrong), json.dumps(good)])
    monkeypatch.setattr(job_extraction, "generate", provider)
    assert ai_step.run("extract", auto=True)
    assert [item["category"] for item in outcome("extract")["attempts"]] == ["invalid_json", "validation_error", "valid"]
    assert provider.call_count == 3
    assert Path(".vita/results/job.toon").is_file()


@pytest.mark.parametrize("error", [ProviderError("secret-body", status=401),
                                 RuntimeError("secret"), TypeError("adapter bug"), ValueError("missing key"),
                                 ProviderError("blocked", "refusal"), ProviderError("short", "incomplete_response")])
def test_provider_failures_stop_without_format_retry_or_sensitive_trace(project, monkeypatch, error):
    provider = Mock(side_effect=error)
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("analyze", auto=True) is False
    provider.assert_called_once()
    record = outcome()
    assert record["error"]["code"] == "provider_error"
    assert "secret" not in json.dumps(record)
    assert "Synthetic Python" not in json.dumps(record)


@pytest.mark.parametrize("provider", ["openai", "openrouter", "gemini"])
def test_native_schema_payload_and_host_validation(project, monkeypatch, evaluation_report, provider):
    response = json.dumps(evaluation_report())
    result = ({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": response}]}}]}
              if provider == "gemini" else {"choices": [{"finish_reason": "stop", "message": {"content": response}}]})
    post = Mock(return_value=result)
    monkeypatch.setattr(llm, "_post", post)
    assert ai_step.run("analyze", auto=True, provider=provider)
    body = post.call_args.args[2]
    expected = generation_schema(EVALUATION_OUTPUT_SCHEMA)
    if provider == "gemini":
        assert body["generationConfig"]["responseJsonSchema"] == expected
        assert body["generationConfig"]["responseMimeType"] == "application/json"
    else:
        assert body["response_format"]["json_schema"]["schema"] == expected
        assert body["response_format"]["json_schema"]["strict"] is True
        if provider == "openrouter":
            assert body["provider"]["require_parameters"] is True
    assert not {"metadata", "qualitative_summary", "comparison"} & expected["properties"].keys()
    assert outcome()["attempts"][0]["mode"] == "native_schema"


def test_unsupported_native_schema_fallback_is_recorded_and_route_frozen(project, monkeypatch, evaluation_report):
    settings = {"model": "original-model", "reasoning_effort": "low"}
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"openai": settings})
    calls = []

    def post(url, headers, data):
        calls.append(data)
        if len(calls) == 1:
            settings.update(model="changed-model", reasoning_effort="high")
            raise UnsupportedSchema()
        return {"choices": [{"message": {"content": json.dumps(evaluation_report())}}]}

    monkeypatch.setattr(llm, "_post", post)
    assert ai_step.run("analyze", auto=True)
    assert "response_format" in calls[0] and "response_format" not in calls[1]
    assert all(data["model"] == "original-model" and data["reasoning_effort"] == "low" for data in calls)
    assert [item["category"] for item in outcome()["attempts"]] == ["unsupported_schema", "valid"]
    assert [item["mode"] for item in outcome()["attempts"]] == ["native_schema", "validated_prompt"]
    assert "test-secret" not in json.dumps(outcome())


@pytest.mark.parametrize("status,body,fallback", [
    (400, 'response_format json_schema is not supported with this model', True),
    (400, 'Invalid schema for response_format: unsupported keyword', False),
    (401, 'response_format is not supported', False),
    (429, 'quota exceeded', False),
])
def test_http_negotiation_only_for_explicit_unsupported_format(project, monkeypatch, status, body, fallback):
    error = urllib.error.HTTPError("https://example.invalid", status, "error", {}, io.BytesIO(body.encode()))
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=error))
    with pytest.raises(UnsupportedSchema if fallback else ProviderError) as caught:
        llm._call_openai("s", "u", "test-secret", "model", response_schema={"type": "object"})
    if not fallback:
        assert not isinstance(caught.value, UnsupportedSchema)


def test_legacy_adapter_and_distinct_reruns(project, monkeypatch, evaluation_report):
    calls = []

    def legacy(system, prompt, provider=None):
        calls.append(provider)
        assert "Required JSON output schema" in prompt
        return MALFORMED if len(calls) == 1 else json.dumps(evaluation_report())

    monkeypatch.setattr(ai_step, "llm_generate", legacy)
    assert ai_step.run("analyze", auto=True, provider="codex")
    first = outcome()
    assert calls == ["codex", "codex"]
    assert first["attempts"][0]["mode"] == "validated_prompt"
    assert ai_step.run("analyze", auto=True, provider="codex")
    assert outcome()["run_id"] != first["run_id"]
    assert len(list(Path(".vita/results/attempts").glob("analyze-*.json"))) == 2


def test_cli_exhaustion_returns_nonzero_and_machine_readable_outcome(project, monkeypatch):
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value=MALFORMED))
    monkeypatch.setattr(sys, "argv", ["vita", "analyze", "--auto"])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1
    assert outcome()["error"]["code"] == "structured_output_invalid"


def test_manual_mode_never_calls_provider_or_creates_attempt_records(project, monkeypatch):
    provider = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("analyze")
    provider.assert_not_called()
    assert not Path(".vita/results/attempts").exists()
    assert "STRUCTURED EVALUATION CONTRACT" in Path(".vita/prompts/analyze.md").read_text(encoding="utf-8")


def test_fallback_counts_toward_total_attempt_limit(project, monkeypatch):
    provider = Mock(side_effect=[UnsupportedSchema(), MALFORMED, MALFORMED])
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("analyze", auto=True) is False
    assert provider.call_count == 3
    assert [item["category"] for item in outcome()["attempts"]] == ["unsupported_schema", "invalid_json", "invalid_json"]
    assert "response_schema" in provider.call_args_list[0].kwargs
    assert "response_schema" not in provider.call_args_list[1].kwargs


@pytest.mark.parametrize("provider,config", [("openai", {"structured_output": "off"}), ("groq", {})])
def test_configured_or_legacy_provider_fallback_is_validated(project, monkeypatch, evaluation_report, provider, config):
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {provider: config})
    post = Mock(return_value={"choices": [{"message": {"content": json.dumps(evaluation_report())}}]})
    monkeypatch.setattr(llm, "_post", post)
    assert ai_step.run("analyze", auto=True)
    assert "response_format" not in post.call_args.args[2]
    assert outcome()["attempts"][0]["mode"] == "validated_prompt"


def test_old_codex_cli_falls_back_without_changing_model(project, monkeypatch, evaluation_report):
    monkeypatch.setattr(llm, "_find_codex_cli", lambda: "mock-codex")
    commands = []

    def codex(cmd, **kwargs):
        commands.append(cmd)
        if "--output-schema" in cmd:
            return subprocess.CompletedProcess(cmd, 2, "", "error: unexpected argument '--output-schema' found")
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(json.dumps(evaluation_report()), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(llm.subprocess, "run", codex)
    assert ai_step.run("analyze", auto=True)
    assert len(commands) == 2
    assert all(cmd[cmd.index("--model") + 1] == "gpt-6.1-sol" for cmd in commands)
    assert [item["category"] for item in outcome()["attempts"]] == ["unsupported_schema", "valid"]
    assert not list(Path(".vita/tmp").glob("codex-*"))


@pytest.mark.parametrize("result,category", [
    ({"promptFeedback": {"blockReason": "SAFETY"}}, "refusal"),
    ({"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}]}, "incomplete_response"),
])
def test_gemini_rejects_refusals_and_truncation_without_retry(project, monkeypatch, result, category):
    post = Mock(return_value=result)
    monkeypatch.setattr(llm, "_post", post)
    assert ai_step.run("analyze", auto=True, provider="gemini") is False
    post.assert_called_once()
    assert outcome()["attempts"][0]["category"] == category


def test_schema_projection_keeps_full_host_schema_unchanged():
    before = copy.deepcopy(JOB_SCHEMA)
    projected = generation_schema(JOB_SCHEMA)
    assert JOB_SCHEMA == before
    assert projected["properties"]["schema_version"] == {"type": "integer", "enum": [1]}
    assert "minItems" not in projected["properties"]["jobs"]
    assert JOB_SCHEMA["properties"]["jobs"]["minItems"] == 1
    assert projected["required"] == list(projected["properties"])


def test_disk_failure_is_not_retried_as_model_format_failure(project, monkeypatch, evaluation_report):
    provider = Mock(return_value=json.dumps(evaluation_report()))
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    monkeypatch.setattr("vita.helpers.assessment.save_evaluation", Mock(side_effect=OSError("disk full")))
    assert ai_step.run("analyze", auto=True) is False
    provider.assert_called_once()
    assert outcome()["error"]["code"] == "artifact_error"


def test_extraction_exhaustion_preserves_cache_and_stops_evaluation(project, monkeypatch):
    cached_job()
    original = Path(".vita/results/job.json").read_bytes()
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "true")
    extractor = Mock(return_value=MALFORMED)
    evaluator = Mock()
    monkeypatch.setattr(job_extraction, "generate", extractor)
    monkeypatch.setattr(ai_step, "llm_generate", evaluator)
    assert run.run(auto=True) is False
    assert extractor.call_count == 3
    evaluator.assert_not_called()
    assert Path(".vita/results/job.json").read_bytes() == original
    assert outcome("extract")["error"]["code"] == "structured_output_invalid"
