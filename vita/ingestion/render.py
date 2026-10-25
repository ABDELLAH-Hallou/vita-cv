"""Generic editable Unicode LaTeX from explicitly reviewed transcription only."""

import difflib
import os
import re
from pathlib import Path

from vita.ingestion.contracts import (
    VERSION,
    load,
    read,
    require,
    seal,
    sha,
    stages,
    timestamp,
    within,
    write,
)
from vita.ingestion.pipeline import approval, clean_text, private_store

LANGUAGES = {"en": "english", "es": "spanish", "fr": "french", "ar": "arabic"}
ESCAPES = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "%": r"\%",
           "&": r"\&", "_": r"\_", "#": r"\#", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
           "\t": r"\hspace*{2em}"}
ARABIC = r"\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff"


def escaped(text):
    return "".join(ESCAPES.get(char, char) for char in text)


def prose(text, language):
    require(clean_text(text), "Approved text contains unsupported control characters or is empty.")
    # This template's fonts cover these tested scripts; never erase unsupported characters.
    require(not re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", text),
            "This generic template has no validated CJK/Korean font configuration. Preserve the reviewed text and use a suitable custom Unicode template; no LaTeX was generated.", "unsupported_font_script")
    lines = []
    for line in text.split("\n"):
        chunks = re.split("([" + ARABIC + "][" + ARABIC + " ]*)", line)
        rendered = []
        for chunk in chunks:
            if not chunk:
                continue
            if re.search("[" + ARABIC + "]", chunk):
                rendered.append(r"\textarabic{" + escaped(chunk) + "}")
            elif language == "ar" and chunk.strip():
                rendered.append(r"\textenglish{" + escaped(chunk) + "}")
            else:
                rendered.append(escaped(chunk))
        lines.append("".join(rendered))
    return r"\\ ".join(lines)


def generate(approval_revision, output, language):
    root = private_store()
    approved, extracted = approval(approval_revision)
    require(language in LANGUAGES, "Choose the source language en/es/fr/ar. Ingestion does not translate.", "unsupported_language")
    target = Path(output).resolve()
    require(target.is_relative_to(Path.cwd().resolve()) and target.suffix == ".tex" and not target.exists(),
            "Choose a new project-local .tex file. Existing/direct LaTeX sources are never overwritten.", "output_conflict")
    require(not target.is_relative_to(root), "Write the editable CV outside the immutable ingestion store.", "output_conflict")
    reviewed = {p["id"]: p for p in approved["review"]["paragraphs"]}
    original = {p["id"]: p for p in extracted["paragraphs"]}
    header = r"""\documentclass[10pt,a4paper]{article}
\usepackage[margin=18mm]{geometry}
\usepackage{fontspec}
\usepackage{polyglossia}
\setmainfont{DejaVu Serif}
\newfontfamily\arabicfont[Script=Arabic]{Amiri}
\newfontfamily\englishfont{DejaVu Serif}
\setdefaultlanguage{MAINLANG}
OTHERLANGS
\setlength{\parindent}{0pt}
\begin{document}
""".replace("MAINLANG", LANGUAGES[language])
    others = [value for value in ("english", "arabic") if value != LANGUAGES[language]]
    header = header.replace("OTHERLANGS", "\n".join(r"\setotherlanguage{" + value + "}" for value in others))
    lines, mapping, changes = header.splitlines(), [], []
    # Render everything in memory first: failed validation must not leave a partial working CV.
    for paragraph_id in approved["review"]["order"]:
        item, source = reviewed[paragraph_id], original[paragraph_id]
        changes.append({"paragraph_id": paragraph_id, "decision": item["decision"], "association": item["association"],
                        "original": source["text"], "approved": item["approved_text"], "rationale": item["rationale"],
                        "diff": list(difflib.ndiff(source["text"].splitlines(), (item["approved_text"] or "").splitlines()))})
        if item["decision"] == "omit":
            continue
        text = prose(item["approved_text"], language)
        lines.append("% ingestion paragraph " + paragraph_id)
        start = len(lines) + 1
        lines.extend([text + r"\par\medskip", ""])
        mapping.append({"document_id": source["document_id"], "paragraph_id": paragraph_id,
                        "source_ref": source["locator"], "source_text_sha256": sha(source["text"].encode("utf-8")),
                        "approved_text_sha256": sha(item["approved_text"].encode("utf-8")),
                        "latex_line_start": start, "latex_line_end": start})
    lines.append(r"\end{document}")
    content = "\n".join(lines) + "\n"
    result = seal({"contract_version": VERSION, "document_id": extracted["document_id"],
                   "extraction_revision": extracted["revision"], "approval_revision": approval_revision,
                   "created_at": timestamp(), "output": target.relative_to(Path.cwd()).as_posix(),
                   "output_sha256": sha(content.encode("utf-8")), "language": language, "translation": "not_performed",
                   "latex_engine": "xelatex", "fonts": ["DejaVu Serif", "Amiri"], "source_map": mapping,
                   "changes": changes, "format_changes": ["generic_single_column_template", "LaTeX_metacharacters_escaped",
                       "explicit_reviewed_paragraph_order", "tabs_rendered_as_spacing", "line_breaks_rendered_explicitly"],
                   "original_layout_replication": False,
                   "stages": stages(extracted["stages"]["extract"], "approved_attested", "prepared")})
    folder = within(root, root / "exports" / result["revision"])
    # A receipt, not a prepared record, establishes completed generation.
    write(folder / "record.json", result)
    prepared = folder / "prepared.tex"
    with prepared.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic exclusive publication: never clobber a source created concurrently.
    os.link(prepared, target)
    prepared.unlink()
    write(folder / "completion.json", {"export_revision": result["revision"], "output_sha256": result["output_sha256"], "completed_at": timestamp()})
    return show("exports", result["revision"])


def show(kind, revision):
    if kind == "extractions":
        from vita.ingestion.pipeline import extraction
        return extraction(revision)[0]
    if kind == "approvals":
        return approval(revision)[0]
    result, folder = load("exports", revision)
    approval(result["approval_revision"])
    target = Path(result["output"]).resolve()
    require(target.is_relative_to(Path.cwd().resolve()), "Export path left this project.", "stale_source")
    result = {**result, "generated_file_status": "missing"}
    if target.is_file():
        result["generated_file_status"] = "unchanged" if sha(target.read_bytes()) == result["output_sha256"] else "edited_source_map_no_longer_exact"
    if (folder / "completion.json").is_file():
        receipt = read(folder / "completion.json")
        require(receipt["export_revision"] == revision and receipt["output_sha256"] == result["output_sha256"], "Export completion receipt changed.", "stale_source")
        result["stages"] = {**result["stages"], "latex": "generated" if result["generated_file_status"] != "missing" else "generated_file_missing"}
    return result
