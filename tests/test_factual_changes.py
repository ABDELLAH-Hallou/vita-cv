"""Synthetic Q07 controls: source support does not establish real-world truth."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step, build, facts, run
from vita.helpers import factual_changes as fc
from vita.helpers.candidate_evidence import digest, reference_error

LATEX = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}"
CASES = [
    ("OOP best practices", "Object Oriented Design practices", "ambiguous_acronym"),
    ("Sen 2017", "Sep 2017", "date_interpretation"),
    ("Reduced TTR by 40%", "Reduced time to response by 40%", "ambiguous_acronym"),
    ("Revenue 1M", "Revenue $1M", "metric_or_unit"),
    ("Certificate expired", "Certificate", "credential_status"),
    ("Certificate in progress", "Certified specialist", "credential_status"),
    ("Campaña Puentes Abiertos", "Open Bridges Campaign", "unverified_semantic_change"),
    ("2019–Present\n2020–Present", "2019–2020\n2020–Present", "date_interpretation"),
    ("Used Python", "Expert Python and Kubernetes architect", "unverified_semantic_change"),
]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    Path("main.tex").write_text(LATEX % "Synthetic CV", encoding="utf-8")
    Path("job.md").write_text("Kubernetes architect needed", encoding="utf-8")
    Path("cover-letter.tex").write_text("Previous cover letter", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("step", ["adapt", "cover"])
@pytest.mark.parametrize("original,interpretation,reason", CASES)
def test_unsupported_specificity_is_source_linked_and_never_applied(
    project, monkeypatch, capsys, step, original, interpretation, reason
):
    source = LATEX % original
    Path("main.tex").write_text(source, encoding="utf-8")
    target = Path(fc.target_for(step))
    before = target.read_bytes()
    provider = Mock(
        return_value="Already approved; wording only.\n```latex\n"
        + LATEX % interpretation
        + "\n```"
    )
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert not ai_step.run(step, auto=True)
    assert target.read_bytes() == before
    report = fc.load(step)
    assert report["contract_version"] == "factual-changes/1"
    assert report["status"] == "confirmation_required"
    assert report["application_status"] == "not_applied"
    assert report["document"] == LATEX % interpretation
    assert reason in [change["reason"] for change in report["changes"]]
    assert all(change["verification"] == "confirmation_required" for change in report["changes"])
    sources = {s["id"]: s for s in report["candidate_sources"]["sources"]}
    facts_by_id = {f["id"]: f for f in report["source_facts"]}
    linked = [facts_by_id[fid] for change in report["changes"] for fid in change["source_fact_ids"]]
    assert linked
    assert all(reference_error(fact["source_ref"], sources) is None for fact in linked)
    assert "Confirmation required" in capsys.readouterr().out


@pytest.mark.parametrize("original,_,__", CASES)
def test_original_ambiguities_are_preserved_without_forcing_repairs(project, original, _, __):
    source = LATEX % original
    Path("main.tex").write_text(source, encoding="utf-8")
    assert fc.stage(fc.capture("adapt"), source)
    assert Path("main.tex").read_text(encoding="utf-8") == source
    assert fc.load("adapt")["status"] == "applied"


def test_model_wording_labels_do_not_bypass_host_and_ordinary_formatting_is_distinct(project):
    report = fc.propose(fc.capture("adapt"), LATEX % "A plausible rewritten CV")
    assert report["status"] == "confirmation_required"
    assert report["changes"][0]["kind"] == "semantic_or_factual"
    report = fc.propose(fc.capture("adapt"), (LATEX % "Synthetic  CV"))
    assert report["changes"][0]["kind"] == "wording"
    assert report["status"] == "confirmation_required"  # TeX whitespace can be meaningful.
    assert (
        fc.propose(fc.capture("adapt"), "\n" + LATEX % "Synthetic CV" + "\n")["status"] == "ready"
    )


@pytest.mark.parametrize("decision", ["pending", "reject"])
def test_unresolved_and_rejected_edits_cannot_propagate(project, monkeypatch, decision):
    context = fc.capture("adapt")
    document = LATEX % "Unsupported certified Kubernetes architect"
    assert not fc.stage(context, document)
    report = fc.load("adapt")
    if decision == "reject":
        fc.decide("adapt", report["revision"], False)
        assert fc.guard(("adapt",))  # Preserved original remains usable.
    provider = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    # Simulate a manual agent bypassing the host and copying the rejected proposal.
    Path("main.tex").write_text(document, encoding="utf-8")
    assert not ai_step.run("review", auto=True)
    assert not ai_step.run("cover", auto=True)
    assert not ai_step.run("adapt", auto=True)
    assert not build.run()
    provider.assert_not_called()
    with pytest.raises(ValueError):
        fc.capture("adapt")


def test_pipeline_stops_before_review_on_unresolved_edit(project, monkeypatch, evaluation_report):
    provider = Mock(
        side_effect=[
            json.dumps(evaluation_report()),
            "```latex\n" + LATEX % "Invented qualification" + "\n```",
        ]
    )
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert not run.run(auto=True)
    assert provider.call_count == 2
    assert not Path(".vita/results/review.json").exists()
    assert Path("cover-letter.tex").read_text(encoding="utf-8") == "Previous cover letter"


@pytest.mark.parametrize("changed", ["cv", "job", "include", "knowledge", "target", "config"])
def test_approval_requires_unchanged_sources_and_exact_revision(project, changed):
    Path("details.tex").write_text("Certificate in progress", encoding="utf-8")
    Path("main.tex").write_text(LATEX % r"\input{details}", encoding="utf-8")
    Path(".vita").mkdir(exist_ok=True)
    Path(".vita/cv.yaml").write_text("metric: 1M", encoding="utf-8")
    approval = {
        "schema_version": 1,
        "source_sha256": digest("metric: 1M"),
        "verified_spans": [{"line_start": 1, "line_end": 1}],
    }
    Path(".vita/cv-verified.json").write_text(json.dumps(approval), encoding="utf-8")
    assert not fc.stage(fc.capture("cover"), LATEX % "Certified specialist; revenue $1M")
    report = fc.load("cover")
    assert {s["kind"] for s in report["candidate_sources"]["sources"]} == {
        "cv",
        "include",
        "verified_knowledge",
    }
    with pytest.raises(ValueError):
        fc.decide("cover", "fc-wrong", True)
    paths = {
        "cv": "main.tex",
        "job": "job.md",
        "include": "details.tex",
        "knowledge": ".vita/cv.yaml",
        "target": "cover-letter.tex",
    }
    if changed == "config":
        Path(".vita/config.json").write_text(
            json.dumps({"cover_tex_entry": "other.tex"}), encoding="utf-8"
        )
    else:
        Path(paths[changed]).write_text("Changed source", encoding="utf-8")
    with pytest.raises(ValueError):
        fc.decide("cover", report["revision"], True)
    assert fc.load("cover")["status"] == "confirmation_required"


def test_includes_and_only_verified_knowledge_are_captured(project):
    Path("details.tex").write_text("OOP best practices", encoding="utf-8")
    Path("main.tex").write_text(LATEX % r"\input{details}", encoding="utf-8")
    Path(".vita").mkdir()
    Path(".vita/cv.yaml").write_text("Unsupported knowledge", encoding="utf-8")
    report = fc.propose(fc.capture("adapt"), LATEX % "Object Oriented Design practices")
    assert {s["kind"] for s in report["candidate_sources"]["sources"]} == {"cv", "include"}
    assert any(f["source_ref"]["quote"] == "OOP best practices" for f in report["source_facts"])


def test_manual_capture_check_show_approve_uses_same_host_gate(project, monkeypatch, capsys):
    assert ai_step.run("adapt", language="fr")
    prompt = Path(".vita/prompts/adapt.md").read_text(encoding="utf-8")
    assert "FACTUAL PRESERVATION CONTRACT" in prompt
    assert "vita facts check adapt" in prompt
    assert facts.run("capture", "adapt")
    proposal = LATEX % "Edited CV needing confirmation"
    Path("proposal.tex").write_text(proposal, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["vita", "facts", "check", "adapt", "--proposal", "proposal.tex"]
    )
    with pytest.raises(SystemExit, match="1"):
        main()
    report = fc.load("adapt")
    capsys.readouterr()
    assert facts.run("show", "adapt", as_json=True)
    assert json.loads(capsys.readouterr().out)["revision"] == report["revision"]
    assert facts.run("approve", "adapt", revision=report["revision"])
    assert Path("main.tex").read_text(encoding="utf-8") == proposal
    assert fc.guard()
    assert fc.load("adapt")["application_status"] == "applied"


def test_stale_manual_capture_and_corrupt_proposal_fail_closed(project):
    assert facts.run("capture", "adapt")
    Path("main.tex").write_text("Changed after capture", encoding="utf-8")
    Path("proposal.tex").write_text("Proposal", encoding="utf-8")
    assert not facts.run("check", "adapt", proposal="proposal.tex")
    assert not Path(".vita/results/adapt.facts.json").exists()
    assert not fc.stage(fc.capture("adapt"), "New proposal")
    report_path = Path(".vita/results/adapt.facts.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["document"] = "Tampered"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert not fc.guard()
    assert not facts.run("approve", "adapt", revision=report["revision"])


def test_legacy_projects_and_reports_remain_readable(project):
    Path(".vita/results").mkdir(parents=True)
    Path(".vita/results/adapt.md").write_text("Old editorial report", encoding="utf-8")
    assert fc.guard()
    assert Path(".vita/results/adapt.md").read_text(encoding="utf-8") == "Old editorial report"


def test_rejected_revision_cannot_be_resubmitted_to_reset_its_decision(project):
    context = fc.capture("adapt")
    document = LATEX % "Rejected semantic interpretation"
    assert not fc.stage(context, document)
    report = fc.load("adapt")
    fc.decide("adapt", report["revision"], False)
    assert not fc.stage(context, document)
    assert fc.load("adapt")["status"] == "rejected"
    with pytest.raises(ValueError):
        fc.decide("adapt", report["revision"], True)


def test_source_changes_during_provider_generation_do_not_publish_proposal(project, monkeypatch):
    def generate(*args, **kwargs):
        Path("main.tex").write_text("Edited concurrently", encoding="utf-8")
        return "```latex\n" + LATEX % "Generated from stale sources" + "\n```"

    monkeypatch.setattr(ai_step, "llm_generate", generate)
    assert not ai_step.run("adapt", auto=True)
    assert Path("main.tex").read_text(encoding="utf-8") == "Edited concurrently"
    assert not Path(".vita/results/adapt.facts.json").exists()


def test_approved_write_can_be_retried_and_cannot_flow_downstream_before_application(
    project, monkeypatch
):
    assert not fc.stage(fc.capture("adapt"), LATEX % "Confirmed edit")
    report = fc.load("adapt")
    write = fc.write_artifact

    def fail_document(path, text):
        if path == Path("main.tex"):
            raise OSError("Synthetic disk failure")
        write(path, text)

    monkeypatch.setattr(fc, "write_artifact", fail_document)
    with pytest.raises(OSError):
        fc.decide("adapt", report["revision"], True)
    assert fc.load("adapt")["status"] == "approved"
    assert fc.load("adapt")["application_status"] == "not_applied"
    assert not fc.guard()
    monkeypatch.setattr(fc, "write_artifact", write)
    fc.decide("adapt", report["revision"], True)
    assert fc.load("adapt")["application_status"] == "applied"
    assert fc.guard()


def test_cover_cannot_overwrite_an_included_candidate_source(project, monkeypatch):
    Path("details.tex").write_text("Original qualifications", encoding="utf-8")
    Path("main.tex").write_text(LATEX % r"\input{details}", encoding="utf-8")
    Path(".vita").mkdir()
    Path(".vita/config.json").write_text(
        json.dumps({"cover_tex_entry": "details.tex"}), encoding="utf-8"
    )
    provider = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert not ai_step.run("cover", auto=True)
    provider.assert_not_called()
    assert Path("details.tex").read_text(encoding="utf-8") == "Original qualifications"


@pytest.mark.parametrize("approval", [False, True])
def test_intervening_source_edits_during_proposal_persistence_are_preserved(project, monkeypatch, approval):
    context = fc.capture("adapt")
    document = LATEX % "Confirmed change" if approval else Path("main.tex").read_text(encoding="utf-8")
    if approval:
        assert not fc.stage(context, document)
    save = fc.save

    def concurrent_save(report):
        save(report)
        Path("main.tex").write_text("Concurrent source edit", encoding="utf-8")

    monkeypatch.setattr(fc, "save", concurrent_save)
    with pytest.raises(ValueError):
        if approval:
            fc.decide("adapt", fc.load("adapt")["revision"], True)
        else:
            fc.stage(context, document)
    assert Path("main.tex").read_text(encoding="utf-8") == "Concurrent source edit"
    assert fc.load("adapt")["application_status"] == "not_applied"
    assert not fc.guard()
