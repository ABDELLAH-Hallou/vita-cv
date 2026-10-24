"""No paid requests: harness safety, adapter observation, and comparison accounting."""

import copy
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from scripts.benchmark import runner, worker
from vita.helpers import llm
from vita.helpers.provider_errors import ProviderError


def case(provider="openai", **updates):
    return {"id": "synthetic", "provider": provider, "model": "custom/model-snapshot-v1",
            "reasoning_effort": "low" if provider in runner.REASONING else None,
            "extraction": True, **updates}


def authorization(tmp_path, plan, **updates):
    path = tmp_path / "authorization.json"
    runner.write(path, {"plan_sha256": runner.object_hash(plan), "acknowledge_api_billing": True,
        "max_requests": 2, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), **updates})
    return path


def test_frozen_corpus_and_complete_default_matrix():
    manifest = runner.corpus_manifest()
    assert manifest["revision"] == "synthetic-v1"
    plan = runner.fixture_plan()
    runner.validate_plan(plan, live=False)
    assert {c["provider"] for c in plan["cases"]} == set(runner.ADAPTERS)
    for adapter in runner.ADAPTERS:
        assert {c["extraction"] for c in plan["cases"] if c["provider"] == adapter} == {False, True}
    for adapter in runner.REASONING:
        assert {c["reasoning_effort"] for c in plan["cases"] if c["provider"] == adapter} >= {"low", "high"}
    job = (runner.CORPUS / "job.md").read_text(encoding="utf-8")
    assert "conflicting with the page title" in job and "Application form" in job and "Footer" in job


@pytest.mark.parametrize("change", [
    {"id": "../escape"}, {"provider": "unknown"}, {"model": "https://secret.example?key=x"},
    {"extraction": "true"}, {"reasoning_effort": "expensive"},
    {"provider": "gemini", "reasoning_effort": "low"}, {"api_key": "never allowed"},
])
def test_reject_invalid_or_secret_bearing_live_plans(change):
    with pytest.raises(ValueError):
        runner.validate_plan({"schema_version": 1, "cases": [case(**change)]}, live=True)


def test_live_requires_exact_authorization_before_directory_or_process(tmp_path, monkeypatch):
    plan = {"schema_version": 1, "cases": [case()]}
    path = tmp_path / "plan.json"
    runner.write(path, plan)
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("Dispatched without authorization"))
    output = tmp_path / "run"
    assert runner.main(["--mode", "live", "--plan", str(path), "--output", str(output)]) == 2
    assert not output.exists()
    auth = authorization(tmp_path, plan, acknowledge_api_billing=False)
    assert runner.main(["--mode", "live", "--plan", str(path), "--authorization", str(auth), "--output", str(output)]) == 2
    auth = authorization(tmp_path, plan, plan_sha256="wrong")
    with pytest.raises(ValueError):
        runner.validate_authorization(auth, plan)
    auth = authorization(tmp_path, plan, expires_at="2000-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        runner.validate_authorization(auth, plan)
    assert not output.exists()


def test_dispatch_budget_reserves_failures_and_survives_new_worker(tmp_path):
    auth = authorization(tmp_path, {"schema_version": 1, "cases": [case()]})
    ledger = tmp_path / "ledger.json"
    worker.reserve(auth, ledger)
    worker.reserve(auth, ledger)
    with pytest.raises(ProviderError) as error:
        worker.reserve(auth, ledger)
    assert error.value.code == "configuration"
    assert runner.read(ledger) == {"requests": 2}


@pytest.mark.parametrize("provider", runner.ADAPTERS)
def test_fixture_exercises_real_adapter_custom_model_and_reasoning(tmp_path, monkeypatch, provider):
    config = case(provider)
    project = tmp_path / "project"
    runner.project_setup(project, config)
    monkeypatch.chdir(project)
    for key, value in runner.child_env(project, config, "fixture").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(worker, "main", lambda: llm.generate("system", "Adapt the CV", provider=provider, model=config["model"]))
    telemetry = tmp_path / "transport.json"
    worker.execute({"mode": "fixture", "case": config, "telemetry": str(telemetry), "real_pdf": False})
    requests = runner.read(telemetry)["requests"]
    assert len(requests) == 1
    assert requests[0]["wire_model"] == config["model"]
    assert requests[0]["reasoning_effort"] == config["reasoning_effort"]
    assert requests[0]["status"] == "response"
    assert requests[0]["usage_status"] == ("unknown" if provider == "codex" else "reported")
    assert requests[0]["billing"] == "unknown"


def test_usage_allowlist_unknown_is_not_zero():
    assert worker.usage_metadata({})["usage"] is None
    result = worker.usage_metadata({"modelVersion": "snapshot-v2", "usageMetadata": {
        "promptTokenCount": 40, "thoughtsTokenCount": 8, "secret": "never capture", "totalTokenCount": True}})
    assert result["usage"] == {"promptTokenCount": 40, "thoughtsTokenCount": 8}
    assert result["reported_model"] == "snapshot-v2"
    assert result["billing"] == "unknown"
    result = worker.usage_metadata({"usage": {"total_tokens": float("inf"), "cost": 0.01,
        "completion_tokens_details": {"reasoning_tokens": 4, "unsafe": "not captured"}}})
    assert result["usage"] == {"cost": 0.01, "completion_tokens_details": {"reasoning_tokens": 4}}
    assert result["billing"] == "provider_reported_cost_not_invoice"


def test_live_resume_waits_for_human_then_skips_already_approved_adapt(tmp_path, monkeypatch):
    config = case()
    workflow = tmp_path / "cases" / config["id"] / "workflow"
    calls = []
    settings = {"mode": "live", "real_pdf": False}

    def invoke(run_dir, selected, workspace, label, argv, settings, **options):
        calls.append(label)
        if label == "pipeline":
            runner.write(workspace / ".vita/results/adapt.facts.json", {
                "status": "confirmation_required", "application_status": "not_applied", "revision": "frozen-adapt"})
        return {"label": label, "exit_status": 1 if label == "pipeline" else 0,
                "transport": {"requests": [{"status": "response"}]}, "assessments": {}}

    monkeypatch.setattr(runner, "invoke", invoke)
    previous = runner.execute_case(tmp_path, config, settings)
    assert previous["status"] == "confirmation_required"
    assert calls == ["pipeline"]
    assert runner.execute_case(tmp_path, config, settings, previous) is previous
    assert calls == ["pipeline"]
    runner.write(workflow / ".vita/results/adapt.facts.json", {
        "status": "approved", "application_status": "applied", "revision": "frozen-adapt"})
    result = runner.execute_case(tmp_path, config, settings, previous)
    assert result["status"] == "passed"
    assert result["commands"][0]["exit_status"] == 1
    assert result["commands"][0]["resolved_confirmation"]["revision"] == "frozen-adapt"
    assert calls[:4] == ["pipeline", "resumed-review", "resumed-cover", "build"]
    assert calls.count("pipeline") == 1


def test_unavailable_and_missing_results_stay_in_reliability_denominator():
    plan = {"schema_version": 1, "cases": [case(id="ok"), case(id="offline"), case(id="not-started")]}
    summary = runner.summarize(plan, [{"id": "ok", "status": "passed", "commands": []},
                                    {"id": "offline", "status": "unavailable", "commands": []}])
    assert summary["denominator"] == 3
    assert summary["success_rate"] == 1 / 3
    assert summary["counts"]["unavailable"] == summary["counts"]["not_run"] == 1
    assert summary["providers"]["openai"]["denominator"] == 3
    assert summary["quality"]["status"] == "unmeasured"


def test_unchanged_repeats_cross_stage_and_cache_are_separate():
    report = {"overall_score": 50, "metadata": {"assessment": {
        "prompt_sha256": "p", "system_sha256": "s", "source_sha256": "cv", "criteria_sha256": "criteria"},
        "assessment_execution": {"mode": "generated"}}}
    records = []
    for label, score, mode in (("control-analyze", 50, "generated"), ("repeat-analyze", 40, "reassessment"),
                               ("control-review", 60, "reassessment"), ("cached-review", 50, "reused")):
        result = copy.deepcopy(report)
        result["overall_score"] = score
        result["metadata"]["assessment_execution"]["mode"] = mode
        records.append({"label": label, "assessments": {"review" if "review" in label else "analysis": result}})
    comparisons = runner.controls(records)
    assert comparisons["analyze_to_analyze"]["delta"] == -10
    assert comparisons["analyze_to_review"]["delta"] == 10
    assert comparisons["cache_reuse"]["delta"] == 0
    assert comparisons["cache_reuse"]["execution"]["mode"] == "reused"
    assert all(c["same_prompt"] and c["same_sources"] and c["same_criteria"] for c in comparisons.values())


def test_failed_pipeline_never_spends_on_later_stages(tmp_path, monkeypatch):
    calls = []

    def invoke(*args, **kwargs):
        calls.append(args[3])
        return {"label": args[3], "exit_status": 1, "transport": {"requests": []}}

    monkeypatch.setattr(runner, "invoke", invoke)
    result = runner.execute_case(tmp_path, case(), {"mode": "live"})
    assert calls == ["pipeline"]
    assert result["status"] == "unavailable"
    assert result["quality"] == {"status": "unmeasured", "value": None}


def test_fixture_cannot_connect_even_if_mock_misses_a_transport(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(worker, "main", lambda: socket.create_connection(("fixture.invalid", 443)))
    with pytest.raises(AssertionError, match="network"):
        worker.execute({"mode": "fixture", "case": case(), "telemetry": str(tmp_path / "requests.json")})


def test_live_observer_preserves_http_response_and_enforces_budget(tmp_path, monkeypatch):
    auth = authorization(tmp_path, {"schema_version": 1, "cases": [case()]}, max_requests=1)
    response = worker.Response(json.dumps({"model": "accessible-snapshot", "usage": {"total_tokens": 9}}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: response)

    def request():
        req = urllib.request.Request("https://fixture.invalid", data=b'{"model":"custom/model-snapshot-v1","messages":[]}')
        with urllib.request.urlopen(req) as result:
            assert json.loads(result.read())["usage"]["total_tokens"] == 9
        with pytest.raises(ProviderError):
            urllib.request.urlopen(req)

    monkeypatch.setattr(worker, "main", request)
    telemetry = tmp_path / "requests.json"
    worker.execute({"mode": "live", "case": case(), "telemetry": str(telemetry),
                    "authorization": str(auth), "ledger": str(tmp_path / "ledger.json")})
    rows = runner.read(telemetry)["requests"]
    assert len(rows) == 1 and rows[0]["usage"] == {"total_tokens": 9}
    assert rows[0]["reported_model"] == "accessible-snapshot"
    assert runner.read(telemetry)["dispatch_blocks"] == [{"reason": "request_limit_reached_or_invalid_ledger", "transport": "http"}]


def test_plan_hash_is_read_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["benchmark"])
    assert runner.main(["--plan-hash"]) == 0
    assert capsys.readouterr().out.strip() == runner.object_hash(runner.fixture_plan())
    assert not list(tmp_path.iterdir())
