"""Synthetic software tests only: these are not human annotations or study results."""

import copy
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.evaluation import contracts as c
from scripts.evaluation import study
from scripts.evaluation.__main__ import adjudication_template, main
from scripts.evaluation.scoring import agreement, markdown, proportion, score


def replace(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def now():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "private-study"
    study.initialize(path)
    return path


def configure(root):
    protocol = c.read(root / "protocol.json")
    protocol["status"] = "approved_by_custodian"
    replace(root / "protocol.json", protocol)
    config = {"id": "synthetic-config", "provider": "fixture", "model": "synthetic-test-only",
              "product_revision": "a" * 40, "prompt_revision": "b" * 64, "schema_revision": "c" * 64,
              "extraction_enabled": True, "reasoning_effort": "low", "temperature": None, "as_of_date": "2026-10-24"}
    replace(root / "configurations.json", {"schema_version": 1, "configurations": [config]})
    replace(root / "governance.json", {"custodian_id": "synthetic-test-custodian", "protocol_approved_at": now(),
        "registration_reference": "SYNTHETIC UNIT TEST: no actual human approval", "sampling_plan_approved": True,
        "predeclared_analysis_approved": True, "holdout_tuning_forbidden": True})
    return config


def people(root, cases):
    # Deliberately simulated attestations in temporary test data, never real qualifications.
    roster = [{"id": f"test-human-{i}", "person_key": f"simulated-person-{i}", "kind": "human",
               "identity_verified_by_custodian": True, "independent": True, "conflict_of_interest": False,
               "calibration_completed": True, "qualification_reference": "SYNTHETIC TEST ATTESTATION ONLY",
               "relevant_years": 4, "specialist_qualification_approved": False,
               "domains": ["software", "sales"], "languages": ["en"], "native_formats": ["latex"]} for i in range(3)]
    replace(root / "reviewers.json", {"schema_version": 1, "reviewers": roster})
    replace(root / "assignments.json", {"schema_version": 1, "assignments": [
        {"case_id": case["id"], "reviewer_ids": ["test-human-0", "test-human-1"], "adjudicator_id": "test-human-2"} for case in cases]})


def outputs(root, reg, *, all_cases=False, failure=None):
    rows, units = [], []
    cases = {case["id"]: case for case in reg["cases"]}
    config = reg["configurations"][0]
    for obs in reg["observations"]:
        case = cases[obs["case_id"]]
        if not all_cases and case["control"] != "primary":
            continue
        task = obs["task"]
        path = root / "outputs" / (obs["id"] + ".json")
        path.parent.mkdir(exist_ok=True)
        report = {"claim": "Python engineer", "overall_score": 50,
            "criteria": [{"classification": "required", "status": "partial"}],
            "metadata": {"assessment": {**{key: c.fingerprint(key) for key in (
                "source_sha256", "job_sha256", "criteria_sha256", "prompt_sha256", "system_sha256", "schema_sha256", "host_sha256", "config_sha256", "judge_sha256")},
                **{key: config[key] for key in ("provider", "model", "reasoning_effort", "as_of_date")}},
                "assessment_execution": {"mode": "reassessment"}}}
        replace(path, report)
        row = {**obs, "status": "unavailable" if failure == task else "completed", "started_at": now(), "finished_at": now(),
               "attempts": 3 if failure == task else 1, "usage": None, "exit_status": 1 if failure == task else 0,
               "failure_category": "overloaded" if failure == task else None,
               "input_assets": {a["id"]: a["sha256"] for a in case["assets"]}, "provenance": {k: v for k, v in config.items() if k != "id"},
               "artifact": None if failure == task else {"path": path.relative_to(root).as_posix(), "sha256": c.file_hash(path)}}
        rows.append(row)
        if row["status"] != "completed" or case["control"] != "primary":
            continue
        for dimension in reg["protocol"]["required_dimensions"][task]:
            req = dimension.startswith("requirement_")
            refs = [{"document": "asset:job", "line_start": 7, "line_end": 7, "quote": "Python production experience is required."}] if req else []
            if dimension != "requirement_classification":
                refs.append({"document": "asset:job", "line_start": 6, "line_end": 6, "quote": "Python Engineer position"} if task == "extract" else {"document": "asset:cv", "line_start": 4, "line_end": 4, "quote": "Python engineer"})
            units.append({"id": task + "-" + dimension, "observation_id": obs["id"], "dimension": dimension,
                "concept_id": "python", "question": "Evaluate the documented Python criterion/claim.", "source_refs": refs,
                "output_ref": {"document": "output", "line_start": 2, "line_end": 2, "quote": "Python engineer"},
                "prediction_pointer": "/criteria/0/" + ("classification" if dimension == "requirement_classification" else "status") if req else None,
                "prediction_mode": "value" if req else None})
    replace(root / "results.json", {"schema_version": 1, "observations": rows})
    replace(root / "units.json", {"schema_version": 1, "units": units})
    return rows, units


def reviewed(root, path, rid):
    dest = root / (rid + ".json")
    form = study.review_template(root, path, rid, dest)
    form.update(independent=True, job_pass_completed_at=now(), source_pass_completed_at=now(), outputs_opened_at=now())
    for row in form["inventory"]:
        row.update(status="complete", rationale="SYNTHETIC TEST inventory check")
    default = {"fidelity": "supported", "requirement_classification": "required", "requirement_satisfaction": "partial", "omission": "retained", "addition": "supported"}
    units = {u["id"]: u for u in c.read(path)["units"]}
    for row in form["annotations"]:
        unit = units[row["unit_id"]]
        job_only = row["unit_id"].startswith("extract-") or unit["dimension"] == "requirement_classification"
        row.update(label=default[unit["dimension"]], rationale="SYNTHETIC TEST label, not a real human finding",
                   evidence_kind="direct", refs=[{"document": "asset:job", "line_start": 7, "line_end": 7, "quote": "Python production experience is required."} if job_only else {"document": "asset:cv", "line_start": 4, "line_end": 4, "quote": "Python engineer"}],
                   checked_sources=["job"] if row["unit_id"].startswith("extract-") else ["cv", "education", "job"])
    replace(dest, form)
    return dest


@pytest.fixture
def prepared(root):
    configure(root)
    reg = study.freeze(root)
    outputs(root, reg)
    people(root, reg["cases"])
    path = root / "packet.json"
    study.packet(root, path)
    return root, reg, path


def test_scaffold_has_empty_holdout_and_no_invented_human_work(root):
    report = study.status(root)
    assert c.read(root / "holdout/manifest.json")["cases"] == []
    assert c.read(root / "reviewers.json")["reviewers"] == []
    assert c.read(root / "units.json")["units"] == []
    assert report["agreement"] == {"status": "unmeasured", "value": None}
    assert report["sampling"]["status"] == "sampling_pending"
    assert not any(report["claims"].values())
    assert len(report["sampling"]["cells"]) == 96
    with pytest.raises(ValueError, match="configurations"):
        study.freeze(root)


def test_preregistration_requires_real_custodian_fields(root):
    configure(root)
    governance = c.read(root / "governance.json")
    governance["sampling_plan_approved"] = False
    replace(root / "governance.json", governance)
    with pytest.raises(ValueError, match="approval"):
        study.freeze(root)


@pytest.mark.parametrize("change", ["group", "hash"])
def test_cross_split_leakage_rejected(root, change):
    manifest = c.read(root / "development/manifest.json")
    case = copy.deepcopy(manifest["cases"][0])
    case.update(id="held-out", split="holdout")
    if change == "hash":
        case.update(candidate_group="different-candidate", job_group="different-job", family_id="different-family")
    for asset in case["assets"]:
        source = root / "development" / asset["path"]
        target = root / "holdout" / asset["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    replace(root / "holdout/manifest.json", {"schema_version": 1, "cases": [case]})
    with pytest.raises(ValueError, match="leak"):
        study.status(root)


@pytest.mark.parametrize("change", ["rights", "redaction", "path", "hash", "unchanged", "role"])
def test_invalid_or_stale_corpus_is_rejected(root, change):
    doc = c.read(root / "development/manifest.json")
    if change == "rights":
        doc["cases"][0]["rights_approved"] = False
    elif change == "redaction":
        doc["cases"][0]["contact_redaction_verified"] = False
    elif change == "path":
        doc["cases"][0]["assets"][0]["path"] = "../../outside.tex"
    elif change == "hash":
        doc["cases"][0]["assets"][0]["sha256"] = "0" * 64
    elif change == "unchanged":
        doc["cases"][1]["domain"] = "marketing"
    else:
        doc["cases"][-1]["domain"] = "software"
    replace(root / "development/manifest.json", doc)
    with pytest.raises(ValueError):
        study.status(root)


@pytest.mark.parametrize("changed_file", ["development/sources/education.tex", "annotation-guide.md"])
def test_registration_is_immutable_and_source_changes_invalidate_it(root, changed_file):
    configure(root)
    reg = study.freeze(root)
    with pytest.raises(ValueError, match="overwrite"):
        study.freeze(root)
    assert study.registered(root)["sha256"] == reg["sha256"]
    path = root / changed_file
    path.write_text("Changed education", encoding="utf-8")
    with pytest.raises(ValueError, match="Stale"):
        study.registered(root)


def test_no_reviews_remain_pending_and_strict_gate_fails(prepared, capsys):
    root, _, path = prepared
    report = score(root, path)
    assert report["agreement"] == {"status": "pending_independent_reviews", "rows": []}
    assert all(x["has_semantic_error"] is None for x in report["observations"])
    assert all(x["case_semantic_error_rate"]["value"] is None for x in report["strata"])
    assert main(["score", "--study", str(root), "--packet", str(path), "--output", str(root / "report"), "--require-complete"]) == 1
    assert "unvalidated" in (root / "report/report.md").read_text(encoding="utf-8")
    assert "pending_independent_reviews" in capsys.readouterr().out


def test_blank_review_templates_do_not_count_as_labels(prepared):
    root, _, packet = prepared
    path = root / "blank.json"
    form = study.review_template(root, packet, "test-human-0", path)
    assert all(row["label"] is None for row in form["annotations"])
    report = score(root, packet, [path])
    assert report["status"] == "human_review_pending"
    assert report["agreement"]["rows"] == []
    source = c.read(path.with_suffix(".source-pass.json"))
    assert all("prediction_pointer" not in u and "output_ref" not in u for u in source["units"])
    assert all(d["document"] != "output" for d in source["documents"])
    assert "synthetic-test-only" not in json.dumps(source)


@pytest.mark.parametrize("change", ["same_person", "unqualified", "not_human", "conflict", "adjudicator", "independence"])
def test_human_panel_contract_rejects_invalid_attestations(root, change):
    configure(root)
    reg = study.freeze(root)
    people(root, reg["cases"])
    roster = c.read(root / "reviewers.json")
    assign = c.read(root / "assignments.json")
    if change == "same_person":
        roster["reviewers"][1]["person_key"] = roster["reviewers"][0]["person_key"]
    elif change == "unqualified":
        roster["reviewers"][0]["domains"] = ["marketing"]
    elif change == "not_human":
        roster["reviewers"][0]["kind"] = "assistant"
    elif change == "conflict":
        roster["reviewers"][0]["conflict_of_interest"] = True
    elif change == "independence":
        roster["reviewers"][0]["independent"] = False
    else:
        assign["assignments"][0]["adjudicator_id"] = "test-human-0"
    with pytest.raises(ValueError):
        study.assignments_check(roster, assign, reg["cases"], reg["protocol"])


def test_two_independent_reviews_then_adjudication_preserve_original_agreement(prepared):
    root, _, packet = prepared
    a = reviewed(root, packet, "test-human-0")
    b = reviewed(root, packet, "test-human-1")
    form = c.read(b)
    unit = next(x for x in form["annotations"] if x["unit_id"] == "adapt-fidelity")
    unit["label"] = "unsupported_specificity"
    replace(b, form)
    before = score(root, packet, [a, b])
    assert before["pending"]["adjudication_units"] == ["adapt-fidelity"]
    assert next(o for o in before["observations"] if o["observation_id"] == next(u for u in c.read(packet)["units"] if u["id"] == "adapt-fidelity")["observation_id"])["quality_status"] == "unmeasured"
    target = root / "adjudication.json"
    decision = adjudication_template(root, packet, [a, b], "test-human-2", target)
    assert decision["decisions"][0]["label"] is None
    assert score(root, packet, [a, b], [target])["pending"]["adjudication_units"] == ["adapt-fidelity"]
    decision["decisions"][0] = {**next(x for x in c.read(a)["annotations"] if x["unit_id"] == "adapt-fidelity"), "label": "unsupported_specificity"}
    decision.update(completed_at=now(), reviewed_original_submissions=True)
    replace(target, decision)
    after = score(root, packet, [a, b], [target])
    assert after["agreement"] == before["agreement"]
    assert after["pending"]["adjudication_units"] == []
    assert any(o["has_semantic_error"] is True for o in after["observations"])
    assert not after["claims"]["ats_validated"] and not after["claims"]["hiring_outcomes_validated"]


@pytest.mark.parametrize("change", ["quote", "span", "matched_inference", "matched_job_only", "unchecked_sources", "source_first"])
def test_unsupported_review_evidence_and_order_rejected(prepared, change):
    root, _, packet = prepared
    path = reviewed(root, packet, "test-human-0")
    form = c.read(path)
    row = next(a for a in form["annotations"] if a["unit_id"] == "analyze-requirement_satisfaction")
    if change == "quote":
        row["refs"][0]["quote"] = "Fictional employer that never appears"
    elif change == "span":
        row["refs"][0]["line_end"] = 999
    elif change == "matched_inference":
        row.update(label="matched", evidence_kind="inference")
    elif change == "matched_job_only":
        row.update(label="matched", refs=[{"document": "asset:job", "line_start": 7, "line_end": 7, "quote": "Python production experience is required."}])
    elif change == "unchecked_sources":
        row["checked_sources"] = ["cv"]
    else:
        form["source_pass_completed_at"] = "2100-01-01T00:00:00Z"
    replace(path, form)
    with pytest.raises(ValueError):
        score(root, packet, [path])


def test_unavailable_and_not_run_denominators_and_quality_null(root):
    configure(root)
    reg = study.freeze(root)
    outputs(root, reg, failure="cover")
    packet = root / "packet.json"
    study.packet(root, packet)
    report = score(root, packet)
    target = next(s for s in report["strata"] if s["task"] == "cover" and s["axis"] == "all" and s["control"] == "primary")
    assert target["execution_failure_rate"]["value"] == 1
    assert target["case_semantic_error_rate"]["value"] is None
    unrun = next(s for s in report["strata"] if s["control"] == "unchanged_analyze" and s["axis"] == "all")
    assert unrun["planned"] == unrun["not_run"] == 1
    assert unrun["noncompletion_rate"]["value"] == 1
    assert unrun["execution_failure_rate"]["value"] is None


def test_statistics_known_values_and_degenerate_cases():
    stat = agreement([2, 0, 2, 2, 0, 1], [0, 0, 2, 2, 0, 2])
    assert stat["kappa"] == pytest.approx(3 / 7)
    assert agreement([], [])["kappa"] is None
    assert agreement(["same"] * 3, ["same"] * 3)["status"] == "undefined_constant_marginals"
    assert proportion(0, 0)["value"] is None
    assert proportion(0, 10)["wilson95"][1] > 0.27
    assert proportion(10, 10)["wilson95"][0] < 0.73
    assert proportion(50, 100)["wilson95"] == pytest.approx([0.4038315, 0.5961685], abs=1e-6)


@pytest.mark.parametrize("mode,status", [("reassessment", "identical_payload_reassessment"), ("reused", "cache_reuse_not_independent"), ("changed", "source_or_configuration_changed")])
def test_unchanged_analyze_and_review_controls_are_distinct(root, mode, status):
    configure(root)
    reg = study.freeze(root)
    rows, _ = outputs(root, reg, all_cases=True)
    for row in rows:
        if row["case_id"].startswith("dev-unchanged"):
            path = root / row["artifact"]["path"]
            report = c.read(path)
            if mode == "changed":
                report["metadata"]["assessment"]["source_sha256"] = c.fingerprint("changed")
            else:
                report["metadata"]["assessment_execution"]["mode"] = mode
            report["overall_score"] = 60
            replace(path, report)
            row["artifact"]["sha256"] = c.file_hash(path)
    replace(root / "results.json", {"schema_version": 1, "observations": rows})
    path = root / "packet.json"
    study.packet(root, path)
    report = score(root, path)
    assert {r["control"] for r in report["controls"]} == {"unchanged_analyze", "unchanged_review", "mismatched_role"}
    assert all(r["status"] == status and r["score_delta"] == 10 for r in report["controls"] if r["control"].startswith("unchanged"))
    assert all("No score difference" in r["interpretation"] for r in report["controls"])


def test_stale_packet_outputs_and_review_hashes_are_rejected(prepared):
    root, _, packet = prepared
    a, b = (reviewed(root, packet, "test-human-" + str(i)) for i in range(2))
    target = next((root / "outputs").glob("*.json"))
    target.write_text("Changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Stale"):
        score(root, packet, [a, b])


def test_readable_pending_report_and_no_overwrites(prepared):
    root, _, packet = prepared
    report = score(root, packet)
    assert c.SHA.fullmatch(report["scoring_provenance"]["implementation_sha256"])
    rendered = markdown(report)
    assert "unmeasured" in rendered and "ATS" in rendered and "hiring" in rendered
    with pytest.raises(ValueError, match="overwrite"):
        study.packet(root, packet)


def test_preregistration_provenance_and_machine_prediction_guards(root):
    configure(root)
    reg = study.freeze(root)
    rows, units = outputs(root, reg)
    rows[0]["provenance"]["model"] = "substituted-model"
    with pytest.raises(ValueError, match="provenance"):
        study.observations_check(root, reg, {"schema_version": 1, "observations": rows})
    rows[0]["provenance"]["model"] = "synthetic-test-only"
    rows[0]["case_id"] = "different-case"
    with pytest.raises(ValueError, match="identity"):
        study.observations_check(root, reg, {"schema_version": 1, "observations": rows})
    rows[0]["case_id"] = reg["observations"][0]["case_id"]
    req = next(u for u in units if u["dimension"] == "requirement_classification")
    req["prediction_pointer"] = "/nonexistent"
    with pytest.raises(KeyError):
        study.units_check(root, reg, rows, {"schema_version": 1, "units": units})


def test_stopped_proposals_remain_in_quality_and_failure_denominators(root):
    configure(root)
    reg = study.freeze(root)
    rows, _ = outputs(root, reg)
    stopped = next(r for r in rows if r["task"] == "cover")
    stopped.update(status="failed", exit_status=1, failure_category="factual_confirmation")
    replace(root / "results.json", {"schema_version": 1, "observations": rows})
    people(root, reg["cases"])
    path = root / "packet.json"
    study.packet(root, path)
    paths = [reviewed(root, path, "test-human-" + str(i)) for i in range(2)]
    for review_path in paths:
        form = c.read(review_path)
        addition = next(a for a in form["annotations"] if a["unit_id"] == "cover-addition")
        addition.update(label="unsupported", evidence_kind="none")
        replace(review_path, form)
    result = score(root, path, paths)
    row = next(r for r in result["strata"] if r["task"] == "cover" and r["axis"] == "all" and r["control"] == "primary")
    assert row["execution_failure_rate"]["value"] == 1
    assert row["available_outputs"] == 1
    assert row["dimensions"]["addition"]["case_error_rate"]["value"] == 1
    assert row["human_review_coverage"]["value"] == 1


def test_missing_inventory_cannot_claim_full_case_quality(prepared):
    root, _, packet = prepared
    paths = [reviewed(root, packet, "test-human-" + str(i)) for i in range(2)]
    form = c.read(paths[0])
    form["inventory"] = []
    replace(paths[0], form)
    result = score(root, packet, paths)
    assert result["agreement"]["rows"]
    assert all(row["quality_status"] == "unmeasured" for row in result["observations"])


def test_duplicate_concepts_and_negative_prediction_indexes_rejected(root):
    configure(root)
    reg = study.freeze(root)
    rows, units = outputs(root, reg)
    copied = {**copy.deepcopy(units[0]), "id": "duplicate-weight"}
    with pytest.raises(ValueError, match="concept"):
        study.units_check(root, reg, rows, {"schema_version": 1, "units": [*units, copied]})
    unit = next(u for u in units if u["dimension"] == "requirement_satisfaction")
    unit["prediction_pointer"] = "/criteria/-1/status"
    with pytest.raises(ValueError, match="indexes"):
        study.units_check(root, reg, rows, {"schema_version": 1, "units": units})


def test_development_packets_and_labels_cannot_be_used_as_holdout(prepared):
    root, _, development = prepared
    review = reviewed(root, development, "test-human-0")
    held_out = root / "holdout-packet.json"
    doc = study.packet(root, held_out, "holdout")
    assert doc["split"] == "holdout" and doc["observations"] == doc["units"] == []
    with pytest.raises(ValueError, match="packet"):
        score(root, held_out, [review])
    report = score(root, held_out)
    assert report["agreement"]["rows"] == [] and report["status"] == "human_review_pending"


def test_requirement_and_omission_error_counts_are_separate(prepared):
    root, _, packet = prepared
    paths = [reviewed(root, packet, "test-human-" + str(i)) for i in range(2)]
    for path in paths:
        doc = c.read(path)
        next(a for a in doc["annotations"] if a["unit_id"] == "analyze-requirement_satisfaction").update(label="missing", evidence_kind="none")
        next(a for a in doc["annotations"] if a["unit_id"] == "adapt-omission")["label"] = "harmful"
        replace(path, doc)
    report = score(root, packet, paths)
    analysis = next(s for s in report["strata"] if s["axis"] == "domain" and s["task"] == "analyze" and s["control"] == "primary")
    assert analysis["dimensions"]["requirement_satisfaction"]["confusion"] == [{"reference": "missing", "prediction": "partial", "count": 1}]
    adapt = next(s for s in report["strata"] if s["axis"] == "seniority" and s["task"] == "adapt" and s["control"] == "primary")
    assert adapt["dimensions"]["omission"]["case_error_rate"]["value"] == 1
    assert adapt["dimensions"]["addition"]["case_error_rate"]["value"] == 0


def test_jd_pass_never_contains_candidate_or_machine_predictions(prepared):
    root, _, packet = prepared
    dest = root / "blind.json"
    study.review_template(root, packet, "test-human-0", dest)
    job_pass = c.read(dest.with_suffix(".job-pass.json"))
    assert job_pass["documents"] and all(d["document"] == "asset:job" for d in job_pass["documents"])
    assert all(u["dimension"] == "requirement_classification" and "prediction_pointer" not in u for u in job_pass["units"])
    assert "Fictional Institute" not in json.dumps(job_pass)
    assert job_pass["contexts"] and all(c["as_of_date"] == "2026-10-24" and c["task"] in ("extract", "analyze", "adapt", "review", "cover") for c in job_pass["contexts"])
    assert job_pass["method_documents"] == c.read(root / "registration.json")["method_documents"]
    output_pass = c.read(dest.with_suffix(".output-pass.json"))
    assert "synthetic-test-only" not in json.dumps(output_pass)
    assert all("overall_score" not in json.loads(d["content"]) for d in output_pass["documents"])


@pytest.mark.parametrize("native_format", ["pdf", "docx"])
def test_native_binary_requires_original_and_verified_conversion(root, native_format):
    doc = c.read(root / "development/manifest.json")
    doc["cases"] = [doc["cases"][0]]
    case = doc["cases"][0]
    case["native_format"] = native_format
    path = root / ("development/sources/native." + native_format)
    if native_format == "pdf":
        path.write_bytes(b"%PDF-1.4\n% synthetic format-contract test only\n")
    else:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", "<document>Synthetic format-contract test only</document>")
    case["assets"].append({"id": "native", "role": "native", "path": "sources/" + path.name, "sha256": c.file_hash(path), "is_text": False})
    replace(root / "development/manifest.json", doc)
    with pytest.raises(ValueError, match="conversion"):
        study.status(root)
    case["assets"][0].update(derived_from="native", conversion_verified=True)
    replace(root / "development/manifest.json", doc)
    assert study.status(root)["sampling"]["status"] == "sampling_pending"


def test_credentials_and_duplicate_json_rejected(root):
    path = root / "bad.json"
    path.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        c.read(path)
    configure(root)
    config = c.read(root / "configurations.json")
    config["configurations"][0]["api_key"] = "not-allowed"
    with pytest.raises(ValueError, match="credentials"):
        c.configuration_check(config, c.read(root / "protocol.json"))


def test_pending_adjudicator_cannot_resolve_a_disagreement(prepared):
    root, _, _ = prepared
    assignments = c.read(root / "assignments.json")
    for row in assignments["assignments"]:
        row["adjudicator_id"] = None
    replace(root / "assignments.json", assignments)
    packet = root / "pending-adjudicator-packet.json"
    study.packet(root, packet)
    a, b = [reviewed(root, packet, "test-human-" + str(i)) for i in range(2)]
    doc = c.read(b)
    decision = next(row for row in doc["annotations"] if row["unit_id"] == "adapt-fidelity")
    decision["label"] = "unsupported_specificity"
    replace(b, doc)
    target = root / "invalid-adjudication.json"
    replace(target, {"schema_version": 1, "packet_sha256": c.read(packet)["sha256"], "adjudicator_id": None,
        "review_sha256": {c.read(p)["reviewer_id"]: c.fingerprint(c.read(p)) for p in (a, b)},
        "completed_at": now(), "reviewed_original_submissions": True, "decisions": [decision]})
    with pytest.raises(ValueError, match="third human"):
        score(root, packet, [a, b], [target])
