"""Immutable preregistrations and hash-bound, initially unannotated review packets."""

import copy
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

from scripts.evaluation.contracts import (
    VERSION,
    configuration_check,
    coverage,
    dataset,
    file_hash,
    fingerprint,
    identifier,
    local_file,
    prediction,
    protocol_check,
    read,
    reference,
    require,
    stamp,
    text,
    write,
)

HERE = Path(__file__).resolve().parent


def blinded_output(path):
    original = path.read_text(encoding="utf-8")
    try:
        value = read(path)
    except ValueError:
        return original
    if isinstance(value, dict):
        excluded = {"metadata", "provenance", "provider", "model", "reported_model", "configuration_id",
                    "overall_score", "category_scores", "comparison", "assessment_comparison", "usage"}
        value = {k: v for k, v in value.items() if k not in excluded}
        return json.dumps(value, indent=2, ensure_ascii=False)
    return original


def initialize(root):
    root.mkdir(parents=True, exist_ok=False)
    write(root / "protocol.json", read(HERE / "protocol.json"))
    write(root / "configurations.json", {"schema_version": VERSION, "configurations": []})
    write(root / "reviewers.json", {"schema_version": VERSION, "reviewers": []})
    write(root / "assignments.json", {"schema_version": VERSION, "assignments": []})
    write(root / "governance.json", {"custodian_id": None, "protocol_approved_at": None,
          "registration_reference": None, "sampling_plan_approved": False, "predeclared_analysis_approved": False,
          "holdout_tuning_forbidden": True})
    write(root / "results.json", {"schema_version": VERSION, "observations": []})
    write(root / "units.json", {"schema_version": VERSION, "units": []})
    for split in ("development", "holdout"):
        (root / split / "sources").mkdir(parents=True)
        write(root / split / "manifest.json", {"schema_version": VERSION, "cases": []})
    # Development-only inputs, with no labels or purported human qualifications.
    sources = root / "development/sources"
    corpus = HERE.parent / "benchmark/corpus"
    for name in ("main.tex", "education.tex", "job.md"):
        shutil.copyfile(corpus / name, sources / name)
    (sources / "sales-job.md").write_text(
        "# Junior Account Executive\nOwn a sales quota and document closed-won deals.\n"
        "Quota-carrying sales experience is required.\n", encoding="utf-8")
    assets = [{"id": name, "role": role, "path": "sources/" + file,
               "sha256": file_hash(sources / file), "is_text": True}
              for name, role, file in (("cv", "cv", "main.tex"), ("education", "included", "education.tex"), ("job", "job", "job.md"))]
    primary = {"id": "dev-software-junior", "split": "development", "domain": "software",
               "seniority": "junior", "native_format": "latex", "language": "en", "role": "Python Engineer",
               "candidate_group": "fictional-candidate-1", "job_group": "fictional-job-1", "family_id": "development-pair-1",
               "control": "primary", "paired_case_id": None, "origin": "synthetic",
               "rights_approved": True, "rights_reference": "Repository-owned fictional conformance corpus; no real-person CV",
               "contact_redaction_verified": True, "challenges": [], "tasks": ["extract", "analyze", "adapt", "review", "cover"], "assets": assets}
    cases = [primary]
    for control, task in (("unchanged_analyze", "analyze"), ("unchanged_review", "review"), ("mismatched_role", "analyze")):
        case = {**copy.deepcopy(primary), "id": "dev-" + control, "control": control,
                "paired_case_id": primary["id"], "tasks": [task]}
        if control == "mismatched_role":
            case.update(domain="sales", role="Junior Account Executive", job_group="fictional-sales-job", tasks=["analyze", "adapt", "cover"])
            case["assets"][-1].update(path="sources/sales-job.md", sha256=file_hash(sources / "sales-job.md"))
        cases.append(case)
    # This file was just created by init; replace its empty scaffold once.
    (root / "development/manifest.json").unlink()
    write(root / "development/manifest.json", {"schema_version": VERSION, "cases": cases})
    (root / "holdout/README.md").write_text(
        "PRIVATE HOLDOUT — EMPTY / PENDING ACQUISITION\n\n"
        "Add only rights-approved, contact-redacted sources and a verified manifest.\n"
        "Never copy development fixtures here or use holdout outputs for prompt tuning.\n"
        "No human annotations, qualifications, or agreement results have been supplied.\n", encoding="utf-8")
    return status(root)


def status(root):
    protocol = read(root / "protocol.json")
    protocol_check(protocol)
    cases = dataset(root, protocol)
    configs = configuration_check(read(root / "configurations.json"), protocol)
    return {"schema_version": VERSION, "state": "infrastructure_ready_human_work_pending",
            "scope": "Dataset/configuration inventory only; use score with supplied submissions to inspect human review",
            "sampling": coverage(cases, protocol), "configurations": len(configs),
            "human_annotations": "pending", "agreement": {"status": "unmeasured", "value": None},
            "claims": protocol["claim_boundaries"]}


def freeze(root):
    protocol = read(root / "protocol.json")
    protocol_check(protocol)
    cases = dataset(root, protocol)
    configs = configuration_check(read(root / "configurations.json"), protocol)
    require(cases and configs, "Populate source-reviewed cases and explicit configurations before freezing")
    require(protocol["status"] == "approved_by_custodian", "Protocol approval remains pending")
    governance = read(root / "governance.json")
    identifier(governance["custodian_id"])
    text(governance["registration_reference"])
    require(governance["sampling_plan_approved"] is True and governance["predeclared_analysis_approved"] is True and governance["holdout_tuning_forbidden"] is True, "Human preregistration approval remains pending")
    require(stamp(governance["protocol_approved_at"]) <= datetime.now(timezone.utc), "Invalid protocol approval time")
    observations = [{"id": "obs-" + fingerprint([c["id"], cfg["id"], task])[:24],
                     "case_id": c["id"], "configuration_id": cfg["id"], "task": task,
                     "target": "proposal" if task in ("adapt", "cover") else "validated_report"}
                    for c in cases for cfg in configs for task in c["tasks"]]
    body = {"schema_version": VERSION, "registered_at": datetime.now(timezone.utc).isoformat(),
            "protocol": protocol, "governance": governance, "cases": cases, "configurations": configs, "observations": observations,
            "sampling": coverage(cases, protocol), "ordering": "Serial: manifest case order, configuration order, then task order",
            "human_review": "pending; freeze assignments before distributing annotation packets"}
    registration = {**body, "sha256": fingerprint(body)}
    write(root / "registration.json", registration)
    return registration


def registered(root):
    doc = read(root / "registration.json")
    require(doc["sha256"] == fingerprint({k: v for k, v in doc.items() if k != "sha256"}), "Registration hash mismatch")
    protocol_check(doc["protocol"])
    require(read(root / "protocol.json") == doc["protocol"], "Protocol changed after registration; start a new study revision")
    require(read(root / "governance.json") == doc["governance"], "Preregistration approval changed after freezing")
    require(dataset(root, doc["protocol"]) == doc["cases"], "Dataset changed after registration")
    require(configuration_check(read(root / "configurations.json"), doc["protocol"]) == doc["configurations"], "Configurations changed after registration")
    return doc


def reviewer_check(reviewer, case, protocol):
    identifier(reviewer["id"])
    identifier(reviewer["person_key"])
    require(reviewer["kind"] == "human" and reviewer["identity_verified_by_custodian"] is True and reviewer["independent"] is True and reviewer["conflict_of_interest"] is False and reviewer["calibration_completed"] is True, "Human identity, independence, conflict and calibration attestations are required")
    text(reviewer["qualification_reference"])
    require(case["domain"] in reviewer["domains"] and case["language"] in reviewer["languages"] and case["native_format"] in reviewer["native_formats"], "Reviewer lacks declared domain/language/format qualification")
    years = reviewer["relevant_years"]
    require(type(years) in (int, float) and math.isfinite(years) and protocol["review_policy"]["qualification_minimum_years"] <= years <= 80 or reviewer["specialist_qualification_approved"] is True, "Reviewer qualification is pending")


def assignments_check(roster, assignments, cases, protocol):
    require(roster.get("schema_version") == assignments.get("schema_version") == VERSION, "Unsupported reviewer contract")
    people = {r["id"]: r for r in roster["reviewers"]}
    require(len(people) == len(roster["reviewers"]), "Duplicate reviewer IDs")
    require(len({r["person_key"] for r in people.values()}) == len(people), "Two reviewer IDs cannot represent the same person")
    cases = {c["id"]: c for c in cases}
    seen = set()
    for assignment in assignments["assignments"]:
        cid = assignment["case_id"]
        require(cid in cases and cid not in seen, "Invalid or duplicate case assignment")
        seen.add(cid)
        ids = assignment["reviewer_ids"]
        require(len(ids) == 2 and len(set(ids)) == 2 and all(i in people for i in ids), "Each assigned case needs two distinct humans")
        adjudicator = assignment["adjudicator_id"]
        require(adjudicator is None or adjudicator in people and adjudicator not in ids, "Adjudicator must be a distinct third qualified human")
        for rid in ids + ([adjudicator] if adjudicator else []):
            reviewer_check(people[rid], cases[cid], protocol)
    return people


def observations_check(root, registration, data):
    require(data.get("schema_version") == VERSION, "Unsupported observation contract")
    expected = {o["id"]: o for o in registration["observations"]}
    configs = {c["id"]: c for c in registration["configurations"]}
    cases = {c["id"]: c for c in registration["cases"]}
    seen, rows = set(), []
    for row in data["observations"]:
        oid = row["id"]
        require(oid in expected and oid not in seen, "Unknown or duplicate observation")
        seen.add(oid)
        plan = expected[oid]
        require(all(row.get(key, value) == value for key, value in plan.items()), "Observation identity differs from the registered plan")
        require(row["status"] in ("completed", "unavailable", "failed", "not_run"), "Unknown execution status")
        if row["status"] == "not_run":
            require(row["artifact"] is None, "Not-run observations cannot have output artifacts")
            rows.append({**plan, **row})
            continue
        require(stamp(row["started_at"]) >= stamp(registration["registered_at"]) and stamp(row["finished_at"]) >= stamp(row["started_at"]), "Execution predates preregistration or has invalid timing")
        require(type(row["attempts"]) is int and row["attempts"] >= 0, "Record actual attempt count")
        require(row["usage"] is None or isinstance(row["usage"], dict), "Unknown usage must be null")
        config = configs[plan["configuration_id"]]
        require(all(row["provenance"].get(k) == v for k, v in config.items() if k != "id"), "Execution provenance differs from the preregistered configuration")
        expected_inputs = {a["id"]: a["sha256"] for a in cases[plan["case_id"]]["assets"]}
        require(row["input_assets"] == expected_inputs, "Observation is not bound to the registered candidate/job sources")
        if row["status"] == "completed":
            require(type(row["exit_status"]) is int and row["exit_status"] == 0 and row["artifact"] is not None, "Completed observations require successful exit and an artifact")
        else:
            require(row["exit_status"] is None or type(row["exit_status"]) is int and row["exit_status"] != 0, "Failed/unavailable observations need the actual nonzero or timeout exit")
            require(row["artifact"] is None or row["status"] == "failed" and plan["target"] == "proposal", "Only inspectable Adapt/Cover proposals can be scored after an execution failure")
            text(row["failure_category"])
        if row["artifact"] is not None:
            artifact = row["artifact"]
            text(local_file(root, artifact["path"], artifact["sha256"]).read_text(encoding="utf-8"))
        rows.append({**plan, **row})
    rows.extend({**o, "status": "not_run", "artifact": None} for o in registration["observations"] if o["id"] not in seen)
    return sorted(rows, key=lambda r: list(expected).index(r["id"]))


def units_check(root, registration, observations, data):
    require(data.get("schema_version") == VERSION, "Unsupported unit inventory")
    observations = {o["id"]: o for o in observations}
    cases = {c["id"]: c for c in registration["cases"]}
    ids = set()
    for unit in data["units"]:
        identifier(unit["id"])
        require(unit["id"] not in ids, "Duplicate annotation unit")
        ids.add(unit["id"])
        observation = observations.get(unit["observation_id"])
        require(observation is not None and observation["artifact"] is not None, "Cannot annotate unavailable/not-run output")
        case = cases[observation["case_id"]]
        dimension = unit["dimension"]
        require(dimension in registration["protocol"]["required_dimensions"][observation["task"]], "Unit dimension does not apply to this task")
        text(unit["question"])
        identifier(unit["concept_id"])
        # One atomic concept per dimension/output; no duplicated weighting.
        key = (unit["observation_id"], dimension, unit["concept_id"])
        require(key not in ids, "Duplicate concept within an observation dimension")
        ids.add(key)
        refs = unit["source_refs"]
        require(isinstance(refs, list), "Source references must be a list")
        for ref in refs:
            require(ref["document"] != "output", "Source anchors must refer to captured input assets")
            reference(root, case, observation, ref)
        if unit["output_ref"] is not None:
            require(unit["output_ref"]["document"] == "output", "Output anchors must refer to the output")
            reference(root, case, observation, unit["output_ref"])
        if dimension in ("fidelity", "addition"):
            require(unit["output_ref"] is not None, "Output claims need an exact output anchor")
        else:
            require(refs, "Requirements/omissions need captured source anchors")
        if dimension.startswith("requirement_"):
            job_ids = {"asset:" + a["id"] for a in case["assets"] if a["role"] == "job"}
            require(any(r["document"] in job_ids for r in refs), "Requirement units must anchor the actual JD criterion")
            if dimension == "requirement_classification":
                require(all(r["document"] in job_ids for r in refs), "Classify JD requirements independently of candidate evidence")
            value = prediction(root, observation, unit)
            require(value in registration["protocol"]["labels"][dimension] and value != "cannot_judge", "Unknown machine requirement label")
        else:
            require(unit["prediction_pointer"] is None and unit["prediction_mode"] is None, "Qualitative fidelity labels must come from humans")
        if observation["task"] == "extract":
            job_ids = {"asset:" + a["id"] for a in case["assets"] if a["role"] == "job"}
            require(all(r["document"] in job_ids for r in refs), "Extraction fidelity must use the JD, not candidate facts")
    return data["units"]


def packet(root, destination, split="development"):
    registration = registered(root)
    require(split in ("development", "holdout"), "Choose an explicit dataset split")
    observations = observations_check(root, registration, read(root / "results.json"))
    units = units_check(root, registration, observations, read(root / "units.json"))
    roster, assignments = read(root / "reviewers.json"), read(root / "assignments.json")
    assignments_check(roster, assignments, registration["cases"], registration["protocol"])
    selected = {c["id"] for c in registration["cases"] if c["split"] == split}
    observations = [o for o in observations if o["case_id"] in selected]
    ids = {o["id"] for o in observations}
    units = [u for u in units if u["observation_id"] in ids]
    assignments = {**assignments, "assignments": [a for a in assignments["assignments"] if a["case_id"] in selected]}
    body = {"schema_version": VERSION, "registration_sha256": registration["sha256"], "split": split, "observations": observations,
            "units": units, "reviewers": roster, "assignments": assignments,
            "created_at": datetime.now(timezone.utc).isoformat(), "human_annotation_status": "pending"}
    doc = {**body, "sha256": fingerprint(body)}
    write(destination, doc)
    return doc


def load_packet(root, path):
    registration = registered(root)
    doc = read(path)
    require(doc["sha256"] == fingerprint({k: v for k, v in doc.items() if k != "sha256"}) and doc["registration_sha256"] == registration["sha256"], "Stale or altered review packet")
    expected = {o["id"] for o in registration["observations"] if next(c for c in registration["cases"] if c["id"] == o["case_id"])["split"] == doc["split"]}
    require(doc["split"] in ("development", "holdout") and {o["id"] for o in doc["observations"]} == expected, "Packet must contain exactly one complete registered split")
    observations_check(root, registration, {"schema_version": VERSION, "observations": doc["observations"]})
    units_check(root, registration, doc["observations"], {"schema_version": VERSION, "units": doc["units"]})
    assignments_check(doc["reviewers"], doc["assignments"], registration["cases"], registration["protocol"])
    return registration, doc


def review_template(root, packet_path, reviewer_id, destination):
    registration, doc = load_packet(root, packet_path)
    require(reviewer_id in {r["id"] for r in doc["reviewers"]["reviewers"]}, "Assign a qualified human before generating their form")
    assigned = {a["case_id"] for a in doc["assignments"]["assignments"] if reviewer_id in a["reviewer_ids"]}
    observations = [o for o in doc["observations"] if o["case_id"] in assigned and o["artifact"] is not None]
    ids = {o["id"] for o in observations}
    units = [u for u in doc["units"] if u["observation_id"] in ids]
    form = {"schema_version": VERSION, "packet_sha256": doc["sha256"], "reviewer_id": reviewer_id,
            "independent": False, "job_pass_completed_at": None, "source_pass_completed_at": None, "outputs_opened_at": None,
            "inventory": [{"observation_id": o["id"], "dimension": d, "status": None, "rationale": ""}
                          for o in observations for d in registration["protocol"]["required_dimensions"][o["task"]]],
            "annotations": [{"unit_id": u["id"], "label": None, "rationale": "", "evidence_kind": None,
                             "refs": [], "checked_sources": []} for u in units]}
    write(destination, form)
    # Blinded source pass excludes machine predictions, output anchors and routes.
    job_units = [{k: u[k] for k in ("id", "observation_id", "dimension", "concept_id", "question", "source_refs")}
                 for u in units if u["dimension"] == "requirement_classification"]
    source_units = [{k: u[k] for k in ("id", "observation_id", "dimension", "concept_id", "question", "source_refs")}
                    for u in units if u["dimension"] == "requirement_satisfaction"]
    output_units = [{k: u[k] for k in ("id", "observation_id", "dimension", "concept_id", "question", "source_refs", "output_ref")}
                    for u in units if not u["dimension"].startswith("requirement_")]
    cases = {c["id"]: c for c in registration["cases"]}
    documents = [{"observation_id": o["id"], "document": "asset:" + a["id"], "sha256": a["sha256"],
                  "content": local_file(root / cases[o["case_id"]]["split"], a["path"], a["sha256"]).read_text(encoding="utf-8")}
                 for o in observations for a in cases[o["case_id"]]["assets"] if a["is_text"] and (o["task"] != "extract" or a["role"] == "job")]
    outputs = []
    for o in observations:
        content = blinded_output(local_file(root, o["artifact"]["path"], o["artifact"]["sha256"]))
        outputs.append({"observation_id": o["id"], "document": "output", "original_sha256": o["artifact"]["sha256"],
                        "view_sha256": hashlib.sha256(content.encode()).hexdigest(), "content": content,
                        "view_note": "Structured routing/host-score metadata omitted; original unit spans reference the original hash, not view line numbers. Custodian must audit residual textual identifiers."})
    job_docs = [d for d in documents if d["document"] in {"asset:" + a["id"] for o in observations if o["id"] == d["observation_id"] for a in cases[o["case_id"]]["assets"] if a["role"] == "job"}]
    write(destination.with_suffix(".job-pass.json"), {"packet_sha256": doc["sha256"], "units": job_units, "documents": job_docs})
    write(destination.with_suffix(".source-pass.json"), {"packet_sha256": doc["sha256"], "units": source_units, "documents": documents})
    write(destination.with_suffix(".output-pass.json"), {"packet_sha256": doc["sha256"], "units": output_units, "documents": outputs})
    return form
