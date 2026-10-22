"""Captured candidate provenance, separate from semantic criterion adjudication.

Hashes identify local text, not truth or real-world employment. Only the host
captures sources; provider-supplied snapshots/verification flags are never trusted.
"""

import hashlib
import json
from pathlib import Path

from vita.helpers.config import load_config
from vita.helpers.context_builder import cv_source_files
from vita.helpers.structured import CANDIDATE_SNAPSHOT_SCHEMA, json_text, parse_json, validate

KNOWLEDGE = Path(".vita/cv.yaml")
KNOWLEDGE_APPROVAL = Path(".vita/cv-verified.json")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_hash(value: dict) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def source_identity(source: dict) -> str:
    return "src-" + stable_hash({key: source[key] for key in ("path", "kind", "sha256", "verified_spans")})


def source_lines(content: str) -> list[str]:
    """LF source lines; Unicode separators inside LaTeX text remain literal text."""
    return content.removesuffix("\n").split("\n") if content else []


def valid_spans(spans: list, content: str) -> bool:
    count = len(source_lines(content))
    return bool(spans) and all(
        isinstance(span, dict) and set(span) == {"line_start", "line_end"}
        and type(span["line_start"]) is int and type(span["line_end"]) is int
        and 1 <= span["line_start"] <= span["line_end"] <= count for span in spans
    )


def capture_candidate_sources(entry: str | None = None) -> dict:
    """Read exactly the supported local CV graph and explicitly verified KB spans.

    The knowledge approval is an explicit user assertion tied to the exact text
    hash. Unapproved/stale/invalid approvals never establish candidate evidence.
    """
    entry = entry or load_config().get("tex_entry", "main.tex")
    sources = []
    files = cv_source_files(entry)
    entry_path = Path(entry).resolve()
    for path, content in files.items():
        source = {"path": path, "content": content, "sha256": digest(content),
                  "kind": "cv" if Path(path).resolve() == entry_path else "include", "verified_spans": []}
        source["id"] = source_identity(source)
        sources.append(source)
    try:
        # A symlink to non-project knowledge is not a supported candidate source.
        if KNOWLEDGE.resolve().is_relative_to(Path.cwd().resolve()):
            content = KNOWLEDGE.read_text(encoding="utf-8")
            approval = parse_json(KNOWLEDGE_APPROVAL.read_text(encoding="utf-8"))
            spans = approval.get("verified_spans", [])
            if (approval.get("schema_version") == 1 and approval.get("source_sha256") == digest(content)
                    and isinstance(spans, list) and valid_spans(spans, content)):
                source = {"path": KNOWLEDGE.as_posix(), "content": content, "sha256": digest(content),
                          "kind": "verified_knowledge", "verified_spans": spans}
                source["id"] = source_identity(source)
                sources.append(source)
    except (ValueError, OSError, UnicodeError):
        pass
    snapshot = {"schema_version": 1, "entry": str(entry), "sources": sorted(sources, key=lambda s: s["path"])}
    snapshot["sha256"] = stable_hash(snapshot)
    return snapshot


def validate_snapshot(snapshot: dict) -> None:
    validate(snapshot, CANDIDATE_SNAPSHOT_SCHEMA)
    if snapshot["sha256"] != stable_hash({key: value for key, value in snapshot.items() if key != "sha256"}):
        raise ValueError("Candidate source snapshot hash is inconsistent")
    ids = set()
    paths = set()
    for source in snapshot["sources"]:
        if (source["sha256"] != digest(source["content"]) or source["id"] != source_identity(source)
                or source["id"] in ids or source["path"] in paths):
            raise ValueError("Candidate source identity/content is inconsistent")
        if source["kind"] == "verified_knowledge" and not valid_spans(source["verified_spans"], source["content"]):
            raise ValueError("Invalid verified knowledge spans")
        if source["kind"] != "verified_knowledge" and source["verified_spans"]:
            raise ValueError("Unexpected knowledge approval on a CV source")
        ids.add(source["id"])
        paths.add(source["path"])


def candidate_instruction(snapshot: dict) -> str:
    return (
        "\n\nCAPTURED CANDIDATE SOURCES (the only eligible assessment evidence):\n"
        + json_text(snapshot)
        + "\nFor each criterion return evidence_kind (direct, inference, or none) and evidence_refs. "
        "Each reference requires a source_id from this snapshot and an exact, case-sensitive quote. "
        "Use 1-based inclusive line_start/line_end within that source, or null for BOTH to use exact quotation only. "
        "Set evidence to the referenced quotes joined by a newline, without paraphrases or added claims. "
        "Put your explanation in feedback. Never cite job.md, skills, previous reports, or unverified knowledge. "
        "Knowledge quotes/spans must lie wholly inside an explicitly verified_spans range. "
        "Missing evidence uses evidence_kind=none, evidence_refs=[], evidence=''. "
        "Direct means explicitly stated; inference means transferable/implied support and can be at most partial. "
        "A quote's presence does not prove complete criterion satisfaction: judge scope, duration, level, "
        "recency and compound requirements separately. Partial direct evidence must remain partial. "
        "Source verification proves text support only, not real-world employment or factual truth. "
        "VITA supplies evidence_verification; never return or edit it."
    )


def reference_error(ref: dict, sources: dict) -> str | None:
    source = sources.get(ref["source_id"])
    if source is None:
        return "Unknown or stale candidate source ID; recapture sources and cite the current identity."
    content, quote = source["content"], ref["quote"]
    lines = source_lines(content)
    start, end = ref["line_start"], ref["line_end"]
    spans = source["verified_spans"] if source["kind"] == "verified_knowledge" else [
        {"line_start": 1, "line_end": len(lines)}]
    if start is not None or end is not None:
        if start is None or end is None or not 1 <= start <= end <= len(lines):
            return "Evidence span is incomplete or out of bounds; use 1-based inclusive source lines."
        if not any(span["line_start"] <= start <= end <= span["line_end"] for span in spans):
            return "Evidence span is outside verified knowledge content."
        if quote not in "\n".join(lines[start - 1:end]):
            return "Exact evidence quote is absent from the cited span."
    elif not any(quote in "\n".join(lines[span["line_start"] - 1:span["line_end"]]) for span in spans):
        return "Exact evidence quote is absent from eligible captured content."
    return None


def verify_criteria(criteria: list[dict], snapshot: dict | None, *, stale: bool = False) -> None:
    """Replace every model-supplied verification flag; never infer a match from a quote."""
    invalid_snapshot = False
    if snapshot is not None:
        try:
            validate_snapshot(snapshot)
        except ValueError:
            invalid_snapshot = True
    sources = {source["id"]: source for source in snapshot["sources"]} if snapshot and not invalid_snapshot else {}
    for item in criteria:
        kind = item.setdefault("evidence_kind", "unspecified")
        refs = item.setdefault("evidence_refs", [])
        status, reason = "unverified", "No captured source references; legacy/model assertion only."
        if snapshot is None:
            status, reason = "not_recorded", "Legacy report: candidate sources were not captured; evidence is unverified."
        elif stale:
            reason = "Candidate sources or knowledge approval changed during assessment; rerun with current sources."
        elif invalid_snapshot:
            reason = "Captured source snapshot failed integrity validation; evidence is unverified."
        elif item["status"] == "missing" and not item["evidence"] and not refs and kind in ("none", "unspecified"):
            status, reason = "not_applicable", "No supporting evidence claimed."
        elif refs:
            errors = [reference_error(ref, sources) for ref in refs]
            reason = next((error for error in errors if error), "")
            if not reason and item["evidence"] != "\n".join(ref["quote"] for ref in refs):
                reason = "Evidence text must equal the cited exact quotes; put commentary/inferences in feedback."
            if not reason and kind not in ("direct", "inference"):
                reason = "Evidence must identify direct support versus inference."
            if not reason:
                status, reason = "verified", "Exact text verified against the captured candidate sources; semantic judgment remains separate."
        if kind == "inference" and item["status"] == "matched":
            item["status"] = "partial"
        item["evidence_verification"] = {"status": status, "reason": reason}


def verification_notice(criteria: list[dict]) -> str:
    unverified = sum(item["evidence_verification"]["status"] in ("unverified", "not_recorded") for item in criteria)
    return (f"Evidence verification: {unverified} criterion judgment(s) have unverified evidence. "
            "Coverage scores retain model judgments and do not certify those claims." if unverified else
            "Evidence verification checks captured text only; criterion satisfaction remains a model judgment.")
