"""Privacy and execution-contract controls. All provider activity is synthetic."""

import io
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.helpers import diagnostics as d
from vita.helpers import llm, provider_errors, structured_output
from vita.helpers.diagnostics_contract import (
    EVENT_SCHEMA,
    MANIFEST_SCHEMA,
    PROCESS_SCHEMA,
    REFERENCE_SCHEMA,
)
from vita.helpers.structured import parse_json, validate
from vita.helpers.structured_output import StructuredOutputError, run_structured, run_text

SECRET = "fixture-private-api-secret"
PERSON = "PERSONAL_CANARY_Alice_Example_Employer"
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
REAL_SUBPROCESS_RUN = subprocess.run


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vita").mkdir()
    fixture = Path(__file__).parent / "fixtures/diagnostics/environment.example.env"
    Path(".vita/.env").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    for key in ("VITA_PROJECT_ROOT", "VITA_DIAGNOSTICS_DIR", "VITA_TRACEPARENT", "VITA_DIAGNOSTIC_CONTENT"):
        monkeypatch.delenv(key, raising=False)
    env = {"GEMINI_API_KEY": SECRET}
    monkeypatch.setattr(llm, "load_env", lambda: env)
    monkeypatch.setattr(provider_errors, "load_env", lambda: env)
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"gemini": {"model": "fixture-model"}})
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=AssertionError("No live HTTP")))
    monkeypatch.setattr(llm.subprocess, "run", Mock(side_effect=AssertionError("No live CLI")))
    monkeypatch.setattr(structured_output.time, "sleep", Mock())
    return tmp_path


def traces(root=None):
    return sorted((root or Path.cwd()).glob(".vita/logs/traces/????????????????????????????????"))


def report(root=None):
    path = traces(root)[-1]
    return d.inspect_trace(path.name, root=root), path


def invoke():
    return run_structured(step="extract", generate=llm.generate, system=PERSON, prompt=SECRET + PERSON,
                          route={"provider": "gemini", "model": "fixture-model"}, schema=SCHEMA,
                          finalize=lambda value: value, save=lambda value: None)


def http_error(status, body=None, headers=None):
    return urllib.error.HTTPError(f"https://example.invalid/{PERSON}?key={SECRET}", status, SECRET,
                                  headers or {"x-request-id": SECRET}, io.BytesIO((body or PERSON + SECRET).encode()))


def response(text='{"answer":"ok"}', **extra):
    return io.BytesIO(json.dumps({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}], **extra}).encode())


def assert_private(path):
    text = "".join(p.read_text(encoding="utf-8") for p in path.rglob("*") if p.is_file())
    assert SECRET not in text and PERSON not in text
    assert str(Path.cwd()) not in text and "Authorization" not in text


@pytest.mark.parametrize("status,category", [(401, "authentication"), (403, "permission"), (429, "rate_limit"), (503, "overloaded")])
def test_rejected_request_records_safe_cause_and_no_model_response(project, monkeypatch, capsys, status, category):
    errors = [http_error(status, json.dumps({"error": {"code": status, "status": "UNAVAILABLE", "message": PERSON + SECRET}})) for _ in range(3)]
    http = Mock(side_effect=errors)
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError):
        invoke()
    result, path = report()
    assert result["processes"][0]["status"] == "failed"
    assert result["processes"][0]["failed_phase"] == "provider_request"
    assert result["processes"][0]["failure"]["category"] == category
    assert any(a["kind"] == "response" and a["capture_status"] == "unavailable" and a["content_exists"] is False for a in result["artifacts"])
    assert any(e["details"].get("request_id_sha256") for e in result["events"])
    assert any(e["details"].get("provider_code") == "UNAVAILABLE" for e in result["events"])
    assert http.call_count == (3 if status in (429, 503) else 1)
    assert_private(path)
    stderr = capsys.readouterr().err
    assert "Trace:" in stderr and "provider_request" in stderr and "not produced" in stderr
    assert SECRET not in stderr and PERSON not in stderr


def test_missing_credential_is_configuration_not_transport(project, monkeypatch):
    monkeypatch.setattr(llm, "load_env", lambda: {})
    with pytest.raises(StructuredOutputError):
        invoke()
    result, path = report()
    assert any(e["details"].get("credential_present") is False for e in result["events"])
    assert result["processes"][0]["failure"]["category"] == "configuration"
    assert result["processes"][0]["failed_phase"] == "configuration"
    # Credential rejection happens before an HTTP request, not at decoding.
    llm.urllib.request.urlopen.assert_not_called()
    assert_private(path)


@pytest.mark.parametrize("error,category", [
    (TimeoutError(SECRET), "timeout"),
    (urllib.error.URLError(ssl.SSLCertVerificationError(SECRET)), "tls"),
    (urllib.error.URLError(PERSON + SECRET), "connection"),
])
def test_transport_causes_keep_safe_exception_types(project, monkeypatch, error, category):
    http = Mock(side_effect=error)
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError):
        invoke()
    result, path = report()
    assert result["processes"][0]["failure"]["category"] == category
    assert result["processes"][0]["failed_phase"] == "provider_request"
    assert_private(path)


@pytest.mark.parametrize("body,category", [
    (b'{"unexpected":1}', "response_shape"), (b'[1,2]', "response_shape"),
    (b'{broken', "response_decode"), (b'\xff', "response_decode"),
    (b'{"promptFeedback":{"blockReason":"SAFETY"}}', "refusal"),
    (b'{"candidates":[{"finishReason":"MAX_TOKENS"}]}', "incomplete_response"),
    (b'{"candidates":[{"content":{"parts":[{"text":""}]}}]}', "empty_response"),
])
def test_success_envelope_failures_are_not_guessed_auth_or_network_errors(project, monkeypatch, body, category):
    http = Mock(return_value=io.BytesIO(body))
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError):
        invoke()
    result, path = report()
    assert result["processes"][0]["failed_phase"] == "decoding"
    assert result["processes"][0]["failure"]["category"] == category
    assert any(a["kind"] == "http_response" and a["content_exists"] for a in result["artifacts"])
    http.assert_called_once()
    assert_private(path)


@pytest.mark.parametrize("text,category,phase", [('{"answer":', "invalid_json", "decoding"), ('{}', "schema_error", "validation")])
def test_format_recovery_retains_locations_and_existing_outcome_contract(project, monkeypatch, text, category, phase):
    http = Mock(side_effect=[response(text) for _ in range(3)])
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError):
        invoke()
    result, path = report()
    assert result["processes"][0]["failed_phase"] == phase
    assert result["processes"][0]["failure"]["category"] == category
    assert any(e["details"].get("line") or e["details"].get("location") for e in result["events"])
    outcome = parse_json(Path(".vita/results/extract.outcome.json").read_text())
    assert outcome["error"]["code"] == "structured_output_invalid" and outcome["attempt_count"] == 3
    assert "trace_id" not in outcome  # Separate contract; no required consumer migration.
    assert_private(path)


def test_provenance_and_persistence_failures_have_distinct_phases(project):
    for save in (False, True):
        def fail(value):
            raise ValueError(PERSON + SECRET)
        with pytest.raises(StructuredOutputError):
            run_structured(step="analyze", generate=Mock(return_value='{"answer":"ok"}'), system=PERSON, prompt=SECRET,
                           route={}, schema=SCHEMA, finalize=(lambda value: value) if save else fail,
                           save=fail if save else (lambda value: None))
        # Trace IDs are random; select by process failed phase instead of sort order.
    results = [d.inspect_trace(p.name) for p in traces()]
    assert {p["processes"][0]["failed_phase"] for p in results} == {"validation", "persistence"}
    assert all(p["processes"][0]["status"] == "failed" for p in results)
    for path in traces():
        assert_private(path)
    assert all(SECRET not in p.read_text() and PERSON not in p.read_text()
               for p in Path(".vita/results/attempts").glob("*.json"))


def test_unknown_adapter_failure_remains_unclassified(project):
    with pytest.raises(StructuredOutputError):
        run_text(step="cover", generate=Mock(side_effect=RuntimeError(PERSON + SECRET)), system="", prompt="", route={})
    result, path = report()
    assert result["processes"][0]["failure"]["category"] == "unclassified"
    assert_private(path)


def test_opt_in_content_capture_is_source_aware_and_does_not_capture_reasoning(project, monkeypatch):
    monkeypatch.setenv("VITA_DIAGNOSTIC_CONTENT", "sanitized")
    http = Mock(return_value=response(json.dumps({"answer": PERSON + SECRET}), private_field=PERSON,
                                      reasoning_content=SECRET + PERSON))
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert invoke()["answer"] == PERSON + SECRET
    result, path = report()
    assert result["processes"][0]["capture_enabled"]
    assert any(a["kind"] == "response" and a["capture_status"] == "redacted" for a in result["artifacts"])
    assert_private(path)
    exported = project / "bundle.zip"
    d.export_trace(path.name, exported)
    with zipfile.ZipFile(exported) as archive:
        assert set(archive.namelist()) == {"diagnostics.json", "README.txt"}
        assert PERSON not in archive.read("diagnostics.json").decode()
    with pytest.raises(FileExistsError):
        d.export_trace(path.name, exported)


def test_unstructured_content_is_suppressed_and_large_artifacts_are_truncated(project, monkeypatch):
    monkeypatch.setenv("VITA_DIAGNOSTIC_CONTENT", "sanitized")
    trace = d.Trace()
    context = d._CURRENT.set(trace)
    try:
        ref = d.capture("response", PERSON + SECRET, exists=True)
        assert ref["capture_status"] == "suppressed" and ref["path"] is None
        monkeypatch.setattr(d, "ARTIFACT_LIMIT", 150)
        ref = d.capture("schema", SCHEMA, exists=True)
        assert ref["capture_status"] == "truncated"
        assert (trace.path / ref["path"]).stat().st_size <= 150
    finally:
        trace.close("success")
        d._CURRENT.reset(context)
    assert_private(trace.path)


def test_project_destination_survives_staging_cwd_and_incoming_context(project, tmp_path, monkeypatch):
    parent = "a" * 32
    monkeypatch.setenv("VITA_PROJECT_ROOT", str(project))
    monkeypatch.setenv("VITA_TRACEPARENT", f"00-{parent}-{'b' * 16}-01")
    stage = project / "staging"
    stage.mkdir()
    monkeypatch.chdir(stage)
    assert run_text(step="cover", generate=Mock(return_value="synthetic"), system="", prompt="", route={}) == "synthetic"
    result = d.inspect_trace(parent, root=project)
    assert result["trace_id"] == parent
    assert any(e["parent_span_id"] == "b" * 16 for e in result["events"])
    assert not (stage / ".vita/logs").exists()
    manifest = json.loads((project / f".vita/logs/traces/{parent}/manifest.json").read_text())
    assert manifest["trace_context_status"] == "accepted"


@pytest.mark.parametrize("context", [None, "invalid" + SECRET, "00-" + "0" * 32 + "-" + "b" * 16 + "-01"])
def test_standalone_and_invalid_contexts_generate_new_valid_trace_ids(project, monkeypatch, context):
    if context:
        monkeypatch.setenv("VITA_TRACEPARENT", context)
    run_text(step="cover", generate=Mock(return_value="ok"), system="", prompt="", route={})
    result, path = report()
    assert len(result["trace_id"]) == 32
    assert_private(path)


def test_unavailable_log_directory_warns_without_changing_calls_or_original_error(project, monkeypatch, capsys):
    blocked = project / "blocked"
    blocked.write_text("not a directory")
    monkeypatch.setenv("VITA_DIAGNOSTICS_DIR", str(blocked / "traces"))
    adapter = Mock(side_effect=provider_errors.ProviderError(status=401))
    with pytest.raises(StructuredOutputError) as stopped:
        run_text(step="cover", generate=adapter, system="", prompt="", route={})
    assert stopped.value.error["category"] == "authentication"
    adapter.assert_called_once()
    assert "diagnostics could not be fully saved" in capsys.readouterr().err


def test_quota_rotation_and_retention_are_bounded(project, monkeypatch):
    trace = d.Trace()
    context = d._CURRENT.set(trace)
    monkeypatch.setattr(d, "EVENT_LIMIT", 1000)
    try:
        for _ in range(20):
            d.emit("cache", "validation", reused=True)
    finally:
        trace.close("success")
        d._CURRENT.reset(context)
    assert len(list(trace.path.glob("events-*.jsonl"))) <= d.EVENT_FILES
    monkeypatch.setattr(d, "RETENTION_SECONDS", -1)
    next_trace = d.Trace()
    next_trace.close("success")
    assert not trace.path.exists()
    monkeypatch.setattr(d, "TOTAL_LIMIT", 1)
    exhausted = d.Trace()
    assert exhausted.failed_logging
    exhausted.close("failed")


def test_same_trace_concurrent_writers_have_independent_streams_and_manifests(project, monkeypatch):
    trace_id = "c" * 32
    monkeypatch.setenv("VITA_TRACEPARENT", f"00-{trace_id}-{'d' * 16}-01")
    def execute(_):
        return run_text(step="cover", generate=Mock(return_value="ok"), system="", prompt="", route={})
    with ThreadPoolExecutor(max_workers=3) as executor:
        assert list(executor.map(execute, range(3))) == ["ok"] * 3
    result = d.inspect_trace(trace_id)
    assert len(result["processes"]) == 3 and all(p["status"] == "success" for p in result["processes"])
    assert len({e["process_id"] for e in result["events"]}) == 3
    for file in (project / f".vita/logs/traces/{trace_id}").glob("events-*.jsonl"):
        assert all(json.loads(line) for line in file.read_text().splitlines())


def test_crash_and_interruption_never_look_successful(project):
    trace = d.Trace()
    result = d.inspect_trace(trace.trace_id)
    assert result["processes"][0]["status"] == "incomplete_or_running"
    trace.abandon()
    assert d.inspect_trace(trace.trace_id)["processes"][0]["status"] == "incomplete"
    with pytest.raises(KeyboardInterrupt):
        run_text(step="cover", generate=Mock(side_effect=KeyboardInterrupt()), system="", prompt="", route={})
    statuses = [d.inspect_trace(p.name)["processes"][0]["status"] for p in traces()]
    assert "interrupted" in statuses


def test_v1_event_process_manifest_and_reference_schemas(project):
    run_text(step="cover", generate=Mock(return_value="ok"), system="", prompt="", route={})
    _, path = report()
    validate(json.loads((path / "manifest.json").read_text()), MANIFEST_SCHEMA)
    for file in path.glob("process-*.json"):
        process = json.loads(file.read_text())
        validate(process, PROCESS_SCHEMA)
        for reference in process["diagnostic_artifacts"]:
            validate(reference, REFERENCE_SCHEMA)
    for file in path.glob("events-*.jsonl"):
        for line in file.read_text().splitlines():
            validate(json.loads(line), EVENT_SCHEMA)


def test_cli_inspect_outputs_safe_json_and_nonzero_for_unknown_trace(project, monkeypatch, capsys):
    run_text(step="cover", generate=Mock(return_value="ok"), system="", prompt="", route={})
    _, path = report()
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["vita", "diagnostics", "inspect", path.name, "--json"])
    main()
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["trace_id"] == path.name
    assert any(e["step"] == "cover" and e["sequence"] and e["timestamp"] for e in inspected["events"])
    monkeypatch.setattr(sys, "argv", ["vita", "diagnostics", "inspect", "invalid"])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1


def test_real_subprocesses_share_parent_trace_without_overwriting_each_other(project):
    trace_id = "e" * 32
    environment = {**os.environ, "VITA_PROJECT_ROOT": str(project),
                   "VITA_TRACEPARENT": f"00-{trace_id}-{'f' * 16}-01",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    code = "from vita.helpers.structured_output import run_text; run_text(step='cover', generate=lambda *a, **k: 'ok', system='', prompt='', route={})"
    children = [subprocess.Popen([sys.executable, "-c", code], cwd=project, env=environment,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for child in children:
        _, error = child.communicate(timeout=30)
        assert child.returncode == 0, error.decode()
        assert b"diagnostics could not be fully saved" not in error, error.decode()
    result = d.inspect_trace(trace_id)
    assert len(result["processes"]) == 2 and all(p["status"] == "success" for p in result["processes"])


def test_abrupt_process_exit_keeps_incomplete_manifest_and_events(project):
    trace_id = "9" * 32
    environment = {**os.environ, "VITA_PROJECT_ROOT": str(project),
                   "VITA_TRACEPARENT": f"00-{trace_id}-{'8' * 16}-01",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    code = "import os; from vita.helpers.diagnostics import Trace; trace=Trace(); trace.event('attempt','provider_request',attempt=1); os._exit(9)"
    child = REAL_SUBPROCESS_RUN([sys.executable, "-c", code], cwd=project, env=environment, capture_output=True, timeout=30)
    assert child.returncode == 9
    result = d.inspect_trace(trace_id)
    assert result["processes"][0]["status"] == "incomplete_or_running" and result["events"]


def test_export_does_not_trust_edited_artifact_contents_or_unknown_fields(project):
    run_text(step="cover", generate=Mock(return_value="ok"), system="", prompt="", route={})
    _, path = report()
    artifact = next((path / "artifacts").iterdir())
    artifact.write_text(json.dumps({"content": SECRET + PERSON}))
    d.export_trace(path.name, project / "safe.zip")
    with zipfile.ZipFile(project / "safe.zip") as bundle:
        assert all(SECRET.encode() not in bundle.read(name) and PERSON.encode() not in bundle.read(name) for name in bundle.namelist())


def test_schema_fixtures_match_runtime_and_synthetic_consumer_records(project):
    from vita.helpers.diagnostics_contract import SCHEMAS
    fixtures = Path(__file__).parent / "fixtures/diagnostics"
    for name, schema in SCHEMAS.items():
        assert json.loads((fixtures / f"{name}.schema.json").read_text()) == schema
    for scenario in ("success", "failure"):
        validate(json.loads((fixtures / f"{scenario}.events.jsonl").read_text()), EVENT_SCHEMA)
        validate(json.loads((fixtures / f"{scenario}.process.json").read_text()), PROCESS_SCHEMA)


def test_trace_store_adds_narrow_git_exclusions_without_removing_existing_rules(project):
    REAL_SUBPROCESS_RUN(["git", "init"], cwd=project, capture_output=True, check=True)
    base = project / ".vita/logs/traces"
    base.mkdir(parents=True)
    (base / ".gitignore").write_text("# Existing rule\ncustom-file\n", encoding="utf-8")
    run_text(step="cover", generate=Mock(return_value="ok"), system="", prompt="", route={})
    _, path = report()
    assert "# Existing rule\ncustom-file" in (base / ".gitignore").read_text()
    event = next(path.glob("events-*.jsonl"))
    checked = REAL_SUBPROCESS_RUN(["git", "check-ignore", "--no-index", str(event)], cwd=project, capture_output=True)
    assert checked.returncode == 0


def test_project_capture_settings_inline_credentials_and_override_destination(project, monkeypatch):
    fixture = Path(__file__).parent / "fixtures/diagnostics/environment.example.env"
    (project / ".vita/.env").write_text(fixture.read_text(encoding="utf-8") + "\nVITA_DIAGNOSTIC_CONTENT=sanitized\n", encoding="utf-8")
    store = project / "persistent-diagnostics"
    monkeypatch.setenv("VITA_DIAGNOSTICS_DIR", str(store))
    run_text(step="cover", generate=Mock(return_value=json.dumps({"message": SECRET + PERSON})),
             system=PERSON, prompt=SECRET, route={"provider": "gemini", "model": SECRET})
    path = next(p for p in store.iterdir() if p.is_dir())
    result = d.inspect_trace(path.name)
    assert result["processes"][0]["capture_enabled"]
    assert_private(path)


def test_unsupported_schema_versions_are_rejected_by_inspection(project):
    run_text(step="cover", generate=Mock(return_value="ok"), system="", prompt="", route={})
    _, path = report()
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["schema_version"] = 99
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Unsupported"):
        d.inspect_trace(path.name)


@pytest.mark.parametrize("category", ["tls", "response_shape", "response_decode"])
def test_diagnostic_only_categories_preserve_the_existing_provider_outcome_enum(category):
    from vita.helpers.provider_errors import PROVIDER_ERROR_SCHEMA, ProviderError
    error = ProviderError(code=category)
    contract = error.contract(step="extract", route={"provider": "gemini", "model": "fixture"}, attempts=1, max_attempts=3)
    validate(contract, PROVIDER_ERROR_SCHEMA)
    assert contract["category"] == "provider_error" and error.diagnostic_category == category
    assert not error.retryable


def test_os_lock_never_initializes_an_unlocked_shared_byte(project):
    store = project / "lock-fixture"
    with d.storage_lock(store):
        assert (store / ".storage.lock").stat().st_size == 0
