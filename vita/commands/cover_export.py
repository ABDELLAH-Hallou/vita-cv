"""Publish the current cover letter and explicitly reviewed short wording."""

import contextlib
import io
import json
import subprocess
import unicodedata
from pathlib import Path

from vita.commands import build
from vita.helpers import factual_changes as facts
from vita.helpers.candidate_evidence import stable_hash
from vita.helpers.config import load_config
from vita.helpers.context_builder import cv_source_files
from vita.helpers.diagnostics import storage_lock
from vita.helpers.structured import write_artifact

VERSION = "cover-export/1"
STATE = facts.ROOT / "cover-short.json"


class ExportError(ValueError):
    """Error suitable for the public CLI envelope."""


def _source(language):
    if not language:
        raise ExportError("Supply the cover letter's language.")
    files = cv_source_files(facts.target_for("cover"))
    if not files:
        raise ExportError("Create the cover letter before exporting or shortening it.")
    if not facts.guard(("adapt", "cover")):
        raise ExportError("Resolve the current factual-change review before exporting.")
    approval = None
    if (facts.RESULTS / "cover.facts.json").is_file():
        report = facts.load("cover")
        facts.assert_applied_current(report)
        if report.get("language", language) != language:
            raise ExportError("The selected language differs from the published cover letter.")
        approval = report["revision"]
    return stable_hash({"language": language, "files": files, "approval": approval})


def _text(text):
    return {"text": text, "character_count": len(text)}


def _pdf_text(pdf):
    try:
        result = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-nopgbrk", str(pdf), "-"],
            capture_output=True, check=True, encoding="utf-8", timeout=30,
        )
    except FileNotFoundError:
        return {"status": "unavailable", "reason": "poppler_missing"}
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return {"status": "unavailable", "reason": "extraction_failed"}
    text = unicodedata.normalize("NFC", result.stdout.strip())
    return {"status": "ready", **_text(text)} if text else {
        "status": "unavailable", "reason": "no_selectable_text",
    }


def _short_view(record, source, *, for_export=False):
    if record is None:
        return {"status": "missing"}
    if record["source_revision"] != source:
        return {"status": "stale"}
    status = record["status"]
    view = {"status": status, "revision": record["revision"]}
    if status == "approved" or (status == "pending" and not for_export):
        view.update(_text(record["text"]))
    return view


def _stage(draft, source, records):
    path = Path(draft).resolve()
    if not path.is_relative_to(Path.cwd().resolve()):
        raise ExportError("Keep the proposed short wording inside the project.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ExportError("Supply nonempty short wording for review.")
    revision = "cs-" + stable_hash({"source_revision": source, "text": text})
    record = records.setdefault(revision, {"revision": revision, "source_revision": source,
                                          "status": "pending", "text": text})
    if record["status"] == "rejected":
        raise ExportError("This exact wording was rejected. Edit it and stage a new revision.")
    return record


def _execute(action, language, draft, revision):
    source = _source(language)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"revisions": {}}
    records = state["revisions"]
    record = records.get(state.get("current"))
    result = {"contract_version": VERSION, "status": "ready", "language": language,
              "source_revision": source}

    if action == "stage-short":
        record = _stage(draft, source, records)
    elif action in ("approve-short", "reject-short"):
        if (not record or record["source_revision"] != source or record["revision"] != revision
                or record["status"] != "pending"):
            raise ExportError("Decide the exact pending short revision for the current cover letter.")
        record["status"] = "approved" if action == "approve-short" else "rejected"
    elif action == "export":
        config = load_config()
        pdf = (Path(config.get("output_dir", "out")) / build.cover_pdf_name(config)).resolve()
        if not build.run("cover"):
            raise ExportError("PDF build failed. Run vita build --cover for compiler output.")
        with pdf.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ExportError("The build output is not a PDF.")
        result.update(pdf_path=str(pdf), plain_text=_pdf_text(pdf))

    if action != "show" and _source(language) != source:
        raise ExportError("The cover letter changed during this operation. Try again with the current source.")
    if action in ("stage-short", "approve-short", "reject-short"):
        state["current"] = record["revision"]
        write_artifact(STATE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    result["short"] = _short_view(record, source, for_export=action == "export")
    return result


def run(action, *, language, draft=None, revision=None, as_json=False):
    try:
        lock = contextlib.nullcontext() if action == "show" else storage_lock(STATE.parent / "cover-export")
        with contextlib.redirect_stdout(io.StringIO()), lock:
            result = _execute(action, language.strip().casefold(), draft, revision)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"contract_version": VERSION, "status": "failed", "error": (
            str(exc) if isinstance(exc, ExportError)
            else "Cannot export or review this cover letter. Verify the current published source and its review."
        )}
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["status"] == "failed":
        print(result["error"])
    else:
        if "pdf_path" in result:
            print(result["pdf_path"])
            plain = result["plain_text"]
            if plain["status"] == "ready":
                print(f"Plain text ({plain['character_count']} characters)\n\n{plain['text']}\n")
            else:
                print("Plain text is unavailable. Use Poppler or select the text in the PDF.")
        short = result["short"]
        print(f"Short version is {short['status']}.")
        if "revision" in short:
            print(short["revision"])
        if "text" in short:
            print(f"{short['character_count']} characters\n\n{short['text']}")
    return int(result["status"] == "failed")
