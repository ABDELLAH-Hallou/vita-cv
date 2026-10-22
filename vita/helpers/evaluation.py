"""Shared analysis/review contract, stable scoring rubric, and Markdown rendering."""

import copy
from pathlib import Path

from vita.helpers.assessment_narrative import qualitative_text
from vita.helpers.candidate_evidence import (
    candidate_instruction,
    capture_candidate_sources,
    verification_notice,
    verify_criteria,
)
from vita.helpers.job_extraction import JobContext, fingerprint, read_job
from vita.helpers.requirements import IMPORTANCE, WEIGHTS, assert_current
from vita.helpers.structured import (
    CANONICAL_CRITERION_FIELDS,
    CATEGORIES,
    EVALUATION_OUTPUT_SCHEMA,
    EVALUATION_SCHEMA,
    json_text,
    parse_json,
    validate,
    write_artifact,
)

RESULTS = Path(".vita/results")
TAXONOMY_FIELDS = ("id", "job_id", "category", "criterion", "importance")
STATUS_VALUE = {"matched": 1, "partial": 0.5, "missing": 0}


def taxonomy(report: dict) -> list[dict]:
    return sorted(
        ({key: item[key] for key in (*TAXONOMY_FIELDS, *CANONICAL_CRITERION_FIELDS) if key in item}
         for item in report["metrics"]["criteria"]),
        key=lambda item: item["id"],
    )


def criterion_weight(item: dict) -> int:
    return item.get("weight", 2 if item["importance"] == "must_have" else 1)


def scores(criteria: list[dict]) -> tuple[float, dict]:
    def percentage(items):
        total = earned = 0
        for item in items:
            weight = criterion_weight(item)
            total += weight
            earned += weight * STATUS_VALUE[item["status"]]
        return round(100 * earned / total, 2) if total else 0

    return percentage(criteria), {
        category: percentage([item for item in criteria if item["category"] == category])
        for category in CATEGORIES
    }


def validate_evaluation(report: dict) -> None:
    validate(report, EVALUATION_SCHEMA)
    criteria = report["metrics"]["criteria"]
    if len({item["id"] for item in criteria}) != len(criteria):
        raise ValueError("Evaluation contains duplicate criterion IDs")
    for item in criteria:
        if item["status"] != "missing" and not item["evidence"].strip():
            raise ValueError("Matched and partial criteria require CV evidence")
        if any(key in item for key in CANONICAL_CRITERION_FIELDS):
            if not all(key in item for key in CANONICAL_CRITERION_FIELDS):
                raise ValueError("Canonical criteria require classification, weight, ambiguity, and source references")
            if item["weight"] != WEIGHTS[item["classification"]] or item["importance"] != IMPORTANCE[item["classification"]]:
                raise ValueError("Canonical criterion classification/weight mismatch")


def load_baseline(job: JobContext) -> dict | None:
    path = RESULTS / "analysis.json"
    if not path.exists():
        return None
    try:
        if job.requirements is not None:
            if fingerprint(read_job()) != job.source_sha256:
                return None
            assert_current(job.requirements, read_job())
        data = parse_json(path.read_text(encoding="utf-8"))
        validate_evaluation(data)
        metadata = data.get("metadata", {})
        revision = job.requirements["revision"] if job.requirements is not None else None
        if metadata.get("requirements_revision") != revision:
            return None
        if metadata.get("job_sha256") != job.source_sha256 or metadata.get("context_sha256") != job.context_sha256:
            return None
        if metadata.get("criteria_sha256") != fingerprint(json_text(taxonomy(data))):
            return None
        if job.requirements is not None:
            expected = sorted([
                {key: unit[key] for key in (*TAXONOMY_FIELDS, *CANONICAL_CRITERION_FIELDS)}
                for unit in job.requirements["requirements"]
            ], key=lambda unit: unit["id"])
            if taxonomy(data) != expected:
                return None
        return canonical_report(data)
    except (ValueError, OSError, UnicodeError):
        return None


def evaluation_instruction(step: str, job: JobContext, baseline: dict | None = None, *, sources: dict | None = None) -> str:
    name = "analysis" if step == "analyze" else "review"
    instruction = (
        "\n\nSTRUCTURED EVALUATION CONTRACT (overrides skill output-format advice):\n"
        "Return only one JSON object matching this schema; VITA renders the Markdown report.\n"
        + json_text(EVALUATION_OUTPUT_SCHEMA)
        + "\nUse the same weighted-criteria-v1 rubric for analysis and review. "
        "Evaluate the current CV against every relevant stated JD requirement. "
        "Use these categories: hard_skills, soft_skills, experience, responsibilities, keywords. "
        "Do not invent requirements. Split compound requirements into assessable criteria. "
        "Each criterion must have a unique stable ID and one of these job IDs: "
        + ", ".join(job.ids)
        + ". Identify must_have versus nice_to_have. A matched criterion has explicit CV evidence; "
        "partial means relevant but incomplete evidence; missing means no CV evidence. "
        "Copy brief supporting CV evidence for matched/partial criteria. "
        "Scores are 100 * weighted earned / weighted available: must_have weight=2, "
        "nice_to_have weight=1; matched=1, partial=0.5, missing=0. "
        "Round scores to 2 decimals; use 0 for categories with no applicable criteria. "
        "VITA recomputes scores and counts from statuses. Scores measure documented coverage, "
        "not hiring probability; keyword repetition earns no extra credit. "
        "Include a qualitative executive_summary, strengths, gaps, and actionable recommendations. "
        "Describe CV evidence and remaining gaps. Do not put assessment scores, overall percentages, "
        "score changes, or baseline availability/comparison claims in any narrative field. "
        "VITA alone renders those statements from calculated scores and the verified baseline. "
        "Preserve candidate achievement metrics, such as a 40% cost reduction. "
        "Put title/headline and summary suggestions in recommendations. "
        "Omit metadata, qualitative_summary, and comparison; VITA sets these host-owned fields. "
        f"When finalizing the output, pass step='{step}' to vita.helpers.evaluation.finalize. "
        f"The outputs are .vita/results/{name}.json and .vita/results/{name}.md."
    )
    if job.requirements is not None:
        instruction += (
            "\n\nLOCKED CANONICAL JD CRITERIA (approved independently of this CV):\n"
            "Use exactly these criterion IDs, texts, categories and importance values for Analyze AND Review. "
            "Do not derive, split, duplicate, remove, or reweight criteria based on the candidate. "
            "Required=2, preferred=1, unclear=0. Unclear items remain for clarification, not capability penalties. "
            "Employment conditions are separate and unscored; unknown home-office logistics are not skill gaps. "
            "Only judge status, evidence, evidence_kind, evidence_refs, and feedback. The host supplies canonical JD source references, "
            "classifications, weights, employment conditions, denominators, and the approved revision. "
            "Do not return those host-only fields in the provider JSON.\n"
            + json_text({"revision": job.requirements["revision"], "criteria": [
                {key: item[key] for key in TAXONOMY_FIELDS} for item in job.requirements["requirements"]
            ]})
        )
    if baseline is not None:
        instruction += (
            "\n\nLOCKED JD CRITERIA:\nRe-evaluate exactly these criteria against the updated CV. "
            "Preserve every id, job_id, category, criterion, and importance value. "
            "Change only status, evidence, evidence_kind, evidence_refs, and feedback. Do not add or remove criteria. "
            "Cite the CURRENT candidate snapshot; never reuse baseline source IDs for changed CV content.\n"
            + json_text({"criteria": [{key: item[key] for key in TAXONOMY_FIELDS} for item in taxonomy(baseline)]})
        )
    return instruction + candidate_instruction(sources if sources is not None else capture_candidate_sources())


def finalize(response: str, job: JobContext, baseline: dict | None = None, *, step: str | None = None,
             sources: dict | None = None) -> dict:
    report = parse_json(response)
    validate_evaluation(report)
    criteria = report["metrics"]["criteria"]
    # Provider judgments never choose weights or provenance, even for legacy inputs.
    for item in criteria:
        for key in CANONICAL_CRITERION_FIELDS:
            item.pop(key, None)
    if job.requirements is not None:
        if fingerprint(read_job()) != job.source_sha256:
            raise ValueError("job.md changed during assessment; rerun against its new revision")
        assert_current(job.requirements, read_job())
        approved = {item["id"]: item for item in job.requirements["requirements"]}
        expected = sorted([{key: item[key] for key in TAXONOMY_FIELDS} for item in approved.values()], key=lambda x: x["id"])
        supplied = sorted([{key: item[key] for key in TAXONOMY_FIELDS} for item in criteria], key=lambda x: x["id"])
        if supplied != expected:
            raise ValueError("Assessment changed the approved canonical criteria or importance")
        for item in criteria:
            item.update({key: approved[item["id"]][key] for key in CANONICAL_CRITERION_FIELDS})
    elif any(item["importance"] == "unclear" for item in criteria):
        raise ValueError("Unclear importance requires an approved canonical requirement set")
    if any(item["job_id"] not in job.ids for item in criteria):
        raise ValueError("Evaluation references an unknown job ID")
    if set(item["job_id"] for item in criteria) != set(job.ids):
        raise ValueError("Evaluation must assess every supplied job")
    if baseline is not None and taxonomy(report) != taxonomy(baseline):
        raise ValueError("Review changed the baseline criteria; scores would not be comparable")
    report["overall_score"], report["category_scores"] = scores(criteria)
    for status in STATUS_VALUE:
        report["metrics"][f"{status}_count"] = sum(item["status"] == status for item in criteria)
    report["metrics"]["total_count"] = len(criteria)
    report["metadata"] = {
        "job_sha256": job.source_sha256, "context_sha256": job.context_sha256,
        "criteria_sha256": fingerprint(json_text(taxonomy(report))),
        "rubric_version": "weighted-criteria-v1",
    }
    # Bind citations to the host capture supplied to the provider, not a snapshot
    # or verification status returned by it. Standalone/manual callers capture now.
    current = capture_candidate_sources(sources["entry"] if sources is not None else None)
    report["metadata"]["candidate_snapshot"] = sources if sources is not None else current
    report["metadata"]["candidate_capture_status"] = (
        "stale" if sources is not None and current != sources else "captured")
    verify_criteria(criteria, report["metadata"]["candidate_snapshot"],
                    stale=report["metadata"]["candidate_capture_status"] == "stale")
    report["overall_score"], report["category_scores"] = scores(criteria)
    if job.requirements is not None:
        report["metadata"]["requirements_revision"] = job.requirements["revision"]
        report["metrics"]["employment_conditions"] = [
            {key: item[key] for key in ("id", "job_id", "criterion", "classification", "ambiguity", "source_refs")}
            for item in job.requirements["employment_conditions"]
        ]
    else:
        report["metrics"].pop("employment_conditions", None)
    stage = step or ("review" if baseline is not None else "analyze")
    if baseline is not None:
        delta = compute_delta(baseline, report)["overall_score"]
        report["comparison"] = {"status": "available", "baseline_overall_score": delta["before"],
                                "overall_delta": delta["delta"]}
    else:
        report["comparison"] = {"status": "unavailable" if stage == "review" else "not_applicable",
                                "baseline_overall_score": None, "overall_delta": None}
    # A model cannot inject host-owned commentary/comparison fields.
    report["qualitative_summary"] = qualitative_text(report["executive_summary"])
    report = canonical_report(report)
    validate_evaluation(report)
    return report


def rounded_delta(before: float, after: float) -> float:
    return round(after - before, 2) or 0.0


def score_text(score: float) -> str:
    return f"{score:.2f}"


def executive_summary(report: dict) -> str:
    """Only the host writes the public score and comparison narrative."""
    score = score_text(report["overall_score"])
    if report.get("metadata", {}).get("requirements_revision") and report["metrics"].get("weighted_available") == 0:
        return ("No confirmed capability requirements carry weight; documented coverage is not scored. "
                "Ambiguous requirements are retained for clarification. "
                + verification_notice(report["metrics"]["criteria"]))
    text = f"Overall documented coverage: {score}/100 ({score}%)."
    comparison = report["comparison"]
    if comparison["status"] == "available":
        before = score_text(comparison["baseline_overall_score"])
        change = comparison["overall_delta"]
        text += (f" A matching initial assessment is available: {before}/100 → {score}/100 "
                 f"({change:+.2f} percentage points).")
    elif comparison["status"] == "unavailable":
        text += " No matching initial assessment is available; improvement cannot be calculated."
    elif comparison["status"] == "not_applicable":
        text += " This is the initial assessment; no baseline comparison applies."
    else:
        text += " Baseline availability was not recorded in this legacy report; no comparison is asserted."
    return text + " " + verification_notice(report["metrics"]["criteria"])


def canonical_report(report: dict) -> dict:
    """Normalize new and legacy reports without mutating the supplied artifact."""
    validate_evaluation(report)
    report = copy.deepcopy(report)
    metadata = report.get("metadata", {})
    verify_criteria(report["metrics"]["criteria"], metadata.get("candidate_snapshot"),
                    stale=metadata.get("candidate_capture_status") == "stale")
    report["overall_score"], report["category_scores"] = scores(report["metrics"]["criteria"])
    for status in STATUS_VALUE:
        report["metrics"][f"{status}_count"] = sum(
            item["status"] == status for item in report["metrics"]["criteria"]
        )
    report["metrics"]["total_count"] = len(report["metrics"]["criteria"])
    criteria = report["metrics"]["criteria"]
    report["metrics"]["weighted_available"] = sum(criterion_weight(item) for item in criteria)
    report["metrics"]["weighted_earned"] = sum(criterion_weight(item) * STATUS_VALUE[item["status"]] for item in criteria)
    report["metrics"]["category_denominators"] = {
        category: sum(criterion_weight(item) for item in criteria if item["category"] == category)
        for category in CATEGORIES
    }
    report["comparison"] = report.get("comparison", {
        "status": "not_recorded", "baseline_overall_score": None, "overall_delta": None,
    })
    comparison = report["comparison"]
    if comparison["status"] == "available":
        if comparison["baseline_overall_score"] is None:
            raise ValueError("An available comparison requires a baseline score")
        comparison["baseline_overall_score"] = round(comparison["baseline_overall_score"], 2)
        comparison["overall_delta"] = rounded_delta(comparison["baseline_overall_score"], report["overall_score"])
    else:
        comparison.update(baseline_overall_score=None, overall_delta=None)
    report["qualitative_summary"] = qualitative_text(report.get("qualitative_summary", report["executive_summary"]))
    for key in ("strengths", "gaps", "recommendations"):
        report[key] = [cleaned for text in report[key] if (cleaned := qualitative_text(text))]
    for item in report["metrics"]["criteria"]:
        item["feedback"] = qualitative_text(item["feedback"])
    report["executive_summary"] = executive_summary(report)
    return report


def markdown_text(value: str) -> str:
    # Model text must not turn into raw HTML or break scoring tables.
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for char in ("\\", "|", "*", "_", "[", "]", "`", "#"):
        value = value.replace(char, "\\" + char)
    return " ".join(value.splitlines())


def render_report(report: dict, title: str) -> str:
    report = canonical_report(report)
    rows = [f"# {title}", "", "## Executive summary", "", markdown_text(report["executive_summary"]),
            "", "Scores describe documented CV coverage, not a hiring probability.", ""]
    rows += ["## Evidence verification", "", verification_notice(report["metrics"]["criteria"]),
             "", "Verified means the exact quotation occurs in a captured candidate source. "
             "It does not verify real-world employment or prove full criterion satisfaction. "
             "Inference can receive at most partial credit. Historical reports refer to their captured source versions.", ""]
    if report["qualitative_summary"]:
        rows += ["## Qualitative commentary", "", markdown_text(report["qualitative_summary"]), ""]
    rows += ["## Scoring", "", "| Category | Score | Criteria |", "|---|---:|---:|"]
    criteria = report["metrics"]["criteria"]
    for category, score in report["category_scores"].items():
        count = sum(item["category"] == category for item in criteria)
        label = score_text(score) if report["metrics"]["category_denominators"][category] else "N/A"
        rows.append(f"| {category.replace('_', ' ').title()} | {label} | {count} |")
    for heading, key in (("Strengths", "strengths"), ("Gaps", "gaps"), ("Actionable feedback", "recommendations")):
        rows += ["", f"## {heading}", ""]
        rows += ["- " + markdown_text(item) for item in report[key]] or ["None identified."]
    rows += ["", "## Criteria and evidence", "", "| Job / criterion | Status | Evidence | Verification / kind | Sources | Feedback |",
             "|---|---|---|---|---|---|"]
    sources = {source["id"]: source for source in report.get("metadata", {}).get("candidate_snapshot", {}).get("sources", [])}
    for item in criteria:
        references = "; ".join(
            f"{sources.get(ref['source_id'], {}).get('path', ref['source_id'])} "
            + (f"lines {ref['line_start']}-{ref['line_end']}" if ref["line_start"] is not None else "(exact quote)")
            for ref in item["evidence_refs"])
        verification = item["evidence_verification"]
        cells = [f"{item['job_id']} / {item['criterion']}", item["status"], item["evidence"],
                 f"{verification['status']} / {item['evidence_kind']}: {verification['reason']}", references, item["feedback"]]
        rows.append("| " + " | ".join(map(markdown_text, cells)) + " |")
    if report.get("metadata", {}).get("requirements_revision"):
        rows += ["", "## Approved requirement revision", "", report["metadata"]["requirements_revision"],
                 "", f"Weighted denominator: {report['metrics']['weighted_available']}. "
                 "Required=2; preferred=1; unclear=0. Employment conditions are not scored.", "",
                 "| Criterion | Classification | Weight | Source | Ambiguity |", "|---|---|---:|---|---|"]
        for item in criteria:
            references = "; ".join(f"{ref['job_id']} lines {ref['line_start']}-{ref['line_end']}" for ref in item["source_refs"])
            cells = [item["criterion"], item["classification"], str(item["weight"]), references, item["ambiguity"]]
            rows.append("| " + " | ".join(map(markdown_text, cells)) + " |")
        rows += ["", "## Employment conditions (not scored)", ""]
        rows += ["- " + markdown_text(item["criterion"]) for item in report["metrics"].get("employment_conditions", [])] or ["None recorded."]
    if sources:
        rows += ["", "## Captured candidate source versions", "",
                 "These identities refer to the captured text in the JSON report, not live files.", ""]
        for source in sources.values():
            rows += ["- " + markdown_text(f"{source['path']} ({source['kind']}): {source['id']}; SHA-256 {source['sha256']}")]
    return "\n".join(rows) + "\n"


def save_evaluation(step: str, report: dict) -> None:
    report = canonical_report(report)
    name = "analysis" if step == "analyze" else "review"
    text = render_report(report, "Initial analysis" if step == "analyze" else "Post-adaptation review")
    write_artifact(RESULTS / f"{name}.md", text)
    write_artifact(RESULTS / f"{name}.json", json_text(report))
    if step == "analyze":
        # Compatibility with pre-2.5 prompts and integrations.
        write_artifact(RESULTS / "analyze.md", text)


def compute_delta(before: dict, after: dict) -> dict:
    """Compare only the same job context, schema, taxonomy, and scoring rubric."""
    for report in (before, after):
        validate_evaluation(report)
        if "metadata" not in report:
            raise ValueError("Cannot compare evaluations without provenance metadata")
        if report["metadata"]["criteria_sha256"] != fingerprint(json_text(taxonomy(report))):
            raise ValueError("Evaluation criteria fingerprint is inconsistent")
    # Analyze and Review necessarily capture different CV versions. Job/taxonomy
    # provenance must match; candidate source identities are assessment-specific.
    def comparison_metadata(report):
        return {key: value for key, value in report["metadata"].items()
                if key not in ("candidate_snapshot", "candidate_capture_status")}

    if comparison_metadata(before) != comparison_metadata(after) or taxonomy(before) != taxonomy(after):
        raise ValueError("Cannot compare evaluations for different jobs or criteria")
    # Recompute from evidence statuses, including for imported JSON artifacts.
    before, after = canonical_report(before), canonical_report(after)
    for report in (before, after):
        report["overall_score"], report["category_scores"] = scores(report["metrics"]["criteria"])
    previous = {item["id"]: item for item in before["metrics"]["criteria"]}
    changes = []
    for item in after["metrics"]["criteria"]:
        old = previous[item["id"]]
        if old["status"] != item["status"]:
            changes.append({"id": item["id"], "criterion": item["criterion"],
                            "before": old["status"], "after": item["status"]})
    return {
        "schema_version": 1,
        "overall_score": {"before": before["overall_score"], "after": after["overall_score"],
                          "delta": rounded_delta(before["overall_score"], after["overall_score"])},
        "category_scores": {
            key: {"before": before["category_scores"][key], "after": after["category_scores"][key],
                  "delta": rounded_delta(before["category_scores"][key], after["category_scores"][key])}
            for key in CATEGORIES
        },
        "criterion_changes": changes,
        "metadata": before["metadata"],
    }


def save_delta(delta: dict) -> None:
    rows = ["# Evaluation changes", "", "Positive deltas indicate improved documented fit.", "",
            "| Score | Before | After | Delta |", "|---|---:|---:|---:|"]
    for label, values in {"overall": delta["overall_score"], **delta["category_scores"]}.items():
        rows.append(f"| {label} | {score_text(values['before'])} | {score_text(values['after'])} | {values['delta']:+.2f} |")
    rows += ["", "## Changed criteria", ""]
    rows += [f"- {markdown_text(item['criterion'])}: {item['before']} → {item['after']}"
             for item in delta["criterion_changes"]] or ["No status changes."]
    write_artifact(RESULTS / "delta.md", "\n".join(rows) + "\n")
    write_artifact(RESULTS / "delta.json", json_text(delta))
