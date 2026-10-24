"""Local Poppler, WordprocessingML and explicitly requested Tesseract adapters.

No inferred role/date associations. PDF blocks are not semantic paragraphs;
DOCX has no reliable rendered pagination. OCR confidence is not factual accuracy.
"""

import csv
import io
import math
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections import defaultdict

from vita.ingestion.contracts import (
    MAX_CHARACTERS,
    MAX_EXPANDED,
    MAX_PAGES,
    MAX_PARAGRAPHS,
    MAX_PIXELS,
    IngestionError,
    fingerprint,
    require,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def xml(data):
    require(len(data) <= MAX_EXPANDED, "XML exceeds the declared size limit.", "oversized_document")
    # XML may be UTF-16/32. Match declaration markup before parsing, including
    # NUL-padded ASCII, so alternate encodings cannot enable entity expansion.
    markup = data.replace(b"\0", b"").upper()
    require(b"<!DOCTYPE" not in markup and b"<!ENTITY" not in markup,
            "XML entity declarations or oversized XML are unsupported.", "unsupported_document")
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise IngestionError("corrupt_document", "The document XML is corrupt; export a new local copy.") from None


def tool(name, args, work, label):
    executable = shutil.which(name)
    require(executable is not None, f"Install {name} locally and put it on PATH, then retry extraction. No upload or remote fallback was used.", "dependency_unavailable")
    output, error = work / (label + ".stdout"), work / (label + ".stderr")
    try:
        with output.open("xb") as out, error.open("xb") as err:
            result = subprocess.run([executable, *map(str, args)], stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        raise IngestionError("tool_timeout", "Local extraction exceeded its 60-second command limit. Original retained; inspect private tool logs.") from None
    except OSError:
        raise IngestionError("tool_failed", "The local extraction tool could not run. Inspect its installation and private logs.") from None
    require(output.stat().st_size <= MAX_EXPANDED and error.stat().st_size <= MAX_EXPANDED, "Tool output exceeds the declared extraction limit.", "oversized_document")
    if result.returncode != 0 and name == "pdfinfo" and re.search(r"password|encrypt", error.read_text(encoding="utf-8", errors="replace"), re.IGNORECASE):
        raise IngestionError("encrypted_document", "Encrypted PDF is unsupported. Export an unlocked local copy; no password or external upload was requested.")
    require(result.returncode == 0, "Local extraction failed. Inspect the private tool logs for corrupt, encrypted or unsupported content; export a new local copy.", "tool_failed")
    return output.read_text(encoding="utf-8", errors="strict")


def paragraph(document_id, method, locator, text, *, words=None, flags=None, confidence=None):
    body = {"document_id": document_id, "method": method, "locator": locator,
            "text": text, "words": words or [], "confidence": confidence,
            "flags": sorted(set(["associations_unverified", "reading_order_unverified", *(flags or [])]))}
    return {"id": "par-" + fingerprint({key: value for key, value in body.items() if key != "flags"}), **body}


def bounded(paragraphs):
    require(len(paragraphs) <= MAX_PARAGRAPHS and sum(len(p["text"]) for p in paragraphs) <= MAX_CHARACTERS,
            "Extracted text exceeds the declared limits. No history was shortened; use a reviewed smaller source as a new document.", "oversized_document")
    return paragraphs


def pdf_blocks(content, document_id):
    # Poppler emits a standard external XHTML doctype. It is not fetched;
    # internal subsets/entities remain forbidden by xml().
    content = re.sub(r"<!DOCTYPE\s+html\b[^\[>]*>", "", content, flags=re.IGNORECASE)
    root = xml(content.encode("utf-8"))
    paragraphs, pages = [], []
    for page_number, page in enumerate(root.findall(".//{*}page"), 1):
        width, height = float(page.attrib["width"]), float(page.attrib["height"])
        require(all(math.isfinite(n) and n > 0 for n in (width, height)), "Invalid PDF page geometry.", "corrupt_document")
        pages.append({"page": page_number, "width_points": width, "height_points": height})
        page_blocks = []
        for index, block in enumerate(page.findall(".//{*}block"), 1):
            lines, words = [], []
            for line_number, line in enumerate(block.findall("./{*}line"), 1):
                line_words = []
                for word_number, word in enumerate(line.findall("./{*}word"), 1):
                    text = "".join(word.itertext())
                    box = [float(word.attrib[k]) for k in ("xMin", "yMin", "xMax", "yMax")]
                    require(all(math.isfinite(n) for n in box) and 0 <= box[0] <= box[2] <= width + 1 and 0 <= box[1] <= box[3] <= height + 1,
                            "Out-of-bounds PDF text requires a new local export or manual source review.", "unsupported_geometry")
                    words.append({"text": text, "bbox": box, "line": line_number, "word": word_number})
                    line_words.append(text)
                lines.append(" ".join(line_words))
            text = "\n".join(lines)
            if not text.strip():
                continue
            box = [min(w["bbox"][0] for w in words), min(w["bbox"][1] for w in words),
                   max(w["bbox"][2] for w in words), max(w["bbox"][3] for w in words)]
            page_blocks.append(paragraph(document_id, "poppler_bbox", {"page": page_number, "block": index,
                "paragraph_kind": "layout_block_not_semantic_paragraph", "bbox": box, "artifact": "text.xhtml"}, text, words=words))
        for first in page_blocks:
            a = first["locator"]["bbox"]
            gaps = any(w["line"] == nxt["line"] and nxt["bbox"][0] - w["bbox"][2] > width * .1 for w, nxt in zip(first["words"], first["words"][1:], strict=False))
            if gaps or any(min(a[3], p["locator"]["bbox"][3]) > max(a[1], p["locator"]["bbox"][1]) and
                   (a[2] < p["locator"]["bbox"][0] or p["locator"]["bbox"][2] < a[0]) for p in page_blocks if p is not first):
                first["flags"].append("possible_columns_or_role_date_fragmentation")
        if not page_blocks:
            page_blocks.append(paragraph(document_id, "manual_transcription_required", {"page": page_number,
                "bbox": [0, 0, width, height], "artifact": "text.xhtml"}, "", flags=["no_text_layer_or_blank_page"]))
        paragraphs.extend(page_blocks)
    require(pages and len(pages) <= MAX_PAGES, "PDF page count is empty or exceeds the 30-page limit.", "oversized_document")
    return bounded(paragraphs), pages


def docx(path, document_id):
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise IngestionError("corrupt_or_encrypted_document", "DOCX is not a readable ZIP package. Encrypted Office files and legacy DOC are unsupported; export an unlocked DOCX/PDF locally.") from None
    with archive:
        entries = archive.infolist()
        require(len(entries) <= 500 and len({e.filename for e in entries}) == len(entries) and sum(e.file_size for e in entries) <= MAX_EXPANDED,
                "DOCX package exceeds entry/expanded-size limits or contains duplicate parts.", "oversized_document")
        require(not any(e.flag_bits & 1 for e in entries), "Encrypted DOCX packages are unsupported. Export an unlocked local copy.", "encrypted_document")
        require(not any(e.file_size > max(1, e.compress_size) * 300 for e in entries), "DOCX compression ratio exceeds the declared limit.", "oversized_document")
        names = {e.filename for e in entries}
        require("word/document.xml" in names and "[Content_Types].xml" in names, "This ZIP is not a supported DOCX package.", "corrupt_document")
        require(not any("vbaproject" in name.lower() for name in names), "Macro-enabled Office packages are unsupported.", "unsupported_document")
        parts = sorted(name for name in names if re.fullmatch(r"word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml", name))
        parts.remove("word/document.xml")
        parts.insert(0, "word/document.xml")
        paragraphs, issues = [], []
        for name in parts:
            root = xml(archive.read(name))
            parents = {child: parent for parent in root.iter() for child in parent}
            page_hint = 1
            for index, element in enumerate(root.iter(W + "p"), 1):
                flags, pieces = [], []
                def visit(node, current=element, output=pieces):
                    if node is not current and node.tag == W + "p":
                        return  # Text boxes have their own paragraph identity.
                    if node.tag in (W + "t", W + "delText"):
                        output.append(node.text or "")
                    elif node.tag == W + "tab":
                        output.append("\t")
                    elif node.tag in (W + "br", W + "cr"):
                        output.append("\n")
                    for child in node:
                        visit(child)
                visit(element)
                ancestor, chain = element, []
                while ancestor in parents:
                    ancestor = parents[ancestor]
                    chain.append(ancestor)
                if any(a.tag == W + "tc" for a in chain):
                    flags.append("table_cell_association_unverified")
                if any(a.tag == W + "txbxContent" for a in chain):
                    flags.append("text_box_order_unverified")
                for tag, flag in (("del", "tracked_changes_unresolved"), ("ins", "tracked_changes_unresolved"),
                                  ("drawing", "visual_content_requires_review"), ("pict", "visual_content_requires_review"),
                                  ("vanish", "hidden_text_requires_review"), ("instrText", "field_code_not_evaluated")):
                    if any(n.tag == W + tag for n in element.iter()) or any(a.tag == W + tag for a in chain):
                        flags.append(flag)
                if name.endswith("comments.xml"):
                    flags.append("comment_not_candidate_evidence")
                text = "".join(pieces)
                if text.strip() or "visual_content_requires_review" in flags:
                    method = "wordprocessingml" if text.strip() else "manual_transcription_required"
                    paragraphs.append(paragraph(document_id, method, {"page": None, "page_hint": page_hint,
                        "page_hint_status": "explicit_or_cached_break_not_rendered_pagination", "part": name,
                        "paragraph": index, "artifact": "original.bin"}, text, flags=flags))
                page_hint += sum(n.tag == W + "lastRenderedPageBreak" or (n.tag == W + "br" and n.get(W + "type") == "page") for n in element.iter())
            if any(n.tag == W + "altChunk" for n in root.iter()):
                issues.append("embedded_altChunk_not_extracted")
            if any(n.tag == W + "cols" and (int(n.get(W + "num", "1")) > 1 or len(n.findall(W + "col")) > 1) for n in root.iter()):
                issues.append("multiple_section_columns_reading_order_unverified")
        for name in sorted(n for n in names if n.endswith(".rels")):
            for index, rel in enumerate(xml(archive.read(name)), 1):
                if rel.get("TargetMode") == "External":
                    paragraphs.append(paragraph(document_id, "docx_relationship", {"page": None, "part": name,
                        "relationship": rel.get("Id", str(index)), "artifact": "original.bin"}, rel.get("Target", ""),
                        flags=["external_target_not_fetched_or_verified"]))
        require(paragraphs, "DOCX contains no supported text/paragraphs. Export it to PDF for explicit OCR or provide a reviewed transcription.", "no_text")
        return bounded(paragraphs), [{"page": None, "pagination": "unavailable_without_Word_rendering"}], sorted(set(issues))


def image_size(path):
    require(path.is_file() and path.stat().st_size <= MAX_EXPANDED, "Image is missing or exceeds the raster artifact limit.", "oversized_document")
    with path.open("rb") as handle:
        header = handle.read(24)
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            require(len(header) == 24 and header[12:16] == b"IHDR", "Corrupt PNG header.", "corrupt_document")
            width, height = struct.unpack(">II", header[16:24])
            handle.seek(8)
            kinds = set()
            while True:
                chunk = handle.read(8)
                require(len(chunk) == 8, "Corrupt/truncated PNG chunk.", "corrupt_document")
                size, kind = struct.unpack(">I4s", chunk)
                require(size <= MAX_EXPANDED, "PNG chunk exceeds the declared limit.", "oversized_document")
                payload, crc = handle.read(size), handle.read(4)
                require(len(payload) == size and len(crc) == 4 and zlib.crc32(kind + payload) == struct.unpack(">I", crc)[0], "PNG chunk checksum is invalid.", "corrupt_document")
                kinds.add(kind)
                require(kind != b"acTL", "Animated PNG/multiple image frames are unsupported. Export all pages into a local PDF.", "unsupported_document")
                if kind == b"IEND":
                    break
            require({b"IHDR", b"IDAT", b"IEND"}.issubset(kinds), "PNG has no supported pixel data.", "corrupt_document")
        elif header.startswith(b"\xff\xd8"):
            handle.seek(-2, 2)
            require(handle.read(2) == b"\xff\xd9", "JPEG is truncated.", "corrupt_document")
            handle.seek(2)
            while True:
                start = handle.read(1)
                require(start, "Corrupt JPEG header.", "corrupt_document")
                if start != b"\xff":
                    continue
                marker = handle.read(1)
                while marker == b"\xff":
                    marker = handle.read(1)
                require(marker and marker not in (b"\xd9", b"\xda"), "JPEG has no supported frame dimensions.", "corrupt_document")
                length = handle.read(2)
                require(len(length) == 2, "Corrupt JPEG segment.", "corrupt_document")
                size = struct.unpack(">H", length)[0]
                require(size >= 2, "Corrupt JPEG segment length.", "corrupt_document")
                if marker[0] in (0xC0, 0xC1, 0xC2):
                    frame = handle.read(5)
                    require(len(frame) == 5, "Corrupt JPEG frame.", "corrupt_document")
                    height, width = struct.unpack(">HH", frame[1:])
                    break
                handle.seek(size - 2, 1)
        else:
            raise IngestionError("unsupported_document", "Only PDF, DOCX, PNG and JPEG ingestion is supported. Convert TIFF/other formats locally to a supported source; originals remain unchanged.")
    require(0 < width * height <= MAX_PIXELS and width > 0 and height > 0, "Image exceeds the 25-million-pixel limit.", "oversized_document")
    return width, height


def ocr_tsv(content, document_id, page, artifact, bounds=None):
    rows = csv.DictReader(io.StringIO(content), delimiter="\t")
    grouped = defaultdict(list)
    for row in rows:
        if row["level"] != "5" or not row["text"].strip():
            continue
        confidence = float(row["conf"])
        require(math.isfinite(confidence) and -1 <= confidence <= 100, "Invalid OCR confidence value.", "tool_failed")
        left, top, width, height = (int(row[k]) for k in ("left", "top", "width", "height"))
        require(min(left, top, width, height) >= 0, "Invalid OCR word geometry.", "tool_failed")
        require(bounds is None or (left + width <= bounds[0] and top + height <= bounds[1]), "OCR evidence lies outside the captured image.", "tool_failed")
        grouped[(row["block_num"], row["par_num"])].append({"text": row["text"], "confidence": confidence,
            "line": int(row["line_num"]), "bbox_pixels": [left, top, left + width, top + height]})
    result = []
    for (block, number), words in grouped.items():
        lines = defaultdict(list)
        for word in words:
            lines[word["line"]].append(word["text"])
        scores = [w["confidence"] for w in words]
        flags = ["ocr_accuracy_unverified", "ocr_reading_order_unverified"]
        if min(scores) < 80:
            flags.append("ocr_word_below_80")
        result.append(paragraph(document_id, "tesseract_tsv", {"page": page, "block": block,
            "paragraph": number, "artifact": artifact, "image_size_pixels": list(bounds) if bounds else None,
            "paragraph_kind": "ocr_segment_not_semantic_claim"},
            "\n".join(" ".join(line) for line in lines.values()), words=words, flags=flags,
            confidence={"minimum": min(scores), "mean": sum(scores) / len(scores), "scale": "uncalibrated_tesseract_0_100"}))
    return bounded(result)


def recognize(path, work, document_id, page, language):
    artifact = f"ocr-{page}.tsv"
    tool("tesseract", [path, work / f"ocr-{page}", "-l", language, "--psm", "3", "tsv"], work, f"tesseract-{page}")
    result = work / artifact
    require(result.is_file() and result.stat().st_size <= MAX_EXPANDED, "OCR produced no usable bounded TSV artifact.", "tool_failed")
    return ocr_tsv(result.read_text(encoding="utf-8"), document_id, page, artifact, image_size(path))


def extract(path, kind, document_id, work, *, ocr=False, language=None, ocr_all=False):
    require(not ocr_all or ocr, "--ocr-all requires explicit --ocr.", "configuration")
    require(not language or ocr, "OCR language requires explicit --ocr.", "configuration")
    metadata = {"ocr_requested": ocr, "ocr_all": ocr_all, "ocr_language": language,
                "ocr_invocations": 0, "external_uploads": False, "tools": {}}
    if ocr:
        require(isinstance(language, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,20}(?:\+[a-z][a-z0-9_]{1,20})*", language),
                "Supply explicit installed OCR languages, e.g. --ocr-language eng+fra. No language was guessed.", "configuration")
        available = tool("tesseract", ["--list-langs"], work, "tesseract-languages")
        require(set(language.split("+")).issubset(set(available.splitlines())), "Requested OCR language data is unavailable. Install the selected Tesseract language packs locally.", "dependency_unavailable")
        version = tool("tesseract", ["--version"], work, "tesseract-version")
        metadata["tools"]["tesseract"] = version.splitlines()[0] if version.strip() else "unreported; see private version stderr"
    if kind == "docx":
        require(not ocr, "DOCX OCR is not automatic. Export a scanned DOCX to PDF locally, or explicitly transcribe its captured visual placeholders during review.", "unsupported_document")
        paragraphs, pages, issues = docx(path, document_id)
        return paragraphs, pages, issues, metadata
    if kind == "pdf":
        info = tool("pdfinfo", [path], work, "pdfinfo")
        require(not re.search(r"(?mi)^Encrypted:\s*yes", info), "Encrypted PDFs are unsupported. Export an unlocked local copy; do not put passwords in CLI arguments.", "encrypted_document")
        match = re.search(r"(?mi)^Pages:\s*(\d+)", info)
        require(match and 1 <= int(match.group(1)) <= MAX_PAGES, "PDF exceeds the 30-page limit or has no valid page count.", "oversized_document")
        count = int(match.group(1))
        dimensions = tool("pdfinfo", ["-f", "1", "-l", str(count), "-box", path], work, "pdfinfo-boxes")
        sizes = re.findall(r"(?mi)^Page(?:\s+\d+)?\s+size:\s*([\d.]+)\s+x\s+([\d.]+)", dimensions)
        require(len(sizes) == count and all(float(w) > 0 and float(h) > 0 and math.ceil(float(w) * 150 / 72) * math.ceil(float(h) * 150 / 72) <= MAX_PIXELS for w, h in sizes),
                "PDF page geometry exceeds the bounded 150-DPI raster limit.", "oversized_document")
        tool("pdftotext", ["-bbox-layout", "-enc", "UTF-8", path, work / "text.xhtml"], work, "pdftotext")
        text_file = work / "text.xhtml"
        require(text_file.is_file() and text_file.stat().st_size <= MAX_EXPANDED, "PDF text output is missing or oversized.", "oversized_document")
        paragraphs, pages = pdf_blocks(text_file.read_text(encoding="utf-8"), document_id)
        require(len(pages) == count, "PDF extraction did not return every source page.", "tool_failed")
        metadata["tools"]["poppler"] = tool("pdftotext", ["-v"], work, "poppler-version").strip() or (work / "poppler-version.stderr").read_text(encoding="utf-8").splitlines()[0]
        if ocr:
            targets = [p["page"] for p in pages] if ocr_all else sorted({p["locator"]["page"] for p in paragraphs if p["method"] == "manual_transcription_required"})
            for page in targets:
                prefix = work / f"page-{page}"
                tool("pdftoppm", ["-f", str(page), "-l", str(page), "-r", "150", "-singlefile", "-png", path, prefix], work, f"raster-{page}")
                image = prefix.with_suffix(".png")
                image_size(image)
                recognized = recognize(image, work, document_id, page, language)
                metadata["ocr_invocations"] += 1
                if recognized:
                    paragraphs = [p for p in paragraphs if p["locator"]["page"] != page] + recognized
                else:
                    for p in paragraphs:
                        if p["locator"]["page"] == page:
                            p["flags"].append("ocr_returned_no_text")
            paragraphs.sort(key=lambda p: p["locator"]["page"])
        return bounded(paragraphs), pages, [], metadata
    if kind in ("png", "jpeg"):
        width, height = image_size(path)
        pages = [{"page": 1, "width_pixels": width, "height_pixels": height}]
        paragraphs = recognize(path, work, document_id, 1, language) if ocr else []
        metadata["ocr_invocations"] = int(ocr)
        if not paragraphs:
            paragraphs = [paragraph(document_id, "manual_transcription_required", {"page": 1, "artifact": "original.bin"}, "", flags=["image_only_source_requires_explicit_ocr_or_transcription"])]
        return paragraphs, pages, [], metadata
    raise IngestionError("unsupported_document", "Supported inputs: text/scanned PDF, DOCX, PNG and JPEG. Direct LaTeX still uses tex_entry; no import is required. TIFF, HTML and legacy DOC need a local conversion first.")
