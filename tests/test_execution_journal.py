"""Developer journal controls. All CVs, credentials and providers are synthetic."""

import io
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step, build
from vita.helpers import diagnostics as d
from vita.helpers import execution_journal as journal
from vita.helpers import llm, structured_output
from vita.helpers.pipeline_config import load_pipeline_settings
from vita.helpers.structured_output import StructuredOutputError, run_structured, run_text

SECRET = "fixture-private-api-secret"
PRIVATE = "CANDIDATE_PRIVATE_JOURNAL_CANARY"
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".vita").mkdir()
    Path(".vita/config.json").write_text("{}", encoding="utf-8")
    fixture = Path(__file__).parent / "fixtures/diagnostics/environment.example.env"
    Path(".vita/.env").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    Path(".vita/extensions.json").write_text(
        json.dumps(
            {
                "llm_providers": {
                    "gemini": {"model": "gemini-3.6-flash"},
                    "codex": {"model": "synthetic-codex"},
                }
            }
        ),
        encoding="utf-8",
    )
    Path("main.tex").write_text("Synthetic CV " + PRIVATE, encoding="utf-8")
    Path("job.md").write_text("Synthetic Python position", encoding="utf-8")
    for name in list(os.environ):
        if name.startswith(("VITA_", "EXTRACTION_", "ANALYSIS_", "ADAPT_", "REVIEW_", "COVER_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", Mock(side_effect=AssertionError("No live HTTP"))
    )
    monkeypatch.setattr(llm.subprocess, "run", Mock(side_effect=AssertionError("No live CLI")))
    monkeypatch.setattr(structured_output.time, "sleep", Mock())
    return tmp_path


class Response(io.BytesIO):
    status = 200
    headers = {"x-goog-request-id": "synthetic-request-123", "Content-Type": "application/json"}


def envelope(output):
    return json.dumps(
        {"candidates": [{"content": {"parts": [{"text": output}]}, "finishReason": "STOP"}]}
    ).encode()


def location():
    latest = json.loads(Path(".vita/logs/traces/latest.json").read_text(encoding="utf-8"))
    trace = Path(".vita/logs/traces") / latest["trace_id"]
    return trace, trace / "journal" / latest["process_id"]


def events():
    return [
        json.loads(line)
        for line in (location()[1] / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


@d.diagnosed(name="extract")
def extract_fixture():
    route = load_pipeline_settings().route("extract").kwargs()
    return run_structured(
        step="extract",
        generate=llm.generate,
        system="Full system " + PRIVATE,
        prompt="Full user prompt é \\section{Education} " + PRIVATE,
        route=route,
        schema=SCHEMA,
        finalize=lambda value: value,
        save=lambda value: None,
    )


def test_reported_extraction_model_mismatch_has_complete_explanation_and_failure(
    project, monkeypatch, capsys
):
    body = json.dumps(
        {
            "error": {
                "code": 400,
                "status": "INVALID_ARGUMENT",
                "message": "model gemini-2.5-flash is not available; detailed synthetic reason",
            }
        }
    ).encode()
    http = Mock(
        side_effect=lambda *a, **k: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                "https://provider.invalid?key=" + SECRET,
                400,
                "Bad Request",
                Response.headers,
                io.BytesIO(body),
            )
        )
    )
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError):
        extract_fixture()
    trace, local = location()
    configured = json.loads((local / "configuration.json").read_text(encoding="utf-8"))["events"]
    stage = next(
        row["details"]
        for row in configured
        if row["event"] == "configuration.stage_route" and row["details"]["stage"] == "extract"
    )
    assert stage["model"] == "gemini-2.5-flash"
    assert stage["model_source"] == "built_in_extraction_default"
    resolved = next(
        row["details"] for row in configured if row["event"] == "configuration.provider_route"
    )
    assert resolved["extensions_model"] == "gemini-3.6-flash"
    assert resolved["effective_model"] == "gemini-2.5-flash"
    assert "precedence" in resolved["explanation"]
    request = json.loads(next(local.rglob("http-request.json")).read_text(encoding="utf-8"))
    assert "gemini-2.5-flash:generateContent" in request["url"]
    assert journal.REDACTED in request["url"]
    assert "responseJsonSchema" in request["body"]["generationConfig"]
    error_body = next(local.rglob("provider-error-body.txt")).read_text(encoding="utf-8")
    assert "detailed synthetic reason" in error_body
    exceptions = "\n".join(p.read_text(encoding="utf-8") for p in local.rglob("exception-*.txt"))
    assert "HTTPError" in exceptions and "llm.py" in exceptions and "_post" in exceptions
    assert SECRET not in "\n".join(
        p.read_text(encoding="utf-8") for p in trace.rglob("*") if p.is_file()
    )
    assert http.call_count == 1
    assert "Developer journal:" in capsys.readouterr().err


def test_exact_prompts_wire_parameters_output_and_runtime_are_retained(project, monkeypatch):
    output = '{ "answer": "' + PRIVATE + ' résultat" }'
    http = Mock(return_value=Response(envelope(output)))
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert extract_fixture()["answer"] == PRIVATE + " résultat"
    _, local = location()
    request = json.loads(next(local.rglob("http-request.json")).read_text(encoding="utf-8"))
    actual = json.loads(http.call_args.args[0].data.decode("utf-8"))
    assert request["body"] == actual
    attempt = next(p for p in local.rglob("http-request.json")).parent
    assert (attempt / "system-prompt.txt").read_text(encoding="utf-8") == actual[
        "system_instruction"
    ]["parts"][0]["text"]
    assert (attempt / "user-prompt.txt").read_text(encoding="utf-8") == actual["contents"][0][
        "parts"
    ][0]["text"]
    assert (attempt / "model-output.txt").read_text(encoding="utf-8") == output
    response = json.loads((attempt / "http-response.json").read_text(encoding="utf-8"))
    assert response["headers"]["x-goog-request-id"] == "synthetic-request-123"
    runtime = json.loads((local / "runtime.json").read_text(encoding="utf-8"))
    assert runtime["python_executable"] == sys.executable
    assert runtime["working_directory"] == str(project)
    assert Path(runtime["package_directory"]).name == "vita"
    assert "artifact.saved" in (local / "execution.log").read_text(encoding="utf-8")
    assert any(row["component"].get("function") == "_post" for row in events())


def test_format_retries_keep_distinct_actual_prompts_and_invalid_output(project, monkeypatch):
    http = Mock(
        side_effect=[
            Response(envelope('{"answer":}')),
            Response(envelope('{"answer":"recovered"}')),
        ]
    )
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert extract_fixture() == {"answer": "recovered"}
    _, local = location()
    attempts = [p.parent for p in local.rglob("http-request.json")]
    assert len(attempts) == 2
    prompts = [(p / "user-prompt.txt").read_text(encoding="utf-8") for p in attempts]
    assert sum("FORMAT RETRY 2/3" in text for text in prompts) == 1
    assert '{"answer":}' in [(p / "model-output.txt").read_text(encoding="utf-8") for p in attempts]
    assert any(
        "JSONDecodeError" in p.read_text(encoding="utf-8") for p in local.rglob("exception-*.txt")
    )
    assert http.call_count == 2


@pytest.mark.parametrize(
    "status,category,count",
    [(503, "overloaded", 2), (429, "rate_limit", 2), (401, "authentication", 1)],
)
def test_transport_details_and_retry_decisions_keep_the_existing_budget(
    project, monkeypatch, status, category, count
):
    monkeypatch.setenv("VITA_PROVIDER_MAX_ATTEMPTS", "2")

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://provider.invalid",
            status,
            "Synthetic reason",
            {"Retry-After": "1", "x-request-id": "real-local-request-id"},
            io.BytesIO(b'{"error":{"message":"Detailed provider explanation"}}'),
        )

    http = Mock(side_effect=fail)
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError) as error:
        extract_fixture()
    assert error.value.error["category"] == category
    assert http.call_count == count
    rows = events()
    assert any(
        row["event"] == "http.response" and row["details"]["status"] == status for row in rows
    )
    scheduled = [row for row in rows if row["event"] == "retry.scheduled"]
    assert len(scheduled) == count - 1
    if scheduled:
        assert scheduled[0]["details"]["planned_delay_seconds"] == 1


def test_tls_original_reason_and_stack_are_not_lost_in_normalization(project, monkeypatch):
    http = Mock(
        side_effect=urllib.error.URLError(
            ssl.SSLCertVerificationError("synthetic trust-chain failure")
        )
    )
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    with pytest.raises(StructuredOutputError):
        extract_fixture()
    text = "\n".join(p.read_text(encoding="utf-8") for p in location()[1].rglob("exception-*.txt"))
    assert "SSLCertVerificationError" in text and "synthetic trust-chain failure" in text


def test_cli_arguments_exit_status_stdout_stderr_and_final_output_are_captured(
    project, monkeypatch
):
    monkeypatch.setattr(llm, "_find_codex_cli", lambda: "synthetic-codex")

    def execute(cmd, **kwargs):
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            "Final " + PRIVATE, encoding="utf-8"
        )
        return subprocess.CompletedProcess(cmd, 0, "CLI stdout " + PRIVATE, "CLI stderr " + SECRET)

    cli = Mock(side_effect=execute)
    monkeypatch.setattr(llm.subprocess, "run", cli)
    assert (
        run_text(
            step="cover",
            generate=llm.generate,
            system="System",
            prompt="Input",
            route={"provider": "codex"},
        )
        == "Final " + PRIVATE
    )
    _, local = location()
    request = json.loads(next(local.rglob("cli-request.json")).read_text(encoding="utf-8"))
    result = json.loads(next(local.rglob("cli-result.json")).read_text(encoding="utf-8"))
    assert request["argv"] == cli.call_args.args[0]
    assert request["stdin"] == cli.call_args.kwargs["input"]
    assert result["returncode"] == 0 and result["stdout"] == "CLI stdout " + PRIVATE
    assert SECRET not in result["stderr"] and journal.REDACTED in result["stderr"]


def test_private_content_is_local_but_credentials_and_support_exports_are_redacted(project):
    text = (
        PRIVATE
        + " "
        + SECRET
        + '\nAuthorization: Basic unknown-value\n{"api_key":"unregistered-key","reasoning_content":"hidden","answer":"'
        + PRIVATE
        + '"}'
    )
    assert (
        run_text(
            step="adapt",
            generate=Mock(return_value=text),
            system=PRIVATE,
            prompt=SECRET + PRIVATE,
            route={},
        )
        == text
    )
    trace, local = location()
    saved = "\n".join(p.read_text(encoding="utf-8") for p in local.rglob("*") if p.is_file())
    assert PRIVATE in saved
    assert SECRET not in saved and "unknown-value" not in saved and "unregistered-key" not in saved
    archive = project / "safe-support.zip"
    d.export_trace(trace.name, archive)
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {"diagnostics.json", "README.txt"}
        assert PRIVATE.encode() not in bundle.read("diagnostics.json")


@pytest.mark.parametrize("step", ["extract", "analyze", "adapt", "review", "cover"])
def test_generated_prompt_mode_records_instructions_without_claiming_execution(project, step):
    assert ai_step.run(step)
    _, local = location()
    prompt = Path(f".vita/prompts/{step}.md").read_text(encoding="utf-8")
    assert next(local.rglob("generated-prompt.txt")).read_text(encoding="utf-8") == prompt
    assert not list(local.rglob("http-request.json"))
    assert any(
        row["event"] == "prompt.generated" and row["details"]["provider_called"] is False
        for row in events()
    )


@pytest.mark.parametrize("arguments", [["adapt", "--debug"], ["--debug", "adapt"]])
def test_debug_flag_overrides_existing_off_setting_for_one_cli_run(
    project, monkeypatch, capsys, arguments
):
    monkeypatch.setenv("VITA_DIAGNOSTIC_CONTENT", "off")
    monkeypatch.setattr(sys, "argv", ["vita", *arguments])
    main()
    assert list(location()[1].rglob("generated-prompt.txt"))
    assert os.environ["VITA_DIAGNOSTIC_CONTENT"] == "off"
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["vita", "diagnostics", "inspect"])
    main()
    assert "Developer execution journal:" in capsys.readouterr().out


def test_journal_failure_does_not_change_result_or_add_provider_calls(project, monkeypatch):
    atomic = d._atomic

    def fail_journal(path, data, **kwargs):
        if "journal" in path.parts:
            raise OSError("Synthetic journal disk failure")
        atomic(path, data, **kwargs)

    monkeypatch.setattr(d, "_atomic", fail_journal)
    provider = Mock(return_value="Preserved result")
    assert (
        run_text(step="cover", generate=provider, system="", prompt="", route={})
        == "Preserved result"
    )
    assert provider.call_count == 1


def test_artifact_truncation_is_explicit_and_does_not_truncate_business_output(
    project, monkeypatch
):
    # Set the limit inside the provider so runtime/initial metadata remain intact.
    def provider(*args, **kwargs):
        monkeypatch.setattr(journal, "ARTIFACT_LIMIT", 80)
        return "X" * 1000

    assert run_text(step="cover", generate=provider, system="", prompt="", route={}) == "X" * 1000
    _, local = location()
    index = json.loads((local / "index.json").read_text(encoding="utf-8"))
    ref = next(item for item in index["artifacts"] if item["kind"] == "model-output")
    assert ref["truncated"] and ref["original_redacted_bytes"] == 1000
    assert "TRUNCATED" in next(local.rglob("model-output.txt")).read_text(encoding="utf-8")


def test_concurrent_process_journals_and_attempts_do_not_overwrite(project, monkeypatch):
    monkeypatch.setenv("VITA_TRACEPARENT", "00-" + "a" * 32 + "-" + "b" * 16 + "-01")

    def execute(number):
        return run_text(
            step="adapt",
            generate=Mock(return_value=f"Output {number}"),
            system=f"System {number}",
            prompt=f"Prompt {number}",
            route={},
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert set(pool.map(execute, range(3))) == {"Output 0", "Output 1", "Output 2"}
    trace = Path(".vita/logs/traces") / ("a" * 32)
    directories = list((trace / "journal").iterdir())
    assert len(directories) == 3
    assert {
        next(path.rglob("model-output.txt")).read_text(encoding="utf-8") for path in directories
    } == {"Output 0", "Output 1", "Output 2"}


def test_build_failure_keeps_compiler_arguments_and_full_stderr(project, monkeypatch):
    compiler = Mock(
        return_value=subprocess.CompletedProcess(
            [], 1, "Compiler stdout", "Missing command definition " + PRIVATE
        )
    )
    monkeypatch.setattr(build.subprocess, "run", compiler)
    assert build.run() is False
    _, local = location()
    request = json.loads(next(local.rglob("build-request.json")).read_text(encoding="utf-8"))
    result = json.loads(next(local.rglob("build-result.json")).read_text(encoding="utf-8"))
    assert request["argv"][0] == "latexmk"
    assert result["returncode"] == 1 and PRIVATE in result["stderr"]
    assert compiler.call_count == 1


@pytest.mark.parametrize(
    "output",
    [
        '{"answer":}',
        '{"answer":NaN}',
        '{"answer":"one","answer":"two"}',
        "non-JSON output\n" + PRIVATE,
    ],
)
def test_malformed_model_text_remains_exactly_inspectable(project, output):
    assert (
        run_text(step="cover", generate=Mock(return_value=output), system="", prompt="", route={})
        == output
    )
    assert next(location()[1].rglob("model-output.txt")).read_text(encoding="utf-8") == output


@pytest.mark.parametrize("process_override", [False, True])
def test_stage_environment_records_winning_value_and_source(project, monkeypatch, process_override):
    with Path(".vita/.env").open("a", encoding="utf-8") as stream:
        stream.write("\nEXTRACTION_MODEL=project-model\n")
    if process_override:
        monkeypatch.setenv("EXTRACTION_MODEL", "process-model")
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", Mock(return_value=Response(envelope('{"answer":"ok"}')))
    )
    assert extract_fixture() == {"answer": "ok"}
    source = next(
        row["details"]["settings"]["EXTRACTION_MODEL"]
        for row in events()
        if row["event"] == "configuration.environment"
    )
    assert source == {
        "value": "process-model" if process_override else "project-model",
        "source": "process_environment" if process_override else "project_env",
    }


def test_native_schema_fallback_is_logged_without_increasing_attempt_budget(project, monkeypatch):
    replies = iter([None, Response(envelope('{"answer":"ok"}'))])

    def respond(*args, **kwargs):
        reply = next(replies)
        if reply is None:
            raise urllib.error.HTTPError(
                "https://provider.invalid",
                400,
                "Unsupported",
                {},
                io.BytesIO(b'{"error":{"message":"responseJsonSchema is not supported"}}'),
            )
        return reply

    http = Mock(side_effect=respond)
    monkeypatch.setattr(llm.urllib.request, "urlopen", http)
    assert extract_fixture() == {"answer": "ok"}
    requests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in location()[1].rglob("http-request.json")
    ]
    assert sum("responseJsonSchema" in item["body"]["generationConfig"] for item in requests) == 1
    assert http.call_count == 2
    assert any(row["event"] == "retry.schema_mode_changed" for row in events())


def test_secret_fields_reasoning_and_command_line_credentials_are_removed(project):
    output = json.dumps(
        {
            "answer": PRIVATE,
            "api_key": "unknown-api-value",
            "token": "unknown-token-value",
            "reasoning_content": "internal-secret-thought",
            "parts": [{"thought": True, "text": "private-internal-thought"}],
        }
    )
    assert (
        run_text(step="cover", generate=Mock(return_value=output), system="", prompt="", route={})
        == output
    )
    saved = next(location()[1].rglob("model-output.txt")).read_text(encoding="utf-8")
    assert PRIVATE in saved
    assert all(
        text not in saved
        for text in (
            "unknown-api-value",
            "unknown-token-value",
            "internal-secret-thought",
            "private-internal-thought",
        )
    )
    assert journal.redact(
        ["--token=unknown", "--api-key", "another-value", "--model", "model-name"], set()
    ) == ["--token=" + journal.REDACTED, "--api-key", journal.REDACTED, "--model", "model-name"]


@pytest.mark.parametrize(
    "text,secret",
    [
        ('{"Authorization":"Basic unregistered-auth"', "unregistered-auth"),
        ('{"token":"unregistered-token', "unregistered-token"),
        ("Cookie: session=unregistered-cookie", "unregistered-cookie"),
    ],
)
def test_credentials_are_redacted_even_in_malformed_provider_text(project, text, secret):
    assert (
        run_text(step="cover", generate=Mock(return_value=text), system="", prompt="", route={})
        == text
    )
    saved = next(location()[1].rglob("model-output.txt")).read_text(encoding="utf-8")
    assert secret not in saved and journal.REDACTED in saved


def test_reading_extra_error_details_cannot_replace_the_provider_failure(project, monkeypatch):
    class Body:
        count = 0

        def read(self, size):
            self.count += 1
            if self.count == 1:
                return b"A" * 8192
            raise OSError("Synthetic extra-body read failure")

        def close(self):
            pass

    error = urllib.error.HTTPError("https://provider.invalid", 401, "Unauthorized", {}, Body())
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=error))
    with pytest.raises(StructuredOutputError) as stopped:
        extract_fixture()
    assert stopped.value.error["category"] == "authentication"
    assert any(row["event"] == "http.error_body_capture_failed" for row in events())


def test_reservation_cleanup_is_serialized_with_quota_readers(project, monkeypatch):
    trace = d.Trace()
    lock = d.storage_lock
    unlink = Path.unlink
    held = []
    observed = []

    @contextmanager
    def tracked_lock(base):
        with lock(base):
            held.append(True)
            try:
                yield
            finally:
                held.pop()

    def tracked_unlink(path, *args, **kwargs):
        if path == trace.reservation:
            observed.append(bool(held))
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(d, "storage_lock", tracked_lock)
    monkeypatch.setattr(Path, "unlink", tracked_unlink)
    trace.close("success")
    assert observed == [True]


def test_cli_timeout_retains_partial_output_without_exposing_credentials(project, monkeypatch):
    monkeypatch.setenv("VITA_PROVIDER_MAX_ATTEMPTS", "1")
    monkeypatch.setattr(llm, "_find_codex_cli", lambda: "synthetic-codex")
    cli = Mock(
        side_effect=subprocess.TimeoutExpired(
            "synthetic-codex",
            5,
            output=("Partial output " + PRIVATE).encode(),
            stderr=("Partial stderr " + SECRET).encode(),
        )
    )
    monkeypatch.setattr(llm.subprocess, "run", cli)
    with pytest.raises(StructuredOutputError):
        run_text(
            step="cover",
            generate=llm.generate,
            system="System",
            prompt="Input",
            route={"provider": "codex"},
        )
    saved = "\n".join(
        path.read_text(encoding="utf-8") for path in location()[1].rglob("exception-*.txt")
    )
    assert "Partial output " + PRIVATE in saved and "Partial stderr" in saved
    assert SECRET not in saved
    assert cli.call_count == 1
