"""CLI facade for explicitly staged local document ingestion."""

import json
from pathlib import Path

from vita.ingestion import pipeline, render
from vita.ingestion.contracts import IngestionError, document


def run(action, *, path=None, document_id=None, revision=None, output=None, review=None,
        ocr=False, ocr_language=None, ocr_all=False, language=None, kind="extractions", as_json=False):
    try:
        if action == "capture":
            result = pipeline.capture(path)
        elif action == "extract":
            result = pipeline.extract(document_id, ocr=ocr, language=ocr_language, ocr_all=ocr_all)
        elif action == "review":
            result = pipeline.review_template(revision, output)
        elif action == "approve":
            result = pipeline.approve(revision, review)
        elif action == "latex":
            result = render.generate(revision, output, language)
        elif action == "show":
            result = document(revision)[0] if kind == "documents" else render.show(kind, revision)
        else:
            raise IngestionError("configuration", "Unknown ingestion stage.")
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        else:
            print("Ingestion stage: " + action)
            print("Identity: " + str(result.get("revision", result.get("id", result.get("extraction_revision")))))
            if "stages" in result:
                print("Stages: " + json.dumps(result["stages"]))
            if action == "capture":
                print("Private original: " + str(Path(".vita/ingestion/documents") / result["id"] / "original.bin"))
            if "error" in result:
                print(result["error"]["category"] + ": " + result["error"]["action"])
            if action == "extract":
                print(f"Paragraphs/fragments: {len(result['paragraphs'])}; no editable LaTeX generated.")
                print("Private review report: " + str(Path(".vita/ingestion/extractions") / result["revision"] / "review.md"))
            if action == "latex":
                print("Editable source: " + result["output"])
                print("Not activated or compiled. After reviewing the source, configure tex_entry and latex_engine=xelatex; install its fonts, then run vita build.")
        if result.get("state") == "blocked":
            return 1
        return 3 if action == "extract" and result["stages"]["extract"] == "partial" else 0
    except IngestionError as exc:
        error = {"contract_version": "ingestion/1", "status": "blocked", "error": {"category": exc.category, "action": exc.action}}
        print(json.dumps(error, indent=2) if as_json else exc.category + ": " + exc.action)
        return 1
    except (ValueError, OSError, KeyError, TypeError, IndexError, UnicodeError):
        print(json.dumps({"contract_version": "ingestion/1", "status": "blocked", "error": {"category": "invalid_artifact", "action": "Invalid/missing ingestion artifact or review. Original retained; inspect the private stage files and use an intact revision."}}))
        return 1
