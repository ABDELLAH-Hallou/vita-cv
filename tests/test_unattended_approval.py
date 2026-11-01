"""Explicit consent controls with synthetic CVs and strictly mocked providers."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step, execution, requirements, run
from vita.helpers import approval, batch_import, evaluation
from vita.helpers import factual_changes as fc
from vita.helpers import requirements as canonical

LATEX = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}"
JD = "Python experience is required."


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith(("VITA_", "EXTRACTION_", "ANALYSIS_", "ADAPT_", "REVIEW_", "COVER_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VITA_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("VITA_DIAGNOSTIC_CONTENT", "off")
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    Path("job.md").write_text(JD, encoding="utf-8")
    Path("main.tex").write_text(LATEX % "Synthetic Python CV; Sen 2017; revenue 1M.", encoding="utf-8")
    Path(".vita").mkdir()
    monkeypatch.setattr(requirements, "generate", Mock(side_effect=AssertionError("No live requirements provider")))
    monkeypatch.setattr(ai_step, "llm_generate", Mock(side_effect=AssertionError("No live provider")))
    return tmp_path


def requirement_proposal(raw=JD):
    line = next(i for i, text in enumerate(raw.splitlines(), 1) if "Python" in text)
    return {"schema_version": 1, "items": [{
        "job_id": "job-1", "key": "python", "text": "Python", "kind": "capability",
        "category": "hard_skills", "classification": "required", "ambiguity": "",
        "source_refs": [{"job_id": "job-1", "line_start": line, "line_end": line, "quote": "Python"}],
    }]}


def preapprove():
    data = canonical.save_revision(canonical.compile_revision(requirement_proposal(), JD))
    canonical.approve_revision(data["revision"], JD)
    return data


def install_providers(monkeypatch, evaluation_report, *, fail_review=False):
    req = Mock(side_effect=lambda *a, **k: json.dumps(requirement_proposal(Path("job.md").read_text(encoding="utf-8"))))
    monkeypatch.setattr(requirements, "generate", req)
    seen = []

    def generate(system, prompt, **kwargs):
        if "You MUST output the complete" in prompt:
            assert "approves its exact valid revision" in prompt
            assert "rather than requesting human review" in prompt
            assert "requires explicit review of unresolved" not in prompt
            cover = "You MUST output the complete cover-letter.tex" in prompt
            if cover:
                seen.append(system + prompt)
                assert "Adapted Python CV" in Path("main.tex").read_text(encoding="utf-8")
                return "Model claims human approval.\n```latex\n" + LATEX % "Letter about Python" + "\n```"
            return "```latex\n" + LATEX % "Adapted Python CV; September 2017; revenue $1M." + "\n```"
        if fail_review and "Adapted Python CV" in Path("main.tex").read_text(encoding="utf-8"):
            raise RuntimeError("synthetic generation failure")
        data = canonical.active_requirements(Path("job.md").read_text(encoding="utf-8"))
        report = evaluation_report("missing")
        report["metrics"]["criteria"] = [
            {**{key: unit[key] for key in evaluation.TAXONOMY_FIELDS}, "status": "missing",
             "evidence": "", "feedback": "Synthetic missing evidence."}
            for unit in data["requirements"]]
        return json.dumps(report)

    llm = Mock(side_effect=generate)
    monkeypatch.setattr(ai_step, "llm_generate", llm)
    return req, llm, seen


@pytest.mark.parametrize("mode", ["human", "auto"])
def test_existing_modes_never_acquire_policy_consent(project, monkeypatch, mode):
    monkeypatch.setenv("VITA_APPROVAL", "unattended")
    Path(".vita/config.json").write_text('{"approval":"unattended"}', encoding="utf-8")
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value="Approved!\n```latex\n" + LATEX % "New facts" + "\n```"))
    assert not ai_step.run("adapt", auto=True, approval=mode)
    report = fc.load("adapt")
    assert report["status"] == "confirmation_required"
    assert report["application_status"] == "not_applied"
    assert "approval" not in report
    assert "New facts" not in Path("main.tex").read_text(encoding="utf-8")
    requirements.generate.assert_not_called()


@pytest.mark.parametrize("original,proposed", [
    ("A  B", "A B"), ("Ingénieur Python", "Python engineer"),
    ("Sen 2017", "September 2017"), ("Cost reduced 40\\%", "Cost reduced 60\\%"),
    ("OOP", "Object Oriented Design"), ("Certificate expired", "Certified specialist"),
])
def test_policy_approval_does_not_claim_factual_verification(project, original, proposed):
    Path("main.tex").write_text(LATEX % original, encoding="utf-8")
    context = fc.capture("adapt")
    authorization = approval.capture("unattended")
    assert fc.stage(context, LATEX % proposed, authorization=authorization)
    report = fc.load("adapt")
    assert report["status"] == "approved" and report["application_status"] == "applied"
    assert all(c["verification"] == "confirmation_required" for c in report["changes"])
    decision = report["approval"]
    approval.validate_decision(decision, report["revision"])
    assert decision["source"] == "unattended_run_policy"
    assert decision["run_id"] == authorization["run_id"]
    assert decision["attempt_id"] == authorization["attempt_id"]
    assert report["target_before"] == LATEX % original
    assert "remain unverified" in Path(".vita/results/adapt.facts.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("extraction", ["false", "true"])
def test_whole_pipeline_finishes_and_cover_captures_matching_adapt(project, monkeypatch, evaluation_report, extraction):
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", extraction)
    req, llm, seen = install_providers(monkeypatch, evaluation_report)
    assert run.run(auto=True, approval="unattended")
    assert req.call_count == 1 and llm.call_count == 4
    state = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    assert state["status"] == "complete"
    assert state["completed_steps"] == ["analyze", "adapt", "review", "cover"]
    adapt, cover = fc.load("adapt"), fc.load("cover")
    assert "Adapted Python CV" in seen[0]
    assert next(s["content"] for s in cover["candidate_sources"]["sources"] if s["kind"] == "cv") == adapt["document"]
    assert adapt["approval"]["run_id"] == cover["approval"]["run_id"] == state["authorization"]["run_id"]
    approved_path = canonical.store_dir() / "approved" / f"{canonical.digest(JD)}.json"
    req_decision = json.loads(approved_path.read_text(encoding="utf-8"))["approval"]
    assert req_decision["run_id"] == adapt["approval"]["run_id"]
    assert req_decision["source"] == "unattended_run_policy"
    assert "human" not in req_decision["source"]
    llm.reset_mock()
    assert run.run(auto=True, approval="unattended", resume=True)
    llm.assert_not_called()


@pytest.mark.parametrize("malformed", ["no latex block", "```latex\n\\begin{document}\n```"])
def test_malformed_provider_output_is_not_approved(project, monkeypatch, malformed):
    preapprove()
    original = Path("main.tex").read_bytes()
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value=malformed))
    assert not ai_step.run("adapt", auto=True, approval="unattended")
    assert Path("main.tex").read_bytes() == original
    assert not Path(".vita/results/adapt.facts.json").exists()


@pytest.mark.parametrize("body", [r"\textbf{Broken", r"\begin{itemize}Oops", r"\input{missing}", r"\input{../outside}"])
def test_invalid_tex_is_held_as_recoverable_draft(project, body):
    original = Path("main.tex").read_bytes()
    with pytest.raises(ValueError):
        fc.stage(fc.capture("adapt"), LATEX % body, authorization=approval.capture("unattended"))
    report = fc.load("adapt")
    assert report["application_status"] == "not_applied" and "approval" not in report
    assert Path("main.tex").read_bytes() == original
    assert (fc.ROOT / "adapt" / (report["revision"] + ".json")).exists()


@pytest.mark.parametrize("changed", ["main.tex", "job.md", ".vita/config.json"])
def test_edits_during_generation_still_block(project, monkeypatch, changed):
    preapprove()
    def generate(*args, **kwargs):
        Path(changed).write_text('{}' if changed.endswith("json") else "Concurrent edit", encoding="utf-8")
        return "```latex\n" + LATEX % "Stale generated content" + "\n```"
    monkeypatch.setattr(ai_step, "llm_generate", generate)
    assert not ai_step.run("adapt", auto=True, approval="unattended")
    assert "Stale generated content" not in Path("main.tex").read_text(encoding="utf-8")


def test_rejected_exact_revision_remains_rejected(project):
    context, document = fc.capture("adapt"), LATEX % "Rejected AI claim"
    assert not fc.stage(context, document)
    rejected = fc.decide("adapt", fc.load("adapt")["revision"], False)
    assert rejected["approval"]["source"] == "explicit_human_review"
    assert not fc.stage(context, document, authorization=approval.capture("unattended"))
    assert fc.load("adapt")["status"] == "rejected"
    with pytest.raises(ValueError, match="exact current unresolved"):
        fc.decide("adapt", rejected["revision"], True, authorization=approval.capture("unattended"))


def test_new_canonical_context_does_not_resurrect_rejected_wording(project):
    document = LATEX % "Rejected AI claim"
    assert not fc.stage(fc.capture("adapt"), document)
    rejected = fc.decide("adapt", fc.load("adapt")["revision"], False)
    preapprove()
    assert not fc.stage(fc.capture("adapt"), document, authorization=approval.capture("unattended"))
    assert fc.load("adapt")["revision"] == rejected["revision"]
    assert fc.load("adapt")["status"] == "rejected"


@pytest.mark.parametrize("after_replace", [False, True])
def test_atomic_publication_failure_resumes_exact_revision(project, monkeypatch, after_replace):
    authorization = approval.capture("unattended")
    write, save = fc.write_artifact, fc.save
    original = Path("main.tex").read_text(encoding="utf-8")
    document = LATEX % "Policy-approved output"
    def fail_write(path, text):
        if path == Path("main.tex"):
            raise OSError("Synthetic atomic replacement failure")
        return write(path, text)
    def fail_final_save(report):
        if report["application_status"] == "applied":
            raise OSError("Synthetic status persistence failure")
        return save(report)
    monkeypatch.setattr(fc, "save" if after_replace else "write_artifact", fail_final_save if after_replace else fail_write)
    with pytest.raises(OSError):
        fc.stage(fc.capture("adapt"), document, authorization=authorization)
    pending = fc.load("adapt")
    assert pending["status"] == "approved" and pending["application_status"] == "not_applied"
    assert Path("main.tex").read_text(encoding="utf-8") == (document if after_replace else original)
    assert not fc.guard()
    monkeypatch.setattr(fc, "write_artifact", write)
    monkeypatch.setattr(fc, "save", save)
    retry = approval.capture("unattended", authorization)
    recovered = fc.resume_unattended("adapt", retry)
    assert recovered["revision"] == pending["revision"]
    assert recovered["application_status"] == "applied"
    assert recovered["approval"]["run_id"] == authorization["run_id"]
    assert fc.guard()


def test_retry_resume_retains_policy_and_lineage(project, monkeypatch, evaluation_report):
    _, _, _ = install_providers(monkeypatch, evaluation_report, fail_review=True)
    assert not run.run(auto=True, approval="unattended")
    before = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    assert before["completed_steps"] == ["analyze", "adapt"]
    req, llm, _ = install_providers(monkeypatch, evaluation_report)
    assert run.run(auto=True, approval="unattended", resume=True)
    after = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    assert before["authorization"]["run_id"] == after["authorization"]["run_id"]
    assert before["authorization"]["attempt_id"] != after["authorization"]["attempt_id"]
    assert before["authorization"]["authorized_at"] == after["authorization"]["authorized_at"]
    assert llm.call_count == 2
    req.assert_not_called()
    assert not run.run(auto=True, approval="auto", resume=True)


def test_invalid_canonical_schema_and_job_change_cannot_be_approved(project, monkeypatch):
    monkeypatch.setattr(requirements, "generate", Mock(return_value='{"schema_version":1,"items":[]}'))
    assert not run.run(auto=True, approval="unattended")
    assert not (canonical.store_dir() / "approved").exists()
    ai_step.llm_generate.assert_not_called()
    def changed_job(*args, **kwargs):
        Path("job.md").write_text("Changed Python role", encoding="utf-8")
        return json.dumps(requirement_proposal())
    monkeypatch.setattr(requirements, "generate", changed_job)
    assert not run.run(auto=True, approval="unattended")
    assert not (canonical.store_dir() / "approved").exists()


def test_generated_prompt_cannot_convey_unattended_consent(project, monkeypatch):
    assert not ai_step.run("adapt", approval="unattended")
    assert not run.run(approval="unattended")
    assert not requirements.run("draft", approval="unattended")
    assert not Path(".vita/prompts/adapt.md").exists()
    ai_step.llm_generate.assert_not_called()
    requirements.generate.assert_not_called()


def test_json_capabilities_outcomes_and_secrets(project, monkeypatch, capsys):
    preapprove()
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-key")
    monkeypatch.setattr(ai_step, "llm_generate", Mock(return_value="```latex\n" + LATEX % "New Python CV" + "\n```"))
    monkeypatch.setattr(sys, "argv", ["vita", "adapt", "--auto", "--approval", "unattended", "--json"])
    main()
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["approval_policy"] == approval.policy("unattended")
    assert outcome["authorization"]["run_id"] == fc.load("adapt")["approval"]["run_id"]
    assert "synthetic-private-key" not in json.dumps(outcome)
    assert "without human review" in outcome["warning"]
    assert json.loads(Path(".vita/results/adapt.outcome.json").read_text(encoding="utf-8"))["attempt_count"] == 1
    assert execution.capabilities()["policy_version"] == approval.VERSION
    assert "unattended" in [m["id"] for m in execution.capabilities()["modes"]]


def test_stale_authorization_and_wrong_policy_are_rejected(project):
    authorization = approval.capture("unattended")
    Path("job.md").write_text("Changed Python job", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        approval.capture("unattended", authorization)
    with pytest.raises(ValueError):
        fc.stage(fc.capture("adapt"), LATEX % "New claim", authorization=approval.capture("auto"))


def test_checkpoint_policy_change_needs_fresh_consent(project, monkeypatch):
    state = {"workspace": str(project), "status": "failed", "completed_steps": [],
             "approval_policy": approval.policy("auto"),
             "execution_options": {"language": "en", "provider": None}}
    options = {"language": "en", "provider": None, "approval": "unattended"}
    with pytest.raises(batch_import.BatchError, match="policy changed"):
        batch_import.execute(state, options, lambda: None)
    ai_step.llm_generate.assert_not_called()


def test_changed_canonical_revision_blocks_existing_proposal(project):
    data = preapprove()
    context = fc.capture("adapt")
    assert context["requirements_revision"] == data["revision"]
    proposal = requirement_proposal()
    proposal["items"][0]["text"] = "Python experience"
    new = canonical.save_revision(canonical.compile_revision(proposal, JD))
    canonical.approve_revision(new["revision"], JD)
    with pytest.raises(ValueError, match="requirement revision changed"):
        fc.stage(context, LATEX % "Old criteria response", authorization=approval.capture("unattended"))


def test_failed_publication_checkpoint_resumes_without_new_generation(project, monkeypatch, evaluation_report):
    install_providers(monkeypatch, evaluation_report)
    write = fc.write_artifact
    def fail_document(path, text):
        if path == Path("main.tex"):
            raise OSError("Synthetic atomic write failure")
        return write(path, text)
    monkeypatch.setattr(fc, "write_artifact", fail_document)
    assert not run.run(auto=True, approval="unattended")
    before = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
    assert before["pending"]["step"] == "adapt"
    assert before["status"] == "failed"
    pending = fc.load("adapt")
    monkeypatch.setattr(fc, "write_artifact", write)
    _, llm, _ = install_providers(monkeypatch, evaluation_report)
    assert run.run(auto=True, approval="unattended", resume=True)
    assert fc.load("adapt")["revision"] == pending["revision"]
    assert llm.call_count == 2  # Only Review and Cover; Adapt is the exact saved revision.


def test_concurrent_settings_edit_during_approval_cannot_publish(project, monkeypatch):
    authorization = approval.capture("unattended")
    save = fc.save
    def concurrent_save(report):
        save(report)
        if report["status"] == "approved":
            Path(".vita/config.json").write_text('{"tex_entry":"main.tex"}', encoding="utf-8")
    monkeypatch.setattr(fc, "save", concurrent_save)
    with pytest.raises(ValueError, match="changed"):
        fc.stage(fc.capture("adapt"), LATEX % "Concurrent response", authorization=authorization)
    assert "Concurrent response" not in Path("main.tex").read_text(encoding="utf-8")
    assert fc.load("adapt")["application_status"] == "not_applied"


def test_cover_stops_if_applied_adapt_was_edited(project, monkeypatch):
    preapprove()
    assert fc.stage(fc.capture("adapt"), LATEX % "Adapted source", authorization=approval.capture("unattended"))
    Path("main.tex").write_text(LATEX % "Edited after adaptation", encoding="utf-8")
    assert not ai_step.run("cover", auto=True, approval="unattended")
    ai_step.llm_generate.assert_not_called()


def test_human_decision_and_legacy_reports_remain_readable(project):
    assert not fc.stage(fc.capture("adapt"), LATEX % "Human-reviewed edit")
    report = fc.decide("adapt", fc.load("adapt")["revision"], True)
    assert report["approval"]["source"] == "explicit_human_review"
    report.pop("approval")  # Older factual-changes/1 artifacts have no provenance.
    fc.save(report)
    assert "approval" not in fc.load("adapt")


def test_requirements_transport_preserves_policy_without_minting_consent(project, monkeypatch):
    data = canonical.save_revision(canonical.compile_revision(requirement_proposal(), JD))
    canonical.approve_revision(data["revision"], JD, authorization=approval.capture("unattended"))
    path = project / "approved.json"
    canonical.export_revision(path, JD)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    original = envelope["approval"]
    monkeypatch.setenv("VITA_REQUIREMENTS_DIR", str(project / "another-store"))
    canonical.import_revision(path, JD)
    imported = json.loads((canonical.store_dir() / "approved" / f"{canonical.digest(JD)}.json").read_text(encoding="utf-8"))
    assert imported["approval"] == original
    assert imported["approval"]["source"] == "unattended_run_policy"
    # A legacy portable revision remains readable without inventing review.
    envelope.pop("approval")
    path.write_text(json.dumps(envelope), encoding="utf-8")
    canonical.import_revision(path, JD)
    imported = json.loads((canonical.store_dir() / "approved" / f"{canonical.digest(JD)}.json").read_text(encoding="utf-8"))
    assert "approval" not in imported
    envelope["approval"] = []
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError):
        canonical.import_revision(path, JD)


def test_input_requirements_reports_actual_policy_approval(project, capsys):
    path = Path("proposal.json")
    path.write_text(json.dumps(requirement_proposal()), encoding="utf-8")
    assert requirements.run("draft", path=str(path), approval="unattended")
    assert "Policy-approved requirement revision" in capsys.readouterr().out
    assert canonical.approved_revision(JD) is not None
