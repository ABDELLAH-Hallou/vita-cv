"""Reviewable immutable ingestion stages, reusable without the CLI or a provider."""

import re
import shutil
import subprocess
import unicodedata
import uuid
import zipfile
from pathlib import Path

from vita import __version__
from vita.ingestion import extractors
from vita.ingestion.contracts import (
    MAX_INPUT,
    VERSION,
    IngestionError,
    document,
    file_sha,
    fingerprint,
    load,
    read,
    require,
    seal,
    sha,
    stages,
    store,
    timestamp,
    within,
    write,
)


def private_store():
    root = store()
    if shutil.which("git"):
        check = subprocess.run(["git", "ls-files", "-z", "--", ".vita/ingestion"], capture_output=True, timeout=10)
        require(check.returncode in (0, 128), "Could not check private ingestion tracking status.", "privacy_configuration")
        require(not any(name and not name.endswith(b"/.gitignore") for name in check.stdout.split(b"\0")),
                "Ingestion originals/artifacts are already tracked by Git. Untrack them locally before continuing; no upload was performed.", "privacy_configuration")
    return root


def capture(path):
    root = private_store()
    path = Path(path)
    require(path.is_file(), "Choose an existing local PDF, DOCX, PNG or JPEG file.", "input_missing")
    before = path.stat()
    require(0 < before.st_size <= MAX_INPUT, "Input is empty or exceeds the 20-MiB capture limit. Original unchanged; capture did not complete.", "oversized_document")
    with path.open("rb") as handle:
        data = handle.read(MAX_INPUT + 1)
    require(0 < len(data) <= MAX_INPUT, "Input grew beyond the capture limit. No shortened source was retained.", "oversized_document")
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and len(data) == before.st_size,
            "Source changed during capture; retry a stable local file.", "stale_source")
    digest = sha(data)
    document_id = "doc-" + digest
    folder = within(root, root / "documents" / document_id)
    if folder.exists():
        return document(document_id)[0]
    folder.mkdir(parents=True, exist_ok=False)
    # The original bytes are never opened for writing. Copies are hash-checked at every stage.
    with (folder / "original.bin").open("xb") as handle:
        handle.write(data)
    extension = path.suffix.lower()
    kind = {".pdf": "pdf", ".docx": "docx", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}.get(extension, "unsupported")
    if b"%PDF-" in data[:1024]:
        kind = "pdf"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        kind = "png"
    elif data.startswith(b"\xff\xd8"):
        kind = "jpeg"
    elif data.startswith(b"PK\x03\x04"):
        kind = "docx"  # Extraction still validates the actual Office package.
    result = {"contract_version": VERSION, "id": document_id, "sha256": digest, "size_bytes": len(data),
              "original_name": path.name, "format": kind, "captured_at": timestamp(),
              "producer_version": __version__, "stages": stages(), "external_uploads": False}
    write(folder / "document.json", result)
    return result


def extract(document_id, *, ocr=False, language=None, ocr_all=False):
    root = private_store()
    source, original = document(document_id)
    work = within(root, root / "work" / uuid.uuid4().hex)
    work.mkdir(parents=True, exist_ok=False)
    body = {"contract_version": VERSION, "document_id": document_id, "source_sha256": source["sha256"],
            "created_at": timestamp(), "producer_version": __version__, "paragraphs": [], "pages": [],
            "issues": [], "options": {"ocr": ocr, "ocr_language": language, "ocr_all": ocr_all},
            "state": "blocked", "stages": stages("blocked"), "external_uploads": False}
    try:
        paragraphs, pages, issues, metadata = extractors.extract(original, source["format"], document_id, work,
                                                               ocr=ocr, language=language, ocr_all=ocr_all)
        partial = any(p["method"] == "manual_transcription_required" for p in paragraphs) or "embedded_altChunk_not_extracted" in issues
        body.update(paragraphs=paragraphs, pages=pages, issues=issues, usage=metadata, state="review_required",
                    stages=stages("partial" if partial else "complete"),
                    action="Inspect original pages and all fragments; explicitly review wording, reading order and role/date associations. Empty/visual fragments need explicit OCR or source-checked manual transcription.")
    except IngestionError as exc:
        body["error"] = {"category": exc.category, "action": exc.action}
    except (ValueError, KeyError, OSError, UnicodeError, OverflowError, zipfile.BadZipFile) as exc:
        # Parser errors contain source data/paths. Public failures remain safe; raw tool logs stay private.
        body["error"] = {"category": "corrupt_or_unsupported_document", "action": "Extraction could not finish. Inspect the original and private tool artifacts; export a supported local copy. No candidate facts or LaTeX were generated.", "exception_type": type(exc).__name__}
    if "usage" not in body:
        body["usage"] = {"ocr_requested": ocr, "ocr_language": language,
                         "ocr_invocations": len(list(work.glob("tesseract-[0-9]*.stdout"))),
                         "external_uploads": False, "tools": "inspect retained private tool logs"}
    body["artifacts"] = {p.relative_to(work).as_posix(): file_sha(p) for p in work.rglob("*") if p.is_file()}
    result = seal(body)
    final = within(root, root / "extractions" / result["revision"])
    final.parent.mkdir(parents=True, exist_ok=True)
    require(not final.exists(), "Extraction revision already exists.", "artifact_error")
    work.rename(final)
    write(final / "record.json", result)
    (final / "review.md").write_text(review_markdown(result), encoding="utf-8")
    return result


def extraction(revision):
    record, root = load("extractions", revision)
    for name, expected in record["artifacts"].items():
        path = within(root, root / name)
        require(path.is_file() and file_sha(path) == expected, "Captured extractor/OCR artifacts changed. Create a new extraction and review.", "stale_source")
    for paragraph in record["paragraphs"]:
        expected = "par-" + fingerprint({key: value for key, value in paragraph.items() if key not in ("id", "flags")})
        require(expected == paragraph["id"], "Extraction paragraph identity is invalid.", "stale_source")
    return record, root


def review_template(revision, output):
    private_store()
    record, _ = extraction(revision)
    require(record["state"] == "review_required", "Extraction is blocked; resolve its format/dependency error first.")
    result = {"contract_version": VERSION, "extraction_revision": revision,
              "reviewer": None, "original_viewed": False, "reading_order_checked": False,
              "issue_resolutions": {issue: "" for issue in record["issues"]},
              "order": [p["id"] for p in record["paragraphs"]],
              "paragraphs": [{"id": p["id"], "source_ref": p["locator"], "original_text": p["text"],
                  "decision": "pending", "approved_text": None, "source_checked": False,
                  "association": None, "rationale": "", "factual_change_confirmed": False,
                  "manual_transcription": False} for p in record["paragraphs"]]}
    output = Path(output).resolve()
    require(output.is_relative_to(Path.cwd().resolve()) and output.suffix == ".json", "Write a new review JSON inside the project.")
    write(output, result)
    return result


def clean_text(value):
    return isinstance(value, str) and bool(value.strip()) and not any(unicodedata.category(char) in ("Cc", "Cs") and char not in "\n\t" for char in value)


def approve(revision, review_path):
    root = private_store()
    record, _ = extraction(revision)
    require(record["state"] == "review_required", "Blocked extraction cannot be approved.")
    review = read(Path(review_path))
    require(set(review) == {"contract_version", "extraction_revision", "reviewer", "original_viewed", "reading_order_checked", "issue_resolutions", "order", "paragraphs"}, "Use the generated complete review template; unknown/missing fields are not approved.")
    require(review["contract_version"] == VERSION and review["extraction_revision"] == revision,
            "Review belongs to a different extraction revision.", "stale_source")
    require(clean_text(review["reviewer"]) and review["original_viewed"] is True and review["reading_order_checked"] is True,
            "A reviewer must explicitly inspect the original, wording and reading order; no automatic approval is available.")
    require(set(review["issue_resolutions"]) == set(record["issues"]) and all(clean_text(v) for v in review["issue_resolutions"].values()),
            "Resolve every extraction-wide issue explicitly; omissions cannot be silently accepted.")
    originals = {p["id"]: p for p in record["paragraphs"]}
    require(isinstance(review["order"], list) and len(review["order"]) == len(originals) and set(review["order"]) == set(originals), "Reading order must include every paragraph exactly once, including explicit omissions.")
    require(isinstance(review["paragraphs"], list) and len(review["paragraphs"]) == len(originals), "Review every extracted paragraph, including low-confidence or visual fragments.")
    seen, kept = set(), 0
    for item in review["paragraphs"]:
        require(set(item) == {"id", "source_ref", "original_text", "decision", "approved_text", "source_checked", "association", "rationale", "factual_change_confirmed", "manual_transcription"}, "Invalid paragraph review fields.")
        require(item["id"] in originals and item["id"] not in seen, "Duplicate or unknown reviewed paragraph.")
        seen.add(item["id"])
        original = originals[item["id"]]
        require(item["source_ref"] == original["locator"] and item["original_text"] == original["text"], "Source references/text cannot be edited in a review; use approved_text for a confirmed transcription correction.", "stale_source")
        require(item["source_checked"] is True and item["decision"] in ("keep", "correct", "omit"), "Every paragraph requires a source-checked keep, correct or omit decision.")
        require(item["association"] == "preserve_unassigned" or (isinstance(item["association"], str) and re.fullmatch(r"group:[A-Za-z0-9][A-Za-z0-9_-]{0,63}", item["association"])), "Explicitly preserve ambiguous associations as unassigned, or provide a reviewed group ID.")
        require(clean_text(item["rationale"]), "Record a rationale for every decision and role/date association.")
        if item["decision"] == "keep":
            require(clean_text(original["text"]) and item["approved_text"] == original["text"], "Keep must preserve exact extracted wording; an empty image fragment cannot be kept as candidate facts.")
        elif item["decision"] == "correct":
            require(clean_text(item["approved_text"]) and item["factual_change_confirmed"] is True, "Corrected wording, metrics, dates and credentials require explicit source confirmation.")
            if original["method"] == "manual_transcription_required":
                require(item["manual_transcription"] is True, "Declare source-checked manual transcription for visual/empty fragments.")
        else:
            require(item["approved_text"] is None, "Omitted paragraphs must have null approved_text; the rationale records the omission.")
        kept += item["decision"] != "omit"
    require(kept > 0, "An empty reviewed document cannot generate candidate facts or LaTeX.")
    result = seal({"contract_version": VERSION, "document_id": record["document_id"], "extraction_revision": revision,
                   "review": review, "review_sha256": fingerprint(review), "approved_at": timestamp(),
                   "verification": "explicit_reviewer_attestation_not_independent_semantic_verification",
                   "stages": stages(record["stages"]["extract"], "approved_attested")})
    write(root / "approvals" / result["revision"] / "record.json", result)
    return result


def approval(revision):
    result, _ = load("approvals", revision)
    record, _ = extraction(result["extraction_revision"])
    require(result["document_id"] == record["document_id"] and result["review_sha256"] == fingerprint(result["review"]), "Approval source/review binding changed.", "stale_source")
    return result, record


def review_markdown(record):
    lines = ["# Local ingestion review", "", "State: " + record["state"], "",
             "No semantic role/date associations or OCR corrections have been approved. Inspect the captured original; extraction confidence is not accuracy.", "",
             "Stages: " + str(record["stages"]), ""]
    if "error" in record:
        lines.extend([record["error"]["category"] + ": " + record["error"]["action"], ""])
    for p in record["paragraphs"]:
        fence = "`" * max(3, max((len(match) + 1 for match in re.findall(r"`+", p["text"])), default=3))
        lines.extend(["## " + p["id"], "", "Source: " + str(p["locator"]), "",
                      "Flags: " + ", ".join(p["flags"]), "", "Confidence: " + str(p["confidence"]), "",
                      fence + "text", p["text"], fence, ""])
    return "\n".join(lines)
