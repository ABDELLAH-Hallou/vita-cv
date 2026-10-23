"""Deterministic issue #40 fixtures; no live providers, credentials or waiting."""

import io
import json
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step, providers
from vita.helpers import llm, provider_errors, structured_output
from vita.helpers.provider_errors import (
    PROVIDER_ERROR_SCHEMA,
    ProviderError,
    RetryPolicy,
    retry_after_seconds,
)
from vita.helpers.structured import parse_json, validate
from vita.helpers.structured_output import StructuredOutputError, run_structured, run_text

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
SECRET = "fixture-private-credential"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vita").mkdir()
    env = {"GEMINI_API_KEY": SECRET, "OPENAI_API_KEY": SECRET}
    monkeypatch.setattr(llm, "load_env", lambda: env)
    monkeypatch.setattr(provider_errors, "load_env", lambda: env)
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"gemini": {"model": "fixture-model"}})
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=AssertionError("No live HTTP")))
    monkeypatch.setattr(llm.subprocess, "run", Mock(side_effect=AssertionError("No live CLI")))
    sleeps = Mock()
    monkeypatch.setattr(structured_output.time, "sleep", sleeps)
    return env, sleeps


def http_error(status, body="", headers=None):
    return urllib.error.HTTPError(f"https://example.invalid?key={SECRET}", status, SECRET,
                                  headers or {}, io.BytesIO(body.encode()))


def response(text='{"answer":"ok"}'):
    return io.BytesIO(json.dumps({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}).encode())


def result(step="extract"):
    return parse_json(Path(f".vita/results/{step}.outcome.json").read_text(encoding="utf-8"))


def structured():
    return run_structured(step="extract", generate=llm.generate, system="Synthetic", prompt="No candidate data.",
                          route={"provider": "gemini", "model": "fixture-model"}, schema=SCHEMA,
                          finalize=lambda value: value, save=lambda value: None)


@pytest.mark.parametrize("status,body,category,retryable", [
    (503, '{"error":{"status":"UNAVAILABLE","message":"high demand"}}', "overloaded", True),
    (429, "rate limit", "rate_limit", True),
    (401, SECRET, "authentication", False),
    (403, "permission denied", "permission", False),
    (404, '{"error":{"code":"model_not_found"}}', "invalid_model", False),
    (400, "not a valid model ID", "invalid_model", False),
    (404, "models/fixture-model is not found", "invalid_model", False),
    (429, '{"error":{"code":"insufficient_quota"}}', "quota_exceeded", False),
])
def test_http_failure_contract_and_capped_attempts(project, monkeypatch, capsys, status, body, category, retryable):
    errors = [http_error(status, body + SECRET) for _ in range(3 if retryable else 1)]
    http = Mock(side_effect=errors)
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError) as stopped:
        structured()
    count = 3 if retryable else 1
    record = result()
    error = record["error"]
    validate(error, PROVIDER_ERROR_SCHEMA)
    assert error == stopped.value.error
    assert error["schema_version"] == 1
    assert (error["provider"], error["model"], error["step"]) == ("gemini", "fixture-model", "extract")
    assert (error["category"], error["status"], error["retryable"]) == (category, status, retryable)
    assert error["attempts"] == record["attempt_count"] == http.call_count == count
    assert error["max_attempts"] == 3 and error["exhausted"] == retryable
    assert "credential" not in error["action"] or category in ("authentication", "configuration")
    for call in http.call_args_list:
        assert "fixture-model:generateContent" in call.args[0].full_url
    public = json.dumps(record) + str(stopped.value) + capsys.readouterr().out
    assert SECRET not in public and "high demand" not in public
    assert "No candidate data" not in public
    assert len(list(Path(".vita/results/attempts").glob("extract-*.json"))) == 1


def test_retry_after_and_transient_recovery_do_not_become_format_repairs(project, monkeypatch):
    http = Mock(side_effect=[http_error(429, SECRET, {"Retry-After": "4"}), response()])
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert structured() == {"answer": "ok"}
    assert [item["category"] for item in result()["attempts"]] == ["rate_limit", "valid"]
    assert result()["attempts"][0]["retry_delay_seconds"] == 4
    project[1].assert_called_once_with(4)
    assert http.call_args_list[0].args[0].data == http.call_args_list[1].args[0].data


def test_http_date_retry_after_is_parsed_without_wall_clock_variance():
    now = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
    assert retry_after_seconds("Fri, 23 Oct 2026 14:00:09 GMT", now=now) == 9
    assert retry_after_seconds("Fri, 23 Oct 2026 13:59:00 GMT", now=now) == 0
    for header in ("-1", "1.5", SECRET, "NaN", "", None):
        assert retry_after_seconds(header, now=now) is None


def test_long_retry_after_stops_instead_of_retrying_early(project, monkeypatch):
    http = Mock(side_effect=http_error(503, SECRET, {"Retry-After": "3600"}))
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError):
        structured()
    assert http.call_count == 1
    assert result()["error"]["retry_stopped"] == "retry_after_exceeds_delay_cap"
    assert result()["error"]["retryable"] and not result()["error"]["exhausted"]
    project[1].assert_not_called()


@pytest.mark.parametrize("sequence,expected", [
    ([503, "malformed", "valid"], ["overloaded", "invalid_json", "valid"]),
    (["malformed", 503, "malformed"], ["invalid_json", "overloaded", "invalid_json"]),
    (["unsupported", 503, "malformed"], ["unsupported_schema", "overloaded", "invalid_json"]),
])
def test_format_transport_and_schema_recovery_share_one_budget(project, monkeypatch, sequence, expected):
    values = []
    for item in sequence:
        values.append(http_error(503) if item == 503 else (
            http_error(400, "responseJsonSchema is not supported") if item == "unsupported" else response(
                '{"answer":"ok"}' if item == "valid" else '{"answer":')))
    http = Mock(side_effect=values)
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    if sequence[-1] == "valid":
        assert structured() == {"answer": "ok"}
    else:
        with pytest.raises(StructuredOutputError):
            structured()
    assert http.call_count == 3 and result()["max_attempts"] == 3
    assert [item["category"] for item in result()["attempts"]] == expected
    assert all(item["route"]["model"] == "fixture-model" for item in result()["attempts"])
    if sequence[0] == "malformed":
        assert http.call_args_list[1].args[0].data == http.call_args_list[2].args[0].data


def test_budget_can_be_lowered_and_bad_configuration_is_safe(project, monkeypatch):
    project[0]["VITA_PROVIDER_MAX_ATTEMPTS"] = "2"
    http = Mock(side_effect=[http_error(503), http_error(503)])
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError):
        structured()
    assert http.call_count == result()["attempt_count"] == 2
    for value in ("0", "6", SECRET):
        project[0]["VITA_PROVIDER_MAX_ATTEMPTS"] = value
        with pytest.raises(StructuredOutputError):
            structured()
        assert result()["attempt_count"] == 0 and result()["error"]["category"] == "configuration"
        assert SECRET not in json.dumps(result())
    assert RetryPolicy(5, 1, 30).delay(ProviderError(status=503), 5) == 16


def test_routing_is_frozen_across_transient_retries(project, monkeypatch):
    configuration = {"model": "first-model"}
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"gemini": configuration})
    calls = []
    def http(request, **kwargs):
        calls.append(request.full_url)
        configuration["model"] = "unwanted-fallback"
        if len(calls) == 1:
            raise http_error(503)
        return response()
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert run_structured(step="extract", generate=llm.generate, system="Synthetic", prompt="Test",
                          route={"provider": "gemini"}, schema=SCHEMA, finalize=lambda value: value,
                          save=lambda value: None) == {"answer": "ok"}
    assert calls[0] == calls[1] and "first-model" in calls[1]


def test_transport_timeout_is_typed_and_retried(project, monkeypatch):
    http = Mock(side_effect=[urllib.error.URLError(TimeoutError(SECRET)), response()])
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert structured() == {"answer": "ok"}
    assert result()["attempts"][0]["error"]["category"] == "timeout"
    assert SECRET not in json.dumps(result())


def test_text_cover_failure_has_the_same_machine_contract_and_preserves_cv(project, monkeypatch):
    Path("main.tex").write_text("Synthetic CV", encoding="utf-8")
    Path("cover-letter.tex").write_text("Existing cover", encoding="utf-8")
    Path("job.md").write_text("Synthetic job", encoding="utf-8")
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    http = Mock(side_effect=[http_error(503) for _ in range(3)])
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert ai_step.run("cover", auto=True, provider="gemini") is False
    assert result("cover")["error"]["category"] == "overloaded"
    assert result("cover")["error"]["attempts"] == 3
    assert Path("main.tex").read_text(encoding="utf-8") == "Synthetic CV"
    assert Path("cover-letter.tex").read_text(encoding="utf-8") == "Existing cover"


def test_sensitive_identifiers_and_raw_cli_errors_are_redacted(project, monkeypatch, capsys):
    session = {"resolved": ("gemini", SECRET, {}, project[0])}
    error = ProviderError(f"stderr {SECRET}", status=401)
    assert SECRET not in str(error) and SECRET not in repr(error)
    with pytest.raises(StructuredOutputError):
        run_text(step="check", generate=Mock(side_effect=error), system="", prompt="",
                 route={"provider": "gemini", "model": SECRET}, session=session)
    assert result("check")["error"]["model"] is None
    assert SECRET not in json.dumps(result("check")) + capsys.readouterr().out


def test_secrets_are_redacted_even_in_started_records_before_route_resolution(project, monkeypatch):
    writes = []
    original = structured_output.write_artifact
    def write(path, text):
        writes.append(text)
        assert SECRET not in text
        original(path, text)
    monkeypatch.setattr(structured_output, "write_artifact", write)
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=http_error(401, SECRET)))
    with pytest.raises(StructuredOutputError):
        run_text(step="check", generate=llm.generate, system="", prompt="",
                 route={"provider": "gemini", "model": SECRET})
    assert writes and result("check")["error"]["model"] is None


def test_schema_negotiation_retains_http_status_and_uses_one_budget(project, monkeypatch):
    http = Mock(side_effect=[http_error(400, "responseJsonSchema is not supported"), response()])
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert structured() == {"answer": "ok"}
    attempt = result()["attempts"][0]
    assert attempt["error"]["category"] == "unsupported_schema"
    assert attempt["error"]["status"] == 400 and result()["attempt_count"] == 2


def test_discovery_is_separate_from_generation_and_reports_usage(project, monkeypatch, capsys):
    http = Mock(side_effect=[io.BytesIO(json.dumps({"models": [{"name": "models/fixture-model"}], "nextPageToken": "private-page-token"}).encode()), response("OK")])
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert providers.run(provider="gemini", model="fixture-model", as_json=True)
    discovery = json.loads(capsys.readouterr().out)
    assert discovery["check"] == "discovery" and not discovery["generation_verified"]
    assert discovery["discovery"]["selected_model_listed"] and discovery["discovery"]["has_more"]
    assert http.call_args.args[0].method == "GET" and not discovery["may_consume_usage"]
    assert providers.run(provider="gemini", model="fixture-model", generate=True, as_json=True)
    output = capsys.readouterr()
    generated = json.loads(output.out)
    assert generated["generation_verified"] and generated["may_consume_usage"]
    assert "may consume provider usage" in output.err
    assert http.call_args.args[0].method == "POST"
    assert "Synthetic CV" not in http.call_args.args[0].data.decode()
    assert SECRET not in json.dumps(generated) + json.dumps(discovery)
    assert "private-page-token" not in json.dumps(discovery)


def test_model_discovery_success_does_not_mask_generation_failure(project, monkeypatch, capsys):
    http = Mock(side_effect=[io.BytesIO(b'{"models":[{"name":"models/fixture-model"}]}'), http_error(401, SECRET)])
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert providers.run(provider="gemini", as_json=True)
    assert not providers.run(provider="gemini", generate=True, as_json=True)
    checked = parse_json(Path(".vita/results/provider-check.json").read_text(encoding="utf-8"))
    assert checked["error"]["category"] == "authentication" and not checked["generation_verified"]
    assert checked["attempts"] == 1 and SECRET not in capsys.readouterr().out


def test_cli_generation_check_returns_nonzero_with_safe_json(project, monkeypatch, capsys):
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=http_error(404, "model_not_found")))
    monkeypatch.setattr(sys, "argv", ["vita", "providers", "check", "--provider", "gemini", "--generate", "--json"])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1
    assert json.loads(capsys.readouterr().out)["error"]["category"] == "invalid_model"


@pytest.mark.parametrize("status,category", [(503, "overloaded"), (401, "authentication")])
def test_cli_stderr_classification_preserves_route_and_discards_raw_text(project, monkeypatch, status, category):
    import subprocess
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"codex": {"model": "fixture-codex"}})
    monkeypatch.setattr(llm, "_find_codex_cli", lambda: "fixture-codex-executable")
    cli = Mock(return_value=subprocess.CompletedProcess([], 1, "", f"HTTP {status}: {SECRET}"))
    monkeypatch.setattr(llm.subprocess, "run", cli)
    with pytest.raises(StructuredOutputError):
        run_text(step="cover", generate=llm.generate, system="Test", prompt="Test", route={"provider": "codex"})
    error = result("cover")["error"]
    assert error["category"] == category and error["status"] == status
    assert error["model"] == "fixture-codex" and SECRET not in json.dumps(result("cover"))
    assert cli.call_count == (3 if status == 503 else 1)


def test_missing_configured_credential_has_a_machine_outcome_before_generation(project, monkeypatch):
    Path("main.tex").write_text("Synthetic CV", encoding="utf-8")
    Path("job.md").write_text("Synthetic job", encoding="utf-8")
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    monkeypatch.setattr(llm, "_resolve", Mock(side_effect=ValueError(SECRET)))
    assert not ai_step.run("analyze", auto=True, provider="gemini")
    error = result("analyze")["error"]
    assert error["category"] == "configuration" and error["attempts"] == 0
    assert error["provider"] == "gemini" and SECRET not in json.dumps(result("analyze"))


@pytest.mark.parametrize("field,value", [
    ("VITA_PROVIDER_RETRY_BASE_SECONDS", "NaN"),
    ("VITA_PROVIDER_RETRY_MAX_SECONDS", "31"),
    ("VITA_PROVIDER_RETRY_BASE_SECONDS", "-1"),
])
def test_invalid_delay_settings_fail_before_any_call(project, field, value):
    project[0][field] = value
    adapter = Mock()
    with pytest.raises(StructuredOutputError) as stopped:
        run_text(step="check", generate=adapter, system="", prompt="", route={"provider": "gemini"})
    adapter.assert_not_called()
    assert stopped.value.error["category"] == "configuration"


def test_model_errors_never_negotiate_schema_fallback(project, monkeypatch):
    http = Mock(side_effect=http_error(400, "model_not_found responseJsonSchema is not supported"))
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError):
        structured()
    assert http.call_count == 1 and result()["error"]["category"] == "invalid_model"


@pytest.mark.parametrize("provider", ["openai", "openrouter", "anthropic", "codex"])
def test_catalog_discovery_never_generates_or_claims_access(project, monkeypatch, provider, capsys):
    project[0][f"{provider.upper()}_API_KEY"] = SECRET
    http = Mock(return_value=io.BytesIO(b'{"data":[{"id":"fixture-model"}]}'))
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert providers.run(provider=provider, model="fixture-model", as_json=True)
    checked = json.loads(capsys.readouterr().out)
    assert not checked["generation_verified"]
    if provider == "codex":
        http.assert_not_called()
        assert checked["discovery"]["status"] == "unavailable"
    else:
        http.assert_called_once()
        assert http.call_args.args[0].method == "GET"
        assert checked["discovery"]["selected_model_listed"]


def test_error_contract_rejects_boolean_status_and_integer_retryability():
    contract = ProviderError(status=503).contract(step="check", route={"provider": "gemini", "model": "fixture"}, attempts=1, max_attempts=3)
    for field, value in (("status", True), ("retryable", 1)):
        invalid = {**contract, field: value}
        with pytest.raises(ValueError):
            validate(invalid, PROVIDER_ERROR_SCHEMA)
