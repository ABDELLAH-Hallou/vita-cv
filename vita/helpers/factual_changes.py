"""Source-linked editorial proposals. Text support is not semantic equivalence.

The host can prove outer-whitespace edits, but cannot prove that arbitrary prose
has the same meaning. Those edits need an explicit, revision-bound decision.
No model declaration (including 'wording only') can bypass that boundary.
"""

import difflib
import json
import re
from pathlib import Path

from vita.helpers.candidate_evidence import (
    capture_candidate_sources,
    digest,
    source_lines,
    stable_hash,
    validate_snapshot,
)
from vita.helpers.config import DEFAULT_CONFIG, load_config
from vita.helpers.diagnostics import failure, phase
from vita.helpers.structured import (
    CANDIDATE_SNAPSHOT_SCHEMA,
    EVIDENCE_REF_SCHEMA,
    LINE_SPAN_SCHEMA,
    STRING,
    STRINGS,
    TEXT,
    object_schema,
    parse_json,
    validate,
    write_artifact,
)

VERSION = "factual-changes/1"
ROOT = Path(".vita/factual-changes")
RESULTS = Path(".vita/results")
STEPS = ("adapt", "cover")
CONTEXT_SCHEMA = object_schema(
    {
        "contract_version": {"type": "string", "const": VERSION},
        "step": {"type": "string", "enum": list(STEPS)},
        "target": TEXT,
        "candidate_sources": CANDIDATE_SNAPSHOT_SCHEMA,
        "job_sha256": TEXT,
        "target_before": {"type": ["string", "null"]},
    }
)
FACTUAL_CHANGE_SCHEMA = object_schema(
    {
        **CONTEXT_SCHEMA["properties"],
        "document": TEXT,
        "document_sha256": TEXT,
        "revision": TEXT,
        "source_facts": {
            "type": "array",
            "items": object_schema({"id": TEXT, "source_ref": EVIDENCE_REF_SCHEMA}),
        },
        "changes": {
            "type": "array",
            "items": object_schema(
                {
                    "id": TEXT,
                    "operation": {"type": "string", "enum": ["replace", "delete", "insert"]},
                    "original": STRING,
                    "proposed": STRING,
                    "source_fact_ids": STRINGS,
                    "output_span": {**LINE_SPAN_SCHEMA, "type": ["object", "null"]},
                    "kind": {"type": "string", "enum": ["wording", "semantic_or_factual"]},
                    "reason": {
                        "type": "string",
                        "enum": [
                            "ambiguous_acronym",
                            "date_interpretation",
                            "credential_status",
                            "metric_or_unit",
                            "unverified_semantic_change",
                            "formatting_semantics_unverified",
                            "whitespace_only",
                        ],
                    },
                    "verification": {
                        "type": "string",
                        "enum": ["confirmation_required", "host_verified"],
                    },
                }
            ),
        },
        "status": {
            "type": "string",
            "enum": ["ready", "confirmation_required", "applied", "approved", "rejected"],
        },
        "application_status": {"type": "string", "enum": ["not_applied", "applied"]},
    }
)


def target_for(step):
    if step not in STEPS:
        raise ValueError("Factual changes support adapt and cover only")
    config = load_config() if Path(".vita/config.json").is_file() else DEFAULT_CONFIG
    target = (
        config.get("cover_tex_entry", "cover-letter.tex")
        if step == "cover"
        else config.get("tex_entry", "main.tex")
    )
    if not Path(target).resolve().is_relative_to(Path.cwd().resolve()):
        raise ValueError("Document target must be inside the project")
    if (
        step == "cover"
        and Path(target).resolve() == Path(config.get("tex_entry", "main.tex")).resolve()
    ):
        raise ValueError("Cover target must differ from the CV")
    return target


def _read_target(target):
    return Path(target).read_text(encoding="utf-8") if Path(target).is_file() else None


def _job_hash():
    return digest(Path("job.md").read_text(encoding="utf-8"))


def capture(step):
    """Capture before generation, including supported includes and verified KB."""
    target = target_for(step)
    # Do not recapture a known rejected/unresolved output as new source evidence.
    # This is particularly important for generated-prompt agents that write the
    # target before running the required host check.
    for previous in STEPS:
        if (RESULTS / (previous + ".facts.json")).exists():
            report = load(previous)
            if report["status"] in ("confirmation_required", "rejected") and (
                _read_target(report["target"]) == report["document"]
            ):
                raise ValueError(
                    "A rejected or unresolved proposal was copied into a target; restore the original first"
                )
    snapshot = capture_candidate_sources()
    validate_snapshot(snapshot)
    if not any(source["kind"] == "cv" for source in snapshot["sources"]):
        raise ValueError("A captured main CV is required")
    if step == "cover" and any(
        Path(source["path"]).resolve() == Path(target).resolve() for source in snapshot["sources"]
    ):
        raise ValueError("Cover target must not overwrite a captured candidate source")
    return {
        "contract_version": VERSION,
        "step": step,
        "target": target,
        "candidate_sources": snapshot,
        "job_sha256": _job_hash(),
        "target_before": _read_target(target),
    }


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_artifact(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _normalized(text):
    # Do not strip commands, punctuation, case, accents, units or qualifiers.
    return re.sub(r"\s+", " ", text).strip()


def _facts(snapshot):
    facts = []
    for source in snapshot["sources"]:
        for number, line in enumerate(source_lines(source["content"]), 1):
            if not line.strip():
                continue
            if source["kind"] == "verified_knowledge" and not any(
                span["line_start"] <= number <= span["line_end"]
                for span in source["verified_spans"]
            ):
                continue
            ref = {
                "source_id": source["id"],
                "line_start": number,
                "line_end": number,
                "quote": line,
            }
            facts.append({"id": "fact-" + stable_hash(ref), "source_ref": ref})
    return facts


def _reason(before, after):
    text = before + "\n" + after
    if re.search(r"\b(?:OOP|TTR)\b", text):
        return "ambiguous_acronym"
    if re.search(r"\b(?:Sen|Present)\b|\b(?:19|20)\d{2}\b", text):
        return "date_interpretation"
    if re.search(r"(?i)certif|credential|expired|in.progress|expir", text):
        return "credential_status"
    if re.search(r"\d|[%$€£]", text):
        return "metric_or_unit"
    return "unverified_semantic_change"


@phase("validation")
def propose(context, document):
    """Build the entire contract on the host, independent of model annotations."""
    validate(context, CONTEXT_SCHEMA)
    if not isinstance(document, str) or not document.strip():
        raise ValueError("Proposed document is empty")
    if context["step"] == "cover" and not all(
        marker in document for marker in (r"\documentclass", r"\begin{document}", r"\end{document}")
    ):
        raise ValueError("Cover proposal must be a standalone LaTeX document")
    validate_snapshot(context["candidate_sources"])
    facts = _facts(context["candidate_sources"])
    # Cover is compared to the CV, never to JD prose or an earlier generated letter.
    before = (
        (context["target_before"] or "")
        if context["step"] == "adapt"
        else "\n".join(
            source["content"]
            for source in context["candidate_sources"]["sources"]
            if source["kind"] == "cv"
        )
    )
    changes = []
    if before.strip() != document.strip():
        old, new = source_lines(before), source_lines(document)
        matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
        for tag, start, end, out_start, out_end in matcher.get_opcodes():
            if tag == "equal":
                continue
            original, proposed = "\n".join(old[start:end]), "\n".join(new[out_start:out_end])
            refs = [fact["id"] for fact in facts if fact["source_ref"]["quote"] in old[start:end]]
            item = {
                "operation": tag,
                "original": original,
                "proposed": proposed,
                "source_fact_ids": refs,
                "output_span": {"line_start": out_start + 1, "line_end": out_end}
                if out_end > out_start
                else None,
                "kind": "wording"
                if _normalized(original) == _normalized(proposed)
                else "semantic_or_factual",
                "reason": "formatting_semantics_unverified"
                if _normalized(original) == _normalized(proposed)
                else _reason(original, proposed),
                "verification": "confirmation_required",
            }
            item["id"] = "change-" + stable_hash(item)
            changes.append(item)
    elif before != document:
        changes.append(
            {
                "id": "change-" + digest(document),
                "kind": "wording",
                "reason": "whitespace_only",
                "verification": "host_verified",
                "source_fact_ids": [fact["id"] for fact in facts],
                "original": before,
                "proposed": document,
                "output_span": {"line_start": 1, "line_end": len(source_lines(document))},
                "operation": "replace",
            }
        )
    payload = {
        **context,
        "document": document,
        "document_sha256": digest(document),
        "source_facts": facts,
        "changes": changes,
    }
    revision = "fc-" + stable_hash(payload)
    return {
        **payload,
        "revision": revision,
        "application_status": "not_applied",
        "status": "confirmation_required"
        if any(c["verification"] == "confirmation_required" for c in changes)
        else "ready",
    }


def _current(report):
    if report["contract_version"] != VERSION or report["target"] != target_for(report["step"]):
        raise ValueError("Factual-change contract or configured target changed; recapture")
    if (
        capture_candidate_sources()["sha256"] != report["candidate_sources"]["sha256"]
        or _job_hash() != report["job_sha256"]
        or _read_target(report["target"]) != report["target_before"]
    ):
        raise ValueError(
            "Sources, job, or target changed; recapture and regenerate before approval"
        )


def _context(report):
    return {
        key: report[key]
        for key in (
            "contract_version",
            "step",
            "target",
            "candidate_sources",
            "job_sha256",
            "target_before",
        )
    }


def validate_report(report):
    validate(report, FACTUAL_CHANGE_SCHEMA)
    expected = propose(_context(report), report["document"])
    if any(
        report.get(key) != value
        for key, value in expected.items()
        if key not in ("status", "application_status")
    ):
        raise ValueError("Factual-change proposal failed integrity validation")
    if (
        report["status"] in ("ready", "confirmation_required", "rejected")
        and report["application_status"] != "not_applied"
    ):
        raise ValueError("Unapproved proposal cannot have been applied")
    if report["status"] == "applied" and (
        expected["status"] != "ready" or report["application_status"] != "applied"
    ):
        raise ValueError("Unverified proposal needs explicit approval")
    if report["status"] == "ready" and expected["status"] != "ready":
        raise ValueError("Unverified proposal cannot be marked ready")


def save(report):
    validate_report(report)
    _save(ROOT / report["step"] / (report["revision"] + ".json"), report)
    _save(RESULTS / (report["step"] + ".facts.json"), report)
    lines = [
        f"# {report['step'].title()} factual changes",
        "",
        f"Status: {report['status']} ({report['application_status']})",
        f"Revision: {report['revision']}",
        "",
        "Source text support is not proof of factual truth or semantic equivalence.",
        "",
    ]
    for item in report["changes"]:
        lines += [
            f"- {item['id']}: {item['verification']} ({item['reason']})",
            "",
            "Original:",
            "```text",
            item["original"],
            "```",
            "Proposed:",
            "```text",
            item["proposed"],
            "```",
            "",
        ]
    write_artifact(RESULTS / (report["step"] + ".facts.md"), "\n".join(lines))


def load(step):
    target_for(step)
    try:
        report = parse_json((RESULTS / (step + ".facts.json")).read_text(encoding="utf-8"))
        validate_report(report)
        if report["step"] != step:
            raise ValueError("Mismatched factual-change step")
        return report
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid factual-change report") from exc


def stage(context, document, *, require_approval=False):
    if context["step"] == "cover" and not guard(("adapt",)):
        return False
    report = propose(context, document)
    _current(report)
    archived = ROOT / report["step"] / (report["revision"] + ".json")
    if archived.exists():
        previous = parse_json(archived.read_text(encoding="utf-8"))
        validate_report(previous)
        if previous["status"] == "rejected":
            print("This exact revision was rejected. Change the proposal before submitting again.")
            return False
    if require_approval:
        # Human batch mode also reviews host-verifiable/no-op changes. This
        # cannot weaken the existing confirmation boundary in automatic mode.
        report["status"] = "confirmation_required"
    # Persist the recoverable proposal BEFORE writing any candidate document.
    save(report)
    if report["status"] == "confirmation_required":
        failure("validation", category="confirmation_required")
        count = sum(c["verification"] == "confirmation_required" for c in report["changes"])
        print(f"Confirmation required: {count} source-linked change(s). Original document preserved.")
        if require_approval:
            print("Human approval mode: review this exact proposal before applying the document.")
        print(
            f"Inspect: vita facts show {report['step']} (or --json). Revision: {report['revision']}"
        )
        return False
    _current(report)  # Persistence can take time; preserve intervening source edits.
    write_artifact(Path(report["target"]), document)
    report["status"] = "applied"
    report["application_status"] = "applied"
    save(report)
    return True


def decide(step, revision, approve):
    if step == "cover" and not guard(("adapt",)):
        raise ValueError("Resolve Adapt before deciding a downstream Cover proposal")
    report = load(step)
    resumable = (
        approve and report["status"] == "approved" and report["application_status"] == "not_applied"
    )
    if revision != report["revision"] or (
        report["status"] != "confirmation_required" and not resumable
    ):
        raise ValueError("Decision requires the exact current unresolved revision")
    _current(report)
    # Record the explicit human decision first; a persistence failure must never
    # leave an applied document with only a rejected/unresolved decision on disk.
    report["status"] = "approved" if approve else "rejected"
    save(report)
    if approve:
        _current(report)
        write_artifact(Path(report["target"]), report["document"])
        report["application_status"] = "applied"
        save(report)
    write_artifact(
        RESULTS / (step + ".md"),
        f"Factual-change revision {report['revision']}: {report['status']}, {report['application_status']}. See {step}.facts.md.\n",
    )
    return report


def guard(steps=STEPS):
    """Legacy projects have no contract. Known pending/rejected proposals fail closed."""
    for step in steps:
        path = RESULTS / (step + ".facts.json")
        if not path.exists():
            continue
        try:
            report = load(step)
            if report["status"] in ("confirmation_required", "ready") or (
                report["status"] == "approved" and report["application_status"] != "applied"
            ):
                raise ValueError("Unresolved factual interpretations")
            if report["status"] == "rejected":
                _current(report)
        except (ValueError, OSError, KeyError, TypeError):
            failure("validation", category="confirmation_required")
            print(
                f"Blocked by {step} factual changes. Inspect `vita facts show {step}`; resolve or regenerate from preserved sources."
            )
            return False
    return True


def instruction(step, *, auto=False):
    preservation = (
        "\n\nFACTUAL PRESERVATION CONTRACT factual-changes/1 (takes precedence over tailoring and translation):\n"
        "Do not invent candidate facts or silently add specificity from the JD. Preserve ambiguous dates "
        "(including Sen 2017 and overlapping Present roles), undefined acronyms (OOP is not Object Oriented Design; "
        "do not expand TTR without its definition), metrics, units, unspecified currency (1M is not $1M), "
        "expired/in-progress credential qualifiers, and official names in their original language. "
        "A translated proper-name gloss may accompany, never replace, the original, and needs confirmation. "
        "Only captured CV/include sources and explicitly verified knowledge spans support candidate facts; "
        "job descriptions and analyses are never proof. Separate ordinary wording from semantic changes. "
        "Preserve original facts or stop for confirmation; never guess a repair. The host validates changes "
        "independently; model claims of equivalence or approval are not authorization.\n"
    )
    if auto:
        return preservation + (
            "AUTONOMOUS GENERATION: The host has already captured the factual sources supplied below. "
            "Do not run commands, read files, write proposals, or approve changes. "
            "Return the requested complete LaTeX document in the host's output format. "
            "File-reading and saving instructions in task skills belong to the host in this mode. "
            "After generation the host checks the returned document against those captured sources, "
            "stages the proposal and requires explicit review of unresolved factual interpretations. "
            "Do not treat your own approval or equivalence claims as authorization.\n"
        )
    return preservation + (
        "Generated-prompt execution: before generating run `vita facts capture " + step + "`. "
        "Write ONLY a proposed document to a separate project-local .tex file, never overwrite the target. "
        "Then run `vita facts check " + step + " --proposal <path>`. Stop on nonzero status; "
        "show the source-linked confirmation items. Only the host check/explicit human approval may apply it. "
        "Recapture at execution time, so sequential tasks use current sources."
        " Read the resulting .vita/factual-changes/"
        + step
        + ".capture.json for immutable source identities and exact text."
    )
