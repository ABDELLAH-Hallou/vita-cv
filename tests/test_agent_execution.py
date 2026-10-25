"""Network-free agent controls, final-output handling and factual approval gates."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts.benchmark import execution_comparison as comparison
from scripts.benchmark import runner
from vita.commands import ai_step
from vita.helpers import agent_execution as agent
from vita.helpers import llm
from vita.helpers.context_builder import cv_source_files
from vita.helpers.provider_errors import ProviderError
from vita.helpers.structured_output import StructuredOutputError, run_structured

STREAM = (Path(__file__).parent / "fixtures/agent_execution/synthetic-success.jsonl").read_text(encoding="utf-8")


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VITA_AGENT_EXECUTION", raising=False)
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    monkeypatch.setenv("VITA_PROVIDER_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("VITA_PROVIDER_RETRY_MAX_SECONDS", "0")
    Path(".vita").mkdir()
    Path(".vita/config.json").write_text("{}")
    configure("restricted")
    Path("main.tex").write_text("\\documentclass{article}\n\\begin{document}\nEngineer, Sen 2017; TTR; OOP; 40\\%; degree in progress.\n\\input{education}\n\\end{document}\n", encoding="utf-8")
    Path("education.tex").write_text("Certificado Delta expired 2020; Université Boréal.\n", encoding="utf-8")
    Path("job.md").write_text("Python role; prefer cloud. Footer location is unrelated.\n")
    monkeypatch.setattr(llm, "_find_codex_cli", lambda: "synthetic-codex")
    return tmp_path


def configure(mode, **updates):
    Path(".vita/extensions.json").write_text(json.dumps({"llm_providers": {"codex": {
        "model": "exact/custom-agent-v1", "reasoning_effort": "high", "execution_mode": mode, **updates}}}))


def transport(monkeypatch, *, final="FINAL", stream=STREAM, unsupported=False, forbidden=False):
    calls = []
    def process(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if "--output-last-message" in cmd:
            if isinstance(final, Exception):
                raise final
            Path(cmd[cmd.index("--output-last-message") + 1]).write_text(final, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stream, "")
        if "--version" in cmd:
            value = "codex-cli 0.163.0-fixture"
        elif "--help" in cmd:
            value = "unsupported" if unsupported else "--ephemeral --json --config --output-last-message"
        elif "features" in cmd:
            value = '\n'.join(k + " stable " + ("false" if f"features.{k}=false" in cmd else "true") for k in agent.FEATURES)
        elif "mcp" in cmd:
            value = json.dumps([{"name": "synthetic", "enabled": forbidden or not any("mcp_servers.synthetic=" in v for v in cmd), "transport": {"url": "https://private.invalid/?secret=DO_NOT_COPY"}}])
        else:
            raise AssertionError("Unexpected process")
        return subprocess.CompletedProcess(cmd, 0, value, "")
    monkeypatch.setattr(subprocess, "run", process)
    return calls


def test_baseline_remains_original_command_and_final_file(project, monkeypatch):
    configure("baseline")
    calls = transport(monkeypatch)
    assert llm.generate("system", "task", provider="codex") == "FINAL"
    assert len(calls) == 1
    command = calls[0][0]
    assert "--ephemeral" not in command and "--json" not in command
    assert command[command.index("--model") + 1] == "exact/custom-agent-v1"
    assert 'model_reasoning_effort="high"' in command


def test_restricted_controls_model_reasoning_and_final_contract(project, monkeypatch):
    calls = transport(monkeypatch)
    session = {}
    assert llm.generate("system", "COMPLETE CV", provider="codex", session=session) == "FINAL"
    command, arguments = calls[-1]
    assert all(v in command for v in ("--ephemeral", "--json", 'features.shell_tool=false', 'features.multi_agent=false', 'features.plugins=false', 'web_search="disabled"'))
    assert not any(v.startswith("--ignore") or "bypass" in v for v in command)
    assert "DO_NOT_COPY" not in str(command)
    assert 'url="https://disabled.invalid"' in str(command)
    assert "GENERATION ONLY" in arguments["input"] and "COMPLETE CV" in arguments["input"]
    assert arguments["timeout"] == 600
    assert session["execution"]["restriction_status"] == "verified_local_controls"
    assert session["execution"]["cli_version"] == "codex-cli 0.163.0-fixture"
    assert session["route"]["model"] == "exact/custom-agent-v1" and session["route"]["reasoning_effort"] == "high"
    telemetry = session["agent_telemetry"]
    assert telemetry["model_calls"] is None and telemetry["cost"] is None
    assert telemetry["usage"]["cached_input_tokens"] == 80
    assert "SYNTHETIC_HIDDEN" not in json.dumps(telemetry)


@pytest.mark.parametrize("mode", ["unsupported", "mandatory_mcp"])
def test_restriction_failure_never_falls_back_or_generates(project, monkeypatch, mode):
    calls = transport(monkeypatch, unsupported=mode == "unsupported", forbidden=mode == "mandatory_mcp")
    with pytest.raises(ProviderError) as error:
        llm.generate("system", "task", provider="codex")
    assert error.value.code == "configuration"
    assert not any("--output-last-message" in c for c, _ in calls)


@pytest.mark.parametrize("updates", [{"reasoning_effort": None}, {"model": ""}, {"execution_mode": "fast"}, {"agent_timeout_seconds": 0}, {"max_input_bytes": 0}])
def test_invalid_or_inherited_configuration_cannot_be_called_optimized(project, monkeypatch, updates):
    configure("restricted", **updates)
    calls = transport(monkeypatch)
    with pytest.raises(ProviderError):
        llm.generate("system", "task", provider="codex")
    assert not calls


def test_context_guard_does_not_dispatch_or_truncate(project, monkeypatch):
    configure("restricted", max_input_bytes=10)
    calls = transport(monkeypatch)
    with pytest.raises(ProviderError) as error:
        llm.generate("full system", "FULL DOCUMENT HISTORY" * 100, provider="codex")
    assert error.value.limit_kind == "input_context" and not error.value.retryable
    assert not calls


@pytest.mark.parametrize("bad", ["missing.tex", "../outside.tex", r"\dynamic"])
def test_complete_source_graph_rejects_missing_external_and_dynamic(project, bad):
    Path("main.tex").write_text("\\input{" + bad + "}")
    with pytest.raises(ValueError):
        cv_source_files("main.tex", strict=True)


def test_included_and_prior_inputs_preserve_boundaries(project, monkeypatch):
    Path(".vita/results").mkdir()
    Path(".vita/results/analysis.json").write_text('{"executive_summary":"ADVICE_NOT_EVIDENCE"}')
    calls = transport(monkeypatch, final="```latex\n" + Path("main.tex").read_text(encoding="utf-8") + "\n```")
    assert ai_step.run("adapt", auto=True, provider="codex", language="fr")
    prompt = next(k["input"] for c, k in reversed(calls) if "--output-last-message" in c)
    for value in ("Certificado Delta expired 2020", "Université Boréal", "ADVICE_NOT_EVIDENCE", "NON-EVIDENTIARY", "Sen 2017", "**French**", "src-"):
        assert value in prompt


def test_missing_input_stops_before_generation(project, monkeypatch):
    Path("education.tex").unlink()
    calls = transport(monkeypatch)
    assert not ai_step.run("adapt", auto=True, provider="codex")
    assert not calls


def test_manual_prompt_separates_generation_and_host_tools(project):
    assert ai_step.run("adapt", auto=False, provider="codex")
    prompt = Path(".vita/prompts/adapt.md").read_text(encoding="utf-8")
    assert "HOST OPERATIONS" in prompt and "Host capture/validation/saving commands may use tools" in prompt
    assert "Certificado Delta expired 2020" in prompt
    assert "vita facts capture adapt" in prompt and "vita facts check adapt --proposal" in prompt
    assert "GENERATION OUTPUT CONTRACT" in prompt and "exactly one ```latex code block" in prompt


def test_unresolved_fact_edit_preserves_original_and_remains_inspectable(project, monkeypatch):
    before = Path("main.tex").read_bytes()
    proposal = before.decode().replace("Sen 2017", "September 2017").replace("TTR", "Time to Resolution")
    transport(monkeypatch, final="```latex\n" + proposal + "\n```")
    assert not ai_step.run("adapt", auto=True, provider="codex")
    assert Path("main.tex").read_bytes() == before
    report = json.loads(Path(".vita/results/adapt.facts.json").read_text(encoding="utf-8"))
    assert report["status"] == "confirmation_required" and "September 2017" in report["document"]
    assert not ai_step.run("cover", auto=True, provider="codex")


@pytest.mark.parametrize("category,text", [("refusal", "request refused"), ("invalid_request", "context length exceeded"), ("incomplete_response", "output truncated")])
def test_structured_agent_failure_categories(project, monkeypatch, category, text):
    transport(monkeypatch, stream=json.dumps({"type": "turn.failed", "error": {"message": text}}))
    with pytest.raises(ProviderError) as error:
        llm.generate("system", "task", provider="codex")
    assert error.value.code == category


def test_timeout_uses_shared_budget_and_unknown_usage(project, monkeypatch):
    calls = transport(monkeypatch, final=subprocess.TimeoutExpired("synthetic-codex", 600))
    with pytest.raises(StructuredOutputError):
        run_structured(step="extract", generate=llm.generate, system="system", prompt="task", route={"provider": "codex"}, schema={"type": "object"}, finalize=lambda x: x, save=lambda x: None)
    generations = [c for c, _ in calls if "--output-last-message" in c]
    assert len(generations) == 3
    record = json.loads(Path(".vita/results/extract.outcome.json").read_text())
    assert record["attempt_count"] == 3 and record["error"]["category"] == "timeout"
    assert all(a["agent_telemetry"]["usage"] is None for a in record["attempts"])


def test_unobserved_stream_is_not_zero_activity_or_a_valid_completion(project, monkeypatch):
    transport(monkeypatch, stream="not JSON events")
    with pytest.raises(ProviderError):
        llm.generate("system", "task", provider="codex")
    assert agent.events("not JSON events")["tool_calls"] is None


def test_restricted_forbidden_activity_fails_even_with_final_file(project, monkeypatch):
    stream = STREAM + '\n' + json.dumps({"type": "item.completed", "item": {"type": "mcp_tool_call", "id": "x", "status": "completed"}})
    transport(monkeypatch, stream=stream)
    with pytest.raises(ProviderError) as error:
        llm.generate("system", "task", provider="codex")
    assert error.value.code == "configuration"


def test_plan_pairing_order_optional_reasoning_and_authorization(tmp_path):
    baseline = comparison.plan("exact/model", "high", repeats=2)
    runner.validate_plan(baseline, live=False)
    assert len(baseline["cases"]) == 40
    for a, b in zip(baseline["cases"][::2], baseline["cases"][1::2], strict=True):
        assert a["scenario"] == b["scenario"] and a["repeat"] == b["repeat"]
        assert a["model"] == b["model"] and a["reasoning_effort"] == b["reasoning_effort"]
        assert a["execution_mode"] == "baseline" and b["execution_mode"] == "restricted"
    assert comparison.plan("exact/model", "high", reverse=True)["cases"][0]["arm"] == "B"
    optional = comparison.plan("exact/model", "high", lower_reasoning="low")
    assert next(c for c in optional["cases"] if c["arm"] == "C")["reasoning_effort"] == "low"
    assert runner.object_hash(baseline) != runner.object_hash(optional)
    assert comparison.THRESHOLDS["status"].startswith("proposed")


def test_reports_keep_not_run_and_unknown_quality_visible(tmp_path):
    plan = comparison.plan("exact/model", "high")
    runner.write(tmp_path / "manifest.json", {"plan": plan, "plan_sha256": runner.object_hash(plan), "settings": {"mode": "fixture"}})
    runner.write(tmp_path / "summary.json", {"cases": []})
    report = comparison.report(tmp_path)
    assert report["not_run"] == 40 and report["attempted"] == 0
    assert report["decision"].startswith("inconclusive")
    assert report["model_calls"] is None and report["accuracy"]["harmful_omissions"]["numerator"] is None
    compact = runner.read(tmp_path / "execution-comparison.compact.json")
    assert compact["not_run"] == 40 and "stage_metrics" in compact
    assert compact["detail_report_sha256"] == runner.digest((tmp_path / "execution-comparison.json").read_bytes())


def test_hidden_events_and_legacy_reasoning_are_not_logged():
    assert "SYNTHETIC_HIDDEN_DO_NOT_KEEP" not in agent.log_output(STREAM)
    assert "SYNTHETIC_HIDDEN" not in agent.log_output("thinking\nSYNTHETIC_HIDDEN\ncodex\nFinal")
    assert agent.log_output("HTTP status 503") == "HTTP status 503"


@pytest.mark.parametrize("content", [r"\input main.tex", r"\input{main}"])
def test_incomplete_or_cyclic_include_syntax_is_actionable(project, content):
    Path("main.tex").write_text(content)
    with pytest.raises(ValueError):
        cv_source_files("main.tex", strict=True)


def test_paired_settings_cannot_silently_change_model_or_reasoning():
    plan = comparison.plan("exact/model", "high")
    plan["cases"][1]["reasoning_effort"] = "low"
    with pytest.raises(ValueError, match="A/B"):
        runner.validate_plan(plan, live=False)
    with pytest.raises(ValueError):
        comparison.plan("exact/model", "low", lower_reasoning="high")


def test_transport_and_format_recovery_share_three_attempts(project, monkeypatch):
    base_calls = transport(monkeypatch)
    original = subprocess.run
    generated = []
    def request(cmd, **kwargs):
        if "--output-last-message" not in cmd:
            return original(cmd, **kwargs)
        generated.append(cmd)
        if len(generated) == 1:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP status 503")
        value = "{malformed" if len(generated) == 2 else '{"answer":"safe"}'
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(value)
        return subprocess.CompletedProcess(cmd, 0, STREAM, "")
    monkeypatch.setattr(subprocess, "run", request)
    saved = []
    result = run_structured(step="extract", generate=llm.generate, system="system", prompt="task", route={"provider":"codex"},
                            schema={"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"],"additionalProperties":False},
                            finalize=lambda x:x, save=saved.append)
    assert result == {"answer":"safe"} and saved == [result] and len(generated) == 3
    record = json.loads(Path(".vita/results/extract.outcome.json").read_text())
    assert [a["category"] for a in record["attempts"]] == ["overloaded", "invalid_json", "valid"]
    assert [a["execution"]["capability_processes"] for a in record["attempts"]] == [6, 0, 0]
    assert all('model_reasoning_effort="high"' in c for c in generated)
    assert base_calls  # Local checks were mocked; no real process/provider ran.


def test_denied_calls_are_deduplicated_and_unidentified_calls_unknown():
    items = [{"type":"turn.started"}, *[{"type":kind,"item":{"id":"same","type":"mcp_tool_call","status":"denied"}} for kind in ("item.started","item.completed")], {"type":"turn.completed"}]
    telemetry = agent.events("\n".join(map(json.dumps, items)))
    assert telemetry["tool_calls"] == {"mcp":1} and telemetry["denied_tool_calls"] == 1
    items.insert(1,{"type":"item.completed","item":{"type":"command_execution"}})
    telemetry = agent.events("\n".join(map(json.dumps, items)))
    assert telemetry["tool_calls"] is None and "shell" in telemetry["observed_tool_types"]


def test_tool_ids_can_repeat_in_distinct_turns_without_undercounting():
    turn = [{"type":"turn.started"}, {"type":"item.completed","item":{"id":"same","type":"command_execution","status":"denied"}}, {"type":"turn.completed"}]
    result = agent.events("\n".join(map(json.dumps, turn + turn)))
    assert result["turns_completed"] == 2 and result["model_calls"] is None
    assert result["tool_calls"] == {"shell":2} and result["denied_tool_calls"] == 2


def test_multilingual_fixture_evidence_tracks_preamble_source_lines(tmp_path, monkeypatch):
    from scripts.benchmark.fixture_transport import answer
    from vita.helpers.candidate_evidence import candidate_instruction, capture_candidate_sources
    case = next(c for c in comparison.plan("fixture/model", "high")["cases"] if c["scenario"] == "arabic")
    runner.project_setup(tmp_path / "project", case)
    monkeypatch.chdir(tmp_path / "project")
    snapshot = capture_candidate_sources()
    response = json.loads(answer(candidate_instruction(snapshot)))
    ref = response["metrics"]["criteria"][0]["evidence_refs"][0]
    source = next(s for s in snapshot["sources"] if s["id"] == ref["source_id"])
    assert ref["line_start"] > 4
    assert ref["quote"] in source["content"].split("\n")[ref["line_start"] - 1]


def test_timeout_diagnostics_never_receive_raw_partial_reasoning(project, monkeypatch):
    timeout = subprocess.TimeoutExpired("synthetic-codex", 600, output=STREAM, stderr="SYNTHETIC_HIDDEN_STDERR")
    transport(monkeypatch, final=timeout)
    captured = []
    monkeypatch.setattr(llm.diagnostic, "failure", lambda phase, exc=None, **kwargs: captured.append(exc))
    session = {}
    with pytest.raises(ProviderError) as error:
        llm.generate("system", "task", provider="codex", session=session)
    assert error.value.code == "timeout"
    assert any(isinstance(e, subprocess.TimeoutExpired) for e in captured)
    assert timeout.output is None and timeout.stderr is None
    assert session["agent_telemetry"]["process_outcome"] == "timeout"
    assert "SYNTHETIC_HIDDEN" not in json.dumps(session["agent_telemetry"])


def test_report_distinguishes_text_contract_from_failed_document_gate(tmp_path):
    plan = comparison.plan("fixture/model", "high")
    case = plan["cases"][0]
    runner.write(tmp_path / "manifest.json", {"plan":plan,"plan_sha256":runner.object_hash(plan),"settings":{"mode":"fixture"}})
    outcome = {"run_id":"synthetic-adapt","status":"success","duration_seconds":1,"time_to_contract_valid_seconds":.5,"attempts":[{"category":"valid"}]}
    command = {"label":"pipeline","exit_status":1,"duration_seconds":2,"outputs":[],"outcomes":{"adapt.outcome.json":outcome},"pending_confirmation":None,
               "transport":{"requests":[{"step":"adapt"}]}}
    runner.write(tmp_path / "summary.json", {"cases":[{"id":case["id"],"status":"failed","commands":[command]}]})
    value = comparison.report(tmp_path)
    row = next(s for s in value["stages"] if s["execution"] == "baseline" and s["stage"] == "adapt")
    assert row["operations"][0]["terminal"] == "post_generation_failure"
    assert row["time_to_contract_valid_seconds"]["n"] == 1
    assert row["time_to_validated_output_seconds"]["n"] == 0


def test_report_deduplicates_generation_outcomes_and_includes_resume(tmp_path):
    plan = comparison.plan("fixture/model", "high")
    runner.write(tmp_path / "manifest.json", {"plan":plan,"plan_sha256":runner.object_hash(plan),"settings":{"mode":"fixture"}})
    before = {"run_id":"synthetic-adapt","status":"success","duration_seconds":1,"attempts":[{"category":"valid"}]}
    after = {"run_id":"synthetic-review","status":"success","duration_seconds":2,"attempts":[{"category":"valid"}]}
    root = {"label":"pipeline","exit_status":1,"duration_seconds":2,"outputs":[],"outcomes":{"adapt.outcome.json":before},
            "pending_confirmation":{"step":"adapt"},"resolved_confirmation":{"step":"adapt"},"transport":{"requests":[{"step":"adapt"}]}}
    resumed = {"label":"resumed-review","exit_status":0,"duration_seconds":3,"outputs":[],"pending_confirmation":None,
               "outcomes":{"adapt.outcome.json":before,"review.outcome.json":after},"transport":{"requests":[{"step":"review"}]}}
    runner.write(tmp_path / "summary.json", {"cases":[{"id":plan['cases'][0]['id'],"status":"passed","commands":[root,resumed]}]})
    value = comparison.report(tmp_path)
    adapt = next(s for s in value["stages"] if s["execution"] == "baseline" and s["stage"] == "adapt")
    review = next(s for s in value["stages"] if s["execution"] == "baseline" and s["stage"] == "review")
    assert adapt["attempted_operations"] == 1 and adapt["operations"][0]["terminal"] == "success"
    assert review["attempted_operations"] == 1 and value["host_generation_dispatches"] == 2


def test_host_stage_timings_include_outer_gate_and_do_not_double_count(tmp_path):
    path = tmp_path / "public-events.jsonl"
    def start(identity, parent, phase):
        return {"event":"span_start","span_id":identity,"parent_span_id":parent,"phase":phase,"step":"adapt"}
    def end(identity, phase, duration):
        return {"event":"span_end","span_id":identity,"phase":phase,"step":"adapt","status":"ok","details":{"duration_ms":duration}}
    a,b,c = "a"*16,"b"*16,"c"*16
    values = [start(a,None,"step"),start(b,a,"step"),start(c,b,"validation"),end(c,"validation",20),end(b,"step",100),end(a,"step",500)]
    path.write_text("\n".join(map(json.dumps, values)))
    result = runner.public_span_timings([path])
    assert len(result["stage_spans"]) == 1 and result["stage_spans"][0]["duration_seconds"] == .5
    assert len(result["spans"]) == 3
    path.write_text(json.dumps(start(a,None,"step")))
    result = runner.public_span_timings([path])
    assert result["status"] == "partial" and result["stage_spans"][0]["duration_seconds"] is None


def test_preflight_timeout_clears_private_discovery_output(monkeypatch):
    failure = subprocess.TimeoutExpired("synthetic-codex",20,output="PRIVATE_MCP_TRANSPORT",stderr="PRIVATE_MCP_HEADER")
    monkeypatch.setattr(subprocess,"run",lambda *a,**k: (_ for _ in ()).throw(failure))
    with pytest.raises(ProviderError) as error:
        agent.local("synthetic-codex",["mcp","list","--json"])
    assert error.value.code == "configuration" and failure.output is None and failure.stderr is None
