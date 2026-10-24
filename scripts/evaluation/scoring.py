"""Human-only label resolution, pre-adjudication agreement, and explicit denominators."""

from collections import Counter, defaultdict
from datetime import datetime, timezone

from scripts.evaluation.contracts import (
    SHA,
    VERSION,
    fingerprint,
    prediction,
    read,
    reference,
    require,
    stamp,
    text,
)
from scripts.evaluation.study import load_packet


def proportion(numerator, denominator, *, interval=True):
    require(type(numerator) is int and type(denominator) is int and 0 <= numerator <= denominator, "Invalid rate counts")
    if denominator == 0:
        return {"numerator": numerator, "denominator": 0, "value": None, "wilson95": None}
    p = numerator / denominator
    bounds = None
    if interval:
        z = 1.959963984540054
        scale = 1 + z * z / denominator
        center = (p + z * z / (2 * denominator)) / scale
        half = z * (p * (1 - p) / denominator + z * z / (4 * denominator ** 2)) ** 0.5 / scale
        bounds = [max(0.0, center - half), min(1.0, center + half)]
    return {"numerator": numerator, "denominator": denominator, "value": p, "wilson95": bounds}


def agreement(a, b):
    require(len(a) == len(b), "Agreement requires paired units")
    n = len(a)
    if not n:
        return {"paired_units": 0, "observed_agreement": None, "kappa": None, "status": "pending_independent_reviews"}
    ca, cb = Counter(a), Counter(b)
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum(ca[label] * cb[label] for label in set(ca) | set(cb)) / n ** 2
    matrix = Counter(zip(a, b, strict=True))
    return {"paired_units": n, "observed_agreement": po, "expected_agreement": pe,
            "kappa": (po - pe) / (1 - pe) if pe < 1 else None,
            "status": "measured" if pe < 1 else "undefined_constant_marginals",
            "confusion": [{"reviewer_a": x, "reviewer_b": y, "count": count} for (x, y), count in sorted(matrix.items())]}


def annotation_check(root, registration, packet, unit, annotation):
    labels = registration["protocol"]["labels"][unit["dimension"]]
    require(annotation["label"] in labels, "Invalid human label")
    text(annotation["rationale"])
    require(annotation["evidence_kind"] in ("direct", "inference", "none"), "Distinguish direct evidence, inference, and absence")
    observations = {o["id"]: o for o in packet["observations"]}
    cases = {c["id"]: c for c in registration["cases"]}
    observation = observations[unit["observation_id"]]
    case = cases[observation["case_id"]]
    assets = {a["id"] for a in case["assets"] if a["is_text"] and (observation["task"] != "extract" or a["role"] == "job")}
    require(set(annotation["checked_sources"]) == assets, "Record review of all captured text sources; absence cannot be decided from a selected excerpt")
    for ref in annotation["refs"]:
        reference(root, case, observation, ref)
        if observation["task"] == "extract" and ref["document"] != "output":
            require(ref["document"] in {"asset:" + a["id"] for a in case["assets"] if a["role"] == "job"}, "Extraction evidence must be JD-only")
    positive = {"supported", "ambiguity_preserved", "contradicted", "retained", "matched", "partial"}
    if annotation["label"] in positive:
        require(any(r["document"].startswith("asset:") for r in annotation["refs"]), "A supported/contradictory claim needs an input source citation")
    if unit["dimension"] == "requirement_satisfaction" and annotation["label"] == "matched":
        require(annotation["evidence_kind"] == "direct", "Inference/source presence alone does not establish full criterion satisfaction")
        eligible = {"asset:" + a["id"] for a in case["assets"] if a["role"] in ("cv", "included", "knowledge")}
        require(any(r["document"] in eligible for r in annotation["refs"]), "Matched criteria need candidate evidence, not the JD alone")


def independent_reviews(root, registration, packet, paths):
    assignments = {a["case_id"]: a for a in packet["assignments"]["assignments"]}
    observations = {o["id"]: o for o in packet["observations"]}
    units = {u["id"]: u for u in packet["units"]}
    reviews, hashes, inventory = {}, {}, {}
    for path in paths:
        doc = read(path)
        require(doc["schema_version"] == VERSION and doc["packet_sha256"] == packet["sha256"], "Review belongs to another packet")
        rid = doc["reviewer_id"]
        require(rid not in hashes and rid in {r["id"] for r in packet["reviewers"]["reviewers"]}, "Unknown or duplicate reviewer submission")
        hashes[rid] = fingerprint(doc)
        populated = any(a["label"] is not None for a in doc["annotations"]) or any(a["status"] is not None for a in doc["inventory"])
        if populated:
            require(doc["independent"] is True and stamp(packet["created_at"]) <= stamp(doc["job_pass_completed_at"]) <= stamp(doc["source_pass_completed_at"]) <= stamp(doc["outputs_opened_at"]) <= datetime.now(timezone.utc), "Independent JD-first/source-first review attestation/timing is required")
        seen = set()
        for annotation in doc["annotations"]:
            uid = annotation["unit_id"]
            require(uid in units and uid not in seen, "Unknown or duplicate annotation unit")
            seen.add(uid)
            unit = units[uid]
            case_id = observations[unit["observation_id"]]["case_id"]
            require(case_id in assignments and rid in assignments[case_id]["reviewer_ids"], "Reviewer is not independently assigned to this case")
            if annotation["label"] is not None:
                annotation_check(root, registration, packet, unit, annotation)
                reviews[(rid, uid)] = annotation
        seen = set()
        for row in doc["inventory"]:
            oid, dimension = row["observation_id"], row["dimension"]
            require(oid in observations and (oid, dimension) not in seen, "Unknown/duplicate inventory review")
            seen.add((oid, dimension))
            observation = observations[oid]
            require(observation["artifact"] is not None and dimension in registration["protocol"]["required_dimensions"][observation["task"]], "Invalid inventory dimension")
            require(observation["case_id"] in assignments and rid in assignments[observation["case_id"]]["reviewer_ids"], "Inventory review is not assigned")
            if row["status"] is not None:
                has_units = any(u["observation_id"] == oid and u["dimension"] == dimension for u in units.values())
                require(row["status"] == ("complete" if has_units else "empty"), "Inventory status contradicts captured units")
                text(row["rationale"])
                inventory[(rid, oid, dimension)] = row["status"]
    return reviews, hashes, inventory


def adjudicate(root, registration, packet, paths, reviews, review_hashes):
    decisions = {}
    units = {u["id"]: u for u in packet["units"]}
    observations = {o["id"]: o for o in packet["observations"]}
    assignments = {a["case_id"]: a for a in packet["assignments"]["assignments"]}
    for path in paths:
        doc = read(path)
        require(doc["schema_version"] == VERSION and doc["packet_sha256"] == packet["sha256"], "Adjudication belongs to another packet")
        require(all(review_hashes.get(k) == v for k, v in doc["review_sha256"].items()), "Adjudication must bind to the original independent submissions")
        if any(a["label"] is not None for a in doc["decisions"]):
            require(doc["reviewed_original_submissions"] is True and stamp(packet["created_at"]) <= stamp(doc["completed_at"]) <= datetime.now(timezone.utc), "Adjudicator must attest original-review inspection and actual completion time")
        for annotation in doc["decisions"]:
            uid = annotation["unit_id"]
            require(uid in units and uid not in decisions, "Unknown/duplicate adjudication")
            unit = units[uid]
            assignment = assignments[observations[unit["observation_id"]]["case_id"]]
            require(doc["adjudicator_id"] == assignment["adjudicator_id"] and doc["adjudicator_id"] not in assignment["reviewer_ids"], "Adjudication needs the assigned distinct third human")
            ratings = [reviews.get((r, uid)) for r in assignment["reviewer_ids"]]
            require(all(r in doc["review_sha256"] for r in assignment["reviewer_ids"]), "Missing independent review hash in adjudication")
            require(all(ratings) and ratings[0]["label"] != ratings[1]["label"], "Adjudicate only actual independently rated disagreements")
            if annotation["label"] is None:
                continue
            annotation_check(root, registration, packet, unit, annotation)
            decisions[uid] = annotation["label"]
    return decisions


def unit_error(root, registration, observations, unit, label):
    if label == "cannot_judge":
        return None
    dimension = unit["dimension"]
    if dimension.startswith("requirement_"):
        return int(prediction(root, observations[unit["observation_id"]], unit) != label)
    return int(label in registration["protocol"]["error_labels"][dimension])


def control_results(root, registration, packet):
    cases = {c["id"]: c for c in registration["cases"]}
    observations = {(o["case_id"], o["configuration_id"], o["task"]): o for o in packet["observations"]}
    configs = {c["id"]: c for c in registration["configurations"]}
    results = []
    for row in packet["observations"]:
        case = cases[row["case_id"]]
        if case["control"] == "primary":
            continue
        result = {"observation_id": row["id"], "control": case["control"], "status": "unmeasured", "score_delta": None,
                  "interpretation": "No score difference in an unchanged CV is evidence of tailoring. Mismatched roles require human judgments; transferable skills are legitimate."}
        if case["control"] == "mismatched_role":
            result["status"] = "pending_human_labels" if row["status"] == "completed" else row["status"]
            results.append(result)
            continue
        baseline = observations.get((case["paired_case_id"], row["configuration_id"], "analyze"))
        if baseline and baseline["status"] == row["status"] == "completed":
            try:
                a, b = (read(root / r["artifact"]["path"]) for r in (baseline, row))
                pa, pb = a["metadata"]["assessment"], b["metadata"]["assessment"]
                required = ("source_sha256", "job_sha256", "criteria_sha256", "provider", "model", "reasoning_effort", "prompt_sha256", "system_sha256", "schema_sha256", "host_sha256", "config_sha256", "judge_sha256", "as_of_date")
                require(all(k in pa and k in pb for k in required), "Missing control provenance")
                require(all(isinstance(p[k], str) and SHA.fullmatch(p[k]) for p in (pa, pb) for k in required if k.endswith("_sha256")), "Unverifiable control fingerprints")
                require(all(p["model"] and p.get("route_source") != "inherited_unreported" and p.get("reasoning_source") != "cli_inherited_unreported" for p in (pa, pb)), "Unreported model/reasoning cannot establish an identical-input control")
                differences = [k for k in required if pa[k] != pb[k]]
                mode = b["metadata"]["assessment_execution"]["mode"]
                config = configs[row["configuration_id"]]
                routing_mismatch = any(p[k] != config[k] for p in (pa, pb) for k in ("provider", "model", "reasoning_effort", "as_of_date"))
                result.update(status="routing_differs_from_registration" if routing_mismatch else "source_or_configuration_changed" if differences else "cache_reuse_not_independent" if mode == "reused" else "identical_payload_reassessment",
                              differences=differences, score_delta=b["overall_score"] - a["overall_score"])
            except (ValueError, KeyError, TypeError):
                result["status"] = "missing_control_provenance"
        results.append(result)
    return results


def score(root, packet_path, review_paths=(), adjudication_paths=()):
    registration, packet = load_packet(root, packet_path)
    reviews, hashes, inventory = independent_reviews(root, registration, packet, review_paths)
    decisions = adjudicate(root, registration, packet, adjudication_paths, reviews, hashes)
    cases = {c["id"]: c for c in registration["cases"]}
    observations = {o["id"]: o for o in packet["observations"]}
    assignments = {a["case_id"]: a for a in packet["assignments"]["assignments"]}
    units_by_obs = defaultdict(list)
    paired = defaultdict(lambda: ([], []))
    resolved, pending, disagreements = {}, [], []
    for unit in packet["units"]:
        uid, oid = unit["id"], unit["observation_id"]
        units_by_obs[oid].append(unit)
        case = cases[observations[oid]["case_id"]]
        assignment = assignments.get(case["id"])
        raters = sorted(assignment["reviewer_ids"]) if assignment else []
        ratings = [reviews.get((r, uid)) for r in raters]
        if len(ratings) == 2 and all(ratings):
            a, b = (r["label"] for r in ratings)
            pair = tuple(raters)
            for stratum in ("all", case["domain"], "seniority:" + case["seniority"]):
                key = (case["split"], pair, unit["dimension"], stratum)
                paired[key][0].append(a)
                paired[key][1].append(b)
            if a == b:
                resolved[uid] = a
            elif uid in decisions:
                resolved[uid] = decisions[uid]
            else:
                disagreements.append(uid)
        else:
            pending.append(uid)
    agreement_rows = [{"split": split, "reviewer_pair": list(pair), "dimension": dimension, "stratum": stratum,
                       **agreement(*labels)} for (split, pair, dimension, stratum), labels in sorted(paired.items())]
    observation_scores, groups = [], defaultdict(list)
    for oid, row in observations.items():
        case = cases[row["case_id"]]
        dims = registration["protocol"]["required_dimensions"][row["task"]]
        assignment = assignments.get(case["id"])
        complete_inventory = assignment and all((rid, oid, d) in inventory for rid in assignment["reviewer_ids"] for d in dims)
        units = units_by_obs[oid]
        complete_labels = all(u["id"] in resolved for u in units)
        abstentions = sum(resolved.get(u["id"]) == "cannot_judge" for u in units)
        full = bool(row["artifact"] is not None and complete_inventory and complete_labels and units and not abstentions)
        dimension_scores = {}
        for dimension in dims:
            selected = [u for u in units if u["dimension"] == dimension]
            eligible = [(u, resolved[u["id"]]) for u in selected if u["id"] in resolved and resolved[u["id"]] != "cannot_judge"]
            errors = sum(unit_error(root, registration, observations, u, label) for u, label in eligible)
            matrix = Counter((label, prediction(root, row, u)) for u, label in eligible) if dimension.startswith("requirement_") else {}
            dimension_scores[dimension] = {"error_rate": proportion(errors, len(eligible), interval=False),
                "planned_units": len(selected), "pending_units": sum(u["id"] not in resolved for u in selected),
                "cannot_judge_units": sum(resolved.get(u["id"]) == "cannot_judge" for u in selected),
                "confusion": [{"reference": a, "prediction": b, "count": n} for (a, b), n in sorted(matrix.items())]}
        has_error = any(d["error_rate"]["numerator"] for d in dimension_scores.values()) if full else None
        item = {"observation_id": oid, "execution_status": row["status"],
                "output_available": row["artifact"] is not None, "target": row["target"],
                "quality_status": "reviewed" if full else "unmeasured", "has_semantic_error": has_error,
                "inventory_verified": bool(complete_inventory), "dimensions": dimension_scores if row["artifact"] is not None else None}
        observation_scores.append(item)
        # Never pool split, configurations, stages or dependent controls into a nominal accuracy rate.
        for axis, value in (("all", "all"), ("domain", case["domain"]), ("seniority", case["seniority"]), ("native_format", case["native_format"]), ("role", case["role"])):
            groups[(case["split"], row["configuration_id"], row["task"], case["control"], axis, value)].append(item)
    strata = []
    for (split, config, task, control, axis, value), rows in sorted(groups.items()):
        n = len(rows)
        completed = sum(r["execution_status"] == "completed" for r in rows)
        attempted = sum(r["execution_status"] != "not_run" for r in rows)
        available = sum(r["output_available"] for r in rows)
        reviewed = [r for r in rows if r["quality_status"] == "reviewed"]
        interval = control == "primary"
        dimensions = {}
        for dimension in registration["protocol"]["required_dimensions"][task]:
            measured = [r["dimensions"][dimension] for r in rows if r["dimensions"] is not None]
            eligible_cases = [r["dimensions"][dimension] for r in reviewed if r["dimensions"][dimension]["error_rate"]["denominator"]]
            matrix = Counter()
            for d in measured:
                matrix.update({(cell["reference"], cell["prediction"]): cell["count"] for cell in d["confusion"]})
            dimensions[dimension] = {
                "unit_error_rate": proportion(sum(d["error_rate"]["numerator"] for d in measured), sum(d["error_rate"]["denominator"] for d in measured), interval=False),
                "case_error_rate": proportion(sum(d["error_rate"]["numerator"] > 0 for d in eligible_cases), len(eligible_cases), interval=interval),
                "pending_units": sum(d["pending_units"] for d in measured),
                "cannot_judge_units": sum(d["cannot_judge_units"] for d in measured),
                "confusion": [{"reference": a, "prediction": b, "count": n} for (a, b), n in sorted(matrix.items())]}
        strata.append({"split": split, "configuration_id": config, "task": task, "control": control, "axis": axis, "value": value,
            "planned": n, "attempted": attempted, "completed": completed, "available_outputs": available, "unavailable": sum(r["execution_status"] == "unavailable" for r in rows),
            "not_run": sum(r["execution_status"] == "not_run" for r in rows),
            "execution_failure_rate": proportion(sum(r["execution_status"] in ("failed", "unavailable") for r in rows), attempted, interval=interval),
            "noncompletion_rate": proportion(n - completed, n, interval=interval),
            "human_review_coverage": proportion(len(reviewed), available, interval=False),
            "case_semantic_error_rate": proportion(sum(bool(r["has_semantic_error"]) for r in reviewed), len(reviewed), interval=interval),
            "dimensions": dimensions})
    pending_count = sum(r["output_available"] and r["quality_status"] != "reviewed" for r in observation_scores)
    state = "human_review_pending" if pending_count or pending or disagreements or not reviews else "reviewed_available_outputs"
    return {"schema_version": VERSION, "registration_sha256": registration["sha256"], "packet_sha256": packet["sha256"], "split": packet["split"],
            "status": state, "sampling": registration["sampling"], "review_sha256": hashes,
            "agreement": {"status": "measured" if agreement_rows else "pending_independent_reviews", "rows": agreement_rows},
            "pending": {"independent_units": pending, "adjudication_units": disagreements, "observations": pending_count},
            "observations": observation_scores, "strata": strata, "controls": control_results(root, registration, packet),
            "claims": {"ats_validated": False, "hiring_outcomes_validated": False, "representative_population_validated": False,
                       "human_qualification": "Custodian attestations, not independently verified by software",
                       "scope": "Source fidelity and documented requirement coverage; no ATS or hiring probability inference"}}


def markdown(report):
    lines = ["# Independent evaluation report", "", f"Status: **{report['status']}**. Sampling: **{report['sampling']['status']}**.", "",
             "ATS and hiring-outcome claims: **unvalidated**. This report is not a hiring-probability estimate.", "",
             "Unavailable outputs remain in execution denominators; their content quality is unmeasured. Not-run work is reported separately.", "",
             "Adapt/Cover quality concerns candidate proposals, including proposals stopped for confirmation. A reviewable failed proposal can have measured content errors while remaining an execution failure; it is never automatically applied.", "",
             "Agreement uses original independent labels before adjudication. Undefined/absent statistics are null, never invented agreement.", "",
             "| Split / configuration / task / control / stratum | Planned | Failed or unavailable | Not run | Human-reviewed available | Semantic error cases |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["strata"]:
        error = row["case_semantic_error_rate"]
        measured = f"{error['numerator']}/{error['denominator']}" if error["value"] is not None else "unmeasured"
        lines.append(f"| {row['split']} / {row['configuration_id']} / {row['task']} / {row['control']} / {row['axis']}={row['value']} | {row['planned']} | {row['execution_failure_rate']['numerator']} | {row['not_run']} | {row['human_review_coverage']['numerator']}/{row['available_outputs']} | {measured} |")
    lines.extend(["", "95% Wilson intervals in JSON apply to primary case-level rates within each configuration/task slice, conditional on this sample. Controls and unit-level error proportions are descriptive; repeated units are not independent trials.", "",
                  "Pending independent unit labels: " + str(len(report["pending"]["independent_units"])) + "; pending adjudications: " + str(len(report["pending"]["adjudication_units"])) + ".", ""])
    lines.extend(["## Dimension error counts", "", "| Split / configuration / task / control / stratum | Dimension | Error units / reviewed eligible units | Pending / cannot judge |", "| --- | --- | ---: | ---: |"])
    for row in report["strata"]:
        for dimension, values in row["dimensions"].items():
            rate = values["unit_error_rate"]
            value = f"{rate['numerator']}/{rate['denominator']}" if rate["denominator"] else "unmeasured"
            lines.append(f"| {row['split']} / {row['configuration_id']} / {row['task']} / {row['control']} / {row['axis']}={row['value']} | {dimension} | {value} | {values['pending_units']} / {values['cannot_judge_units']} |")
    lines.append("")
    return "\n".join(lines)
