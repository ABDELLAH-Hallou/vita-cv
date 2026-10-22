"""Shared analysis/review contract, stable scoring rubric, and Markdown rendering."""

import copy
from pathlib import Path

from vita.helpers.job_extraction import JobContext, fingerprint
from vita.helpers.structured import (
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
        ({key: item[key] for key in TAXONOMY_FIELDS} for item in report["metrics"]["criteria"]),
        key=lambda item: item["id"],
    )


def scores(criteria: list[dict]) -> tuple[float, dict]:
    def percentage(items):
        total = earned = 0
        for item in items:
            weight = 2 if item["importance"] == "must_have" else 1
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


def load_baseline(job: JobContext) -> dict | None:
    path = RESULTS / "analysis.json"
    if not path.exists():
        return None
    try:
        data = parse_json(path.read_text(encoding="utf-8"))
        validate_evaluation(data)
        metadata = data.get("metadata", {})
        if metadata.get("job_sha256") != job.source_sha256 or metadata.get("context_sha256") != job.context_sha256:
            return None
        if metadata.get("criteria_sha256") != fingerprint(json_text(taxonomy(data))):
            return None
        return data
    except (ValueError, OSError, UnicodeError):
        return None


def evaluation_instruction(step: str, job: JobContext, baseline: dict | None = None) -> str:
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
        "VITA recomputes scores and counts from statuses. Scores measure documented fit, "
        "not hiring probability; keyword repetition earns no extra credit. "
        "Include an executive_summary, strengths, gaps, and actionable recommendations. "
        "Put title/headline and summary suggestions in recommendations. Omit metadata; VITA sets it. "
        f"The outputs are .vita/results/{name}.json and .vita/results/{name}.md."
    )
    if baseline is not None:
        instruction += (
            "\n\nLOCKED JD CRITERIA:\nRe-evaluate exactly these criteria against the updated CV. "
            "Preserve every id, job_id, category, criterion, and importance value. "
            "Change only status, evidence, and feedback. Do not add or remove criteria.\n"
            + json_text({"criteria": taxonomy(baseline)})
        )
    return instruction


def finalize(response: str, job: JobContext, baseline: dict | None = None) -> dict:
    report = parse_json(response)
    validate_evaluation(report)
    criteria = report["metrics"]["criteria"]
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
    validate_evaluation(report)
    return report


def markdown_text(value: str) -> str:
    # Model text must not turn into raw HTML or break scoring tables.
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for char in ("\\", "|", "*", "_", "[", "]", "`", "#"):
        value = value.replace(char, "\\" + char)
    return " ".join(value.splitlines())


def render_report(report: dict, title: str) -> str:
    rows = [f"# {title}", "", "## Executive summary", "", markdown_text(report["executive_summary"]),
            "", f"**Overall documented fit: {report['overall_score']:g}/100**", "",
            "Scores describe CV evidence, not a hiring probability.", "",
            "## Scoring", "", "| Category | Score | Criteria |", "|---|---:|---:|"]
    criteria = report["metrics"]["criteria"]
    for category, score in report["category_scores"].items():
        count = sum(item["category"] == category for item in criteria)
        label = f"{score:g}" if count else "N/A"
        rows.append(f"| {category.replace('_', ' ').title()} | {label} | {count} |")
    for heading, key in (("Strengths", "strengths"), ("Gaps", "gaps"), ("Actionable feedback", "recommendations")):
        rows += ["", f"## {heading}", ""]
        rows += ["- " + markdown_text(item) for item in report[key]] or ["None identified."]
    rows += ["", "## Criteria and evidence", "", "| Job / criterion | Status | Evidence | Feedback |",
             "|---|---|---|---|"]
    for item in criteria:
        cells = [f"{item['job_id']} / {item['criterion']}", item["status"], item["evidence"], item["feedback"]]
        rows.append("| " + " | ".join(map(markdown_text, cells)) + " |")
    return "\n".join(rows) + "\n"


def save_evaluation(step: str, report: dict) -> None:
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
    if before["metadata"] != after["metadata"] or taxonomy(before) != taxonomy(after):
        raise ValueError("Cannot compare evaluations for different jobs or criteria")
    # Recompute from evidence statuses, including for imported JSON artifacts.
    before, after = copy.deepcopy(before), copy.deepcopy(after)
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
                          "delta": round(after["overall_score"] - before["overall_score"], 2)},
        "category_scores": {
            key: {"before": before["category_scores"][key], "after": after["category_scores"][key],
                  "delta": round(after["category_scores"][key] - before["category_scores"][key], 2)}
            for key in CATEGORIES
        },
        "criterion_changes": changes,
        "metadata": before["metadata"],
    }


def save_delta(delta: dict) -> None:
    rows = ["# Evaluation changes", "", "Positive deltas indicate improved documented fit.", "",
            "| Score | Before | After | Delta |", "|---|---:|---:|---:|"]
    for label, values in {"overall": delta["overall_score"], **delta["category_scores"]}.items():
        rows.append(f"| {label} | {values['before']:g} | {values['after']:g} | {values['delta']:+g} |")
    rows += ["", "## Changed criteria", ""]
    rows += [f"- {markdown_text(item['criterion'])}: {item['before']} → {item['after']}"
             for item in delta["criterion_changes"]] or ["No status changes."]
    write_artifact(RESULTS / "delta.md", "\n".join(rows) + "\n")
    write_artifact(RESULTS / "delta.json", json_text(delta))
