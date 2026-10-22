"""Issue #38: candidate-independent, approved JD taxonomies and revision reuse."""

import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.commands import ai_step
from vita.commands import requirements as command
from vita.commands import run as pipeline
from vita.helpers import evaluation, job_extraction, requirements
from vita.helpers.job_extraction import prepare_job
from vita.helpers.pipeline_config import STAGE_PREFIXES, load_pipeline_settings
from vita.helpers.structured import (
    CANONICAL_CRITERION_FIELDS,
    EVALUATION_OUTPUT_SCHEMA,
    EVALUATION_SCHEMA,
    json_text,
    parse_json,
    validate,
)

JD = """# Marketing Operations Engineer
## Required
- HubSpot experience is required.
- Salesforce experience is required.
## Preferred
- 6sense is a significant plus.
## Must-Have or Strong Plus
- Experience with AI workflows.
## Employment conditions
- If working remotely, reliable internet is required.
- If working remotely, your own computer is required.
## Responsibilities
- Use HubSpot for lifecycle campaigns.
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VITA_REQUIREMENTS_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    for prefix in STAGE_PREFIXES.values():
        for suffix in ("MODEL", "PROVIDER"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    Path("job.md").write_text(JD, encoding="utf-8")
    Path("main.tex").write_text("Candidate A: HubSpot engineer.", encoding="utf-8")
    Path(".vita").mkdir()
    return tmp_path


def item(key, text, line, category="hard_skills", classification="required", kind="capability"):
    return {"job_id": "job-1", "key": key, "text": text, "kind": kind, "category": category,
            "classification": classification, "ambiguity": "",
            "source_refs": [{"job_id": "job-1", "line_start": line, "line_end": line,
                             "quote": JD.splitlines()[line - 1]}]}


def proposal():
    return {"schema_version": 1, "items": [
        item("hubspot", "HubSpot experience", 3), item("salesforce", "Salesforce experience", 4),
        # Deliberately incorrect proposed importance/kind: source wording wins.
        item("6sense", "6sense familiarity", 6), item("ai", "Experience with AI workflows", 8),
        item("internet", "Reliable internet if working remotely", 10),
        item("computer", "Own computer if working remotely", 11),
        item("keyword:hubspot", "Use HubSpot for lifecycle campaigns", 13, category="responsibilities"),
    ]}


def approve():
    data = requirements.save_revision(requirements.compile_revision(proposal(), JD))
    return requirements.approve_revision(data["revision"], JD)


def report_for(data, make_report, status="matched"):
    report = make_report(status)
    report["metrics"]["criteria"] = [
        {**{key: unit[key] for key in evaluation.TAXONOMY_FIELDS}, "status": status,
         "evidence": "Synthetic CV evidence" if status != "missing" else "", "feedback": "Clarify evidence."}
        for unit in data["requirements"]
    ]
    return report


def test_source_classification_deduplication_and_unscored_conditions(project):
    data = approve()
    units = {unit["key"]: unit for unit in data["requirements"]}
    assert set(units) == {"hubspot", "salesforce", "6sense", "ai"}
    assert units["hubspot"]["weight"] == units["salesforce"]["weight"] == 2
    assert len(units["hubspot"]["source_refs"]) == 2
    assert units["6sense"]["classification"] == "preferred" and units["6sense"]["weight"] == 1
    assert units["ai"]["classification"] == "unclear" and units["ai"]["weight"] == 0
    assert units["ai"]["ambiguity"]
    assert len(data["employment_conditions"]) == 2
    assert all(unit["weight"] == 0 for unit in data["employment_conditions"])
    assert sum(unit["weight"] for unit in data["requirements"]) == 5
    requirements.validate_revision(data)


def test_two_cvs_and_both_stages_use_identical_taxonomy_and_denominators(project, monkeypatch, evaluation_report):
    data = approve()
    extractor = Mock(side_effect=AssertionError("Approved requirements must not be extracted again"))
    monkeypatch.setattr(job_extraction, "generate", extractor)
    records = []
    for cv, status in (("Candidate A: HubSpot engineer.", "matched"), ("Candidate B: Salesforce analyst.", "missing")):
        Path("main.tex").write_text(cv, encoding="utf-8")
        provider = Mock(return_value=json_text(report_for(data, evaluation_report, status)))
        monkeypatch.setattr(ai_step, "llm_generate", provider)
        for stage in ("analyze", "review"):
            assert ai_step.run(stage, auto=True)
            assert "LOCKED CANONICAL JD CRITERIA" in provider.call_args.args[1]
            assert cv in provider.call_args.args[0]
            record = parse_json(Path(f".vita/results/{'analysis' if stage == 'analyze' else stage}.json").read_text(encoding="utf-8"))
            records.append(record)
            assert record["metadata"]["requirements_revision"] == data["revision"]
            assert record["metrics"]["weighted_available"] == 5
            assert record["metrics"]["category_denominators"]["hard_skills"] == 5
            assert len(record["metrics"]["criteria"]) == 4
            assert len(record["metrics"]["employment_conditions"]) == 2
            validate(record, EVALUATION_SCHEMA)
    extractor.assert_not_called()
    assert all(evaluation.taxonomy(record) == evaluation.taxonomy(records[0]) for record in records)
    assert all(record["metadata"]["criteria_sha256"] == records[0]["metadata"]["criteria_sha256"] for record in records)
    assert [record["overall_score"] for record in records] == [100, 100, 0, 0]
    assert records[0]["metrics"]["weighted_earned"] == 5
    assert records[-1]["metrics"]["weighted_earned"] == 0
    markdown = Path(".vita/results/review.md").read_text(encoding="utf-8")
    assert "Weighted denominator: 5" in markdown
    assert "Employment conditions (not scored)" in markdown
    assert "unclear" in markdown


@pytest.mark.parametrize("field,value", [("id", "different-id"), ("criterion", "Easier criterion"),
                                         ("category", "keywords"), ("importance", "nice_to_have")])
def test_candidate_cannot_change_approved_taxonomy(project, evaluation_report, field, value):
    data = approve()
    job = prepare_job(load_pipeline_settings(), auto=True)
    report = report_for(data, evaluation_report)
    required = next(unit for unit in report["metrics"]["criteria"] if unit["importance"] == "must_have")
    required[field] = value
    with pytest.raises(ValueError, match="approved canonical"):
        evaluation.finalize(json_text(report), job)


def test_changed_jd_creates_pending_revision_and_invalidates_assessments(project, evaluation_report):
    data = approve()
    old_job = prepare_job(load_pipeline_settings(), auto=False)
    report = evaluation.finalize(json_text(report_for(data, evaluation_report)), old_job)
    evaluation.save_evaluation("analyze", report)
    original = Path(".vita/results/analysis.json").read_bytes()
    Path("job.md").write_text(JD + "- Python experience is required.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="need approval"):
        prepare_job(load_pipeline_settings(), auto=True)
    state = parse_json(requirements.STATE.read_text(encoding="utf-8"))
    pending = requirements.read_revision(state["revision"])
    assert pending["revision"] != data["revision"] and pending["state"] == "pending"
    assert pending["source_sha256"] != data["source_sha256"]
    assert evaluation.load_baseline(old_job) is None
    assert Path(".vita/results/analysis.json").read_bytes() == original
    with pytest.raises(ValueError, match="before approval"):
        requirements.approve_revision(pending["revision"], pending["source_text"])
    with pytest.raises(ValueError, match="different job"):
        requirements.approve_revision(data["revision"], pending["source_text"])


def test_new_approved_revision_for_same_jd_invalidates_previous_baseline(project, evaluation_report):
    old = approve()
    job = prepare_job(load_pipeline_settings(), auto=False)
    evaluation.save_evaluation("analyze", evaluation.finalize(json_text(report_for(old, evaluation_report)), job))
    revised = proposal()
    revised["items"][1]["text"] = "Salesforce CRM experience"
    new = requirements.save_revision(requirements.compile_revision(revised, JD))
    requirements.approve_revision(new["revision"], JD)
    current = prepare_job(load_pipeline_settings(), auto=False)
    assert new["revision"] != old["revision"]
    assert {unit["id"] for unit in new["requirements"]} == {unit["id"] for unit in old["requirements"]}
    assert current.requirements["revision"] == new["revision"]
    assert evaluation.load_baseline(current) is None
    assert evaluation.load_baseline(job) is None
    with pytest.raises(ValueError, match="revision changed"):
        evaluation.finalize(json_text(report_for(old, evaluation_report)), job)


def test_export_import_reuses_exact_approval_and_context_across_projects(project, monkeypatch):
    data = approve()
    before = prepare_job(load_pipeline_settings(), auto=False)
    exported = project / "approved.json"
    requirements.export_revision(exported, JD)
    second = project / "second"
    second.mkdir()
    monkeypatch.chdir(second)
    monkeypatch.setenv("VITA_REQUIREMENTS_DIR", str(second / "separate-store"))
    Path("job.md").write_text(JD, encoding="utf-8")
    requirements.import_revision(exported, JD)
    after = prepare_job(load_pipeline_settings(), auto=False)
    assert after.requirements == data
    assert after.context_sha256 == before.context_sha256
    assert not Path("main.tex").exists()  # Import/approval do not depend on a CV.


def test_git_worktrees_share_approval_across_branches(project, monkeypatch, evaluation_report):
    monkeypatch.delenv("VITA_REQUIREMENTS_DIR")
    def git(*args):
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    git("init", "--initial-branch=master")
    git("config", "user.email", "synthetic@example.invalid")
    git("config", "user.name", "Synthetic Test")
    Path(".gitignore").write_text(".vita/\n", encoding="utf-8")
    git("add", "job.md", "main.tex", ".gitignore")
    git("commit", "-m", "Synthetic job and CV")
    data = approve()
    first_store = requirements.store_dir().resolve()
    first = prepare_job(load_pipeline_settings(), auto=False)
    other = project.parent / (project.name + "-worktree")
    git("worktree", "add", "-b", "candidate-b", str(other))
    try:
        monkeypatch.chdir(other)
        Path("main.tex").write_text("Candidate B: Salesforce.", encoding="utf-8")
        second = prepare_job(load_pipeline_settings(), auto=False)
        assert requirements.store_dir().resolve() == first_store
        assert second.requirements == data
        assert first.context_sha256 == second.context_sha256
        a = evaluation.finalize(json_text(report_for(data, evaluation_report)), first)
        b = evaluation.finalize(json_text(report_for(data, evaluation_report, "missing")), second)
        assert evaluation.taxonomy(a) == evaluation.taxonomy(b)
        assert a["metrics"]["weighted_available"] == b["metrics"]["weighted_available"] == 5
    finally:
        monkeypatch.chdir(project)
        assert other.resolve().parent == project.parent.resolve() and (other / ".git").is_file()
        git("worktree", "remove", "--force", str(other))


@pytest.mark.parametrize("damage", ["quote", "line", "job"])
def test_proposals_require_true_source_references(project, damage):
    source = proposal()
    ref = source["items"][0]["source_refs"][0]
    if damage == "quote":
        ref["quote"] = "Invented requirement"
    elif damage == "line":
        ref["line_end"] = 999
    else:
        ref["job_id"] = "job-2"
    with pytest.raises(ValueError, match="source"):
        requirements.compile_revision(source, JD)


def test_immutable_revision_rejects_tampering(project):
    data = approve()
    path = requirements.store_dir() / "revisions" / f"{data['revision']}.json"
    edited = copy.deepcopy(data)
    edited["requirements"][0]["weight"] = 99
    path.write_text(json_text(edited), encoding="utf-8")
    with pytest.raises(ValueError):
        requirements.active_requirements(JD)


def test_reordering_proposal_does_not_change_ids_or_revision(project):
    first = requirements.compile_revision(proposal(), JD)
    reversed_proposal = proposal()
    reversed_proposal["items"].reverse()
    for unit in reversed_proposal["items"]:
        unit["source_refs"] = [dict(reversed(list(ref.items()))) for ref in unit["source_refs"]]
    second = requirements.compile_revision(reversed_proposal, JD)
    assert first == second


def test_unapproved_draft_blocks_assessment_before_provider(project, monkeypatch):
    requirements.save_revision(requirements.compile_revision(proposal(), JD))
    provider = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("analyze", auto=True) is False
    provider.assert_not_called()


def test_draft_generation_sends_only_jd_and_requires_separate_approval(project, monkeypatch):
    Path(".vita/cv.yaml").write_text("PRIVATE_CANDIDATE_KNOWLEDGE", encoding="utf-8")
    provider = Mock(return_value=json_text(proposal()))
    monkeypatch.setattr(command, "generate", provider)
    assert command.run("draft", auto=True)
    system, prompt = provider.call_args.args
    assert "Candidate A" not in system + prompt and "PRIVATE_CANDIDATE" not in system + prompt
    assert "HubSpot" in prompt and "1: # Marketing" in prompt
    assert requirements.approved_revision(JD) is None
    assert requirements.STATE.exists()


def test_manual_draft_does_not_call_ai_and_cli_approval_round_trip(project, monkeypatch):
    provider = Mock()
    monkeypatch.setattr(command, "generate", provider)
    monkeypatch.setattr(sys, "argv", ["vita", "requirements", "draft"])
    main()
    provider.assert_not_called()
    assert "Never approve it automatically" in Path(".vita/prompts/requirements.md").read_text(encoding="utf-8")
    Path("proposal.json").write_text(json_text(proposal()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["vita", "requirements", "draft", "--input", "proposal.json"])
    main()
    state = parse_json(requirements.STATE.read_text(encoding="utf-8"))
    monkeypatch.setattr(sys, "argv", ["vita", "requirements", "approve", state["revision"]])
    main()
    assert requirements.approved_revision(JD)["revision"] == state["revision"]


def test_legacy_job_cache_and_evaluation_still_work_without_opt_in(project, evaluation_report):
    job = prepare_job(load_pipeline_settings(), auto=False)
    assert job.requirements is None
    report = evaluation.finalize(json_text(evaluation_report()), job)
    assert "requirements_revision" not in report["metadata"]
    assert report["overall_score"] == 100 and report["metrics"]["weighted_available"] == 2


def test_provider_schema_excludes_host_owned_canonical_fields():
    metrics = EVALUATION_OUTPUT_SCHEMA["properties"]["metrics"]["properties"]
    assert "weighted_available" not in metrics and "employment_conditions" not in metrics
    assert not set(CANONICAL_CRITERION_FIELDS) & metrics["criteria"]["items"]["properties"].keys()


def test_repeated_labels_with_different_keys_are_not_double_weighted(project):
    data = proposal()
    repeated = copy.deepcopy(data["items"][0])
    repeated["key"] = "crm-hubspot"
    repeated["category"] = "responsibilities"
    data["items"].append(repeated)
    revision = requirements.compile_revision(data, JD)
    assert len(revision["requirements"]) == 4
    assert sum(item["weight"] for item in revision["requirements"]) == 5


def test_ambiguous_only_revision_is_preserved_without_a_zero_percent_penalty(project, evaluation_report):
    data = proposal()
    data["items"] = [data["items"][3]]
    revision = requirements.save_revision(requirements.compile_revision(data, JD))
    requirements.approve_revision(revision["revision"], JD)
    job = prepare_job(load_pipeline_settings(), auto=False)
    report = evaluation.finalize(json_text(report_for(revision, evaluation_report, "missing")), job)
    assert report["metrics"]["weighted_available"] == 0
    assert "not scored" in report["executive_summary"]
    assert "0.00%" not in report["executive_summary"]
    assert "| Hard Skills | N/A |" in evaluation.render_report(report, "Assessment")


def test_multiple_job_source_ownership_and_ids_are_preserved(project):
    raw = "# Job 1\nPython experience is required.\n# Job 2\nSQL experience is preferred.\n"
    proposal_data = {"schema_version": 1, "items": []}
    for job_id, key, line in (("job-1", "python", 2), ("job-2", "sql", 4)):
        unit = item(key, key, 3)
        unit.update(job_id=job_id)
        unit["source_refs"] = [{"job_id": job_id, "line_start": line, "line_end": line, "quote": raw.splitlines()[line - 1]}]
        proposal_data["items"].append(unit)
    revision = requirements.compile_revision(proposal_data, raw)
    assert {item["job_id"] for item in revision["requirements"]} == {"job-1", "job-2"}
    assert sum(item["weight"] for item in revision["requirements"]) == 3
    proposal_data["items"][0]["source_refs"][0].update(line_start=4, line_end=4, quote=raw.splitlines()[3])
    with pytest.raises(ValueError, match="another job"):
        requirements.compile_revision(proposal_data, raw)


def test_manual_analysis_embeds_approved_revision_even_when_extraction_is_enabled(project, monkeypatch):
    data = approve()
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "true")
    assert ai_step.run("analyze")
    prompt = Path(".vita/prompts/analyze.md").read_text(encoding="utf-8")
    assert data["revision"] in prompt and "LOCKED CANONICAL JD CRITERIA" in prompt
    assert "At execution time, read .vita/results/job.json" not in prompt


def test_malformed_approval_record_stops_safely(project, monkeypatch):
    data = approve()
    path = requirements.store_dir() / "approved" / f"{data['source_sha256']}.json"
    path.write_text('{"schema_version":1}', encoding="utf-8")
    provider = Mock()
    monkeypatch.setattr(ai_step, "llm_generate", provider)
    assert ai_step.run("analyze", auto=True) is False
    provider.assert_not_called()


def test_new_draft_remains_visible_without_replacing_existing_approval(project, capsys):
    old = approve()
    revised = proposal()
    revised["items"][1]["text"] = "Salesforce CRM experience"
    draft = requirements.save_revision(requirements.compile_revision(revised, JD))
    assert requirements.active_requirements(JD)["revision"] == old["revision"]
    assert command.run("show")
    shown = json.loads(capsys.readouterr().out)
    assert shown["approval_status"] == "draft"
    assert shown["revision"]["revision"] == draft["revision"]


def test_pipeline_reuses_approval_without_reextracting_job(project, monkeypatch):
    approve()
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "true")
    steps = []
    monkeypatch.setattr(pipeline, "ai_step_run", lambda step, **kwargs: steps.append(step) or True)
    assert pipeline.run(auto=True)
    assert steps == ["analyze", "adapt", "review", "cover"]


def test_alternative_requirement_is_one_criterion(project):
    raw = "Experience with HubSpot or Salesforce is required.\n"
    data = {"schema_version": 1, "items": [item("crm", raw.strip(), 3)]}
    data["items"][0]["source_refs"] = [{"job_id": "job-1", "line_start": 1, "line_end": 1, "quote": raw.strip()}]
    revision = requirements.compile_revision(data, raw)
    assert len(revision["requirements"]) == 1
    assert "or Salesforce" in revision["requirements"][0]["criterion"]
    assert revision["requirements"][0]["weight"] == 2


def test_baseline_cannot_reweight_an_approved_requirement_even_with_updated_fingerprint(project, evaluation_report):
    data = approve()
    job = prepare_job(load_pipeline_settings(), auto=False)
    report = evaluation.finalize(json_text(report_for(data, evaluation_report)), job)
    unit = next(item for item in report["metrics"]["criteria"] if item["importance"] == "must_have")
    unit.update(classification="preferred", importance="nice_to_have", weight=1)
    report["metadata"]["criteria_sha256"] = requirements.digest(json_text(evaluation.taxonomy(report)))
    Path(".vita/results").mkdir(parents=True, exist_ok=True)
    Path(".vita/results/analysis.json").write_text(json_text(report), encoding="utf-8")
    assert evaluation.load_baseline(job) is None


def test_changed_job_can_resume_only_after_approving_its_new_revision(project, evaluation_report):
    old = approve()
    previous = prepare_job(load_pipeline_settings(), auto=False)
    evaluation.save_evaluation("analyze", evaluation.finalize(json_text(report_for(old, evaluation_report)), previous))
    raw = JD + "- Python experience is required.\n"
    Path("job.md").write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="need approval"):
        prepare_job(load_pipeline_settings(), auto=False)
    data = proposal()
    python = copy.deepcopy(data["items"][0])
    python.update(key="python", text="Python experience")
    python["source_refs"] = [{"job_id": "job-1", "line_start": 14, "line_end": 14,
                              "quote": raw.splitlines()[13]}]
    data["items"].append(python)
    new = requirements.save_revision(requirements.compile_revision(data, raw))
    requirements.approve_revision(new["revision"], raw)
    current = prepare_job(load_pipeline_settings(), auto=False)
    assert evaluation.load_baseline(current) is None
    report = evaluation.finalize(json_text(report_for(new, evaluation_report)), current)
    assert report["metadata"]["requirements_revision"] == new["revision"] != old["revision"]
    assert report["metrics"]["weighted_available"] == 7
    assert {unit["id"] for unit in old["requirements"]} < {unit["id"] for unit in new["requirements"]}
