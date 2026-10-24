"""Mechanical checks on the versioned synthetic macro contract, not arbitrary TeX.

Unit identities prove coverage of an observable fixture contract, not semantic
equivalence. Draft mismatches require review, not an automatic 'bad translation'.
"""

import collections
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.multilingual.fixtures import digest, inventory


def uncomment(text):
    return re.sub(r"(?m)(?<!\\)%.*$", "", text)


def group(text, start):
    if start >= len(text) or text[start] != "{":
        raise ValueError("Expected balanced macro argument")
    depth, index = 1, start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "{":
            depth += 1
        if text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
        index += 1
    raise ValueError("Unbalanced macro argument / possible truncation")


def capture(root, entry="main.tex"):
    """Literal local includes only; missing/dynamic/outside paths are explicit errors."""
    root = root.resolve()
    files, active = {}, set()

    def visit(path):
        path = path.resolve()
        if not path.is_relative_to(root) or path in active:
            raise ValueError("Outside-project or cyclic include")
        if not path.is_file():
            raise ValueError("Missing included source: " + str(path.relative_to(root)))
        relative = path.relative_to(root).as_posix()
        if relative in files:
            raise ValueError("Repeated include would duplicate fixture units")
        content = uncomment(path.read_text(encoding="utf-8"))
        files[relative] = content
        active.add(path)
        def expand(match):
            name = match.group(1)
            if "\\" in name or "#" in name:
                raise ValueError("Dynamic includes require manual review")
            included = Path(name)
            return visit(root / (included if included.suffix else included.with_suffix(".tex")))
        expanded = re.sub(r"\\(?:input|include)\s*\{([^{}]+)\}", expand, content)
        active.remove(path)
        return expanded
    return visit(root / entry), files


def normalized(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def units(text):
    result, spans, duplicates = {}, [], []
    for match in re.finditer(r"\\(CVHeading|CVText)\s*(?=\{)", text):
        key, end = group(text, match.end())
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
        value, end = group(text, start)
        if key in result:
            duplicates.append(key)
        result[key] = {"kind": match.group(1), "text": value}
        spans.append((match.start(), end))
    return result, spans, duplicates


def structural(source, output_root, target_language):
    expected = inventory(target_language, source["expected_pages"])
    result = {"status": "failed", "linguistic_review": "unavailable", "semantic_translation_quality": None,
              "rtl_reading_order": "unreviewed", "missing_units": [], "unexpected_units": [],
              "changed_protected_facts": [], "numeric_changes": [], "untranslated_source_units": [],
              "draft_mismatches": [], "truncation_suspected": False, "errors": []}
    try:
        text, files = capture(output_root)
        # Inspect the document body, not macro definitions or commented-out history.
        if text.count(r"\begin{document}") != 1 or text.count(r"\end{document}") != 1:
            result["truncation_suspected"] = True
            raise ValueError("Missing/duplicate document boundary: possible truncation")
        for declaration in (r"\newcommand{\CVHeading}[2]{\par\medskip\textbf{#2}\par}",
                            r"\newcommand{\CVText}[2]{#2\par}"):
            if declaration not in text:
                result["errors"].append("Fixture rendering macro changed; unit visibility is unverified")
        body = text.split(r"\begin{document}", 1)[1].split(r"\end{document}", 1)[0]
        found, spans, duplicates = units(body)
        result["source_hashes"] = {name: digest(value) for name, value in files.items()}
        result["missing_units"] = sorted(set(expected) - set(found))
        result["unexpected_units"] = sorted(set(found) - set(expected))
        result["duplicate_units"] = duplicates
        for key, reference in expected.items():
            if key not in found:
                continue
            text_value = normalized(found[key]["text"])
            if found[key]["kind"] != reference["kind"]:
                result["errors"].append("Changed unit kind: " + key)
            if text_value != normalized(reference["text"]):
                result["draft_mismatches"].append(key)
            original = source["units"][key]
            if target_language != source["language"] and normalized(original["text"]) != normalized(reference["text"]) and text_value == normalized(original["text"]):
                result["untranslated_source_units"].append(key)
            for fact in original["protected"]:
                if normalized(fact) not in text_value:
                    result["changed_protected_facts"].append({"unit_id": key, "fact": fact})
            def numbers(value):
                return collections.Counter(re.findall(r"\d+(?:[.,]\d+)?", value))
            if numbers(text_value) != numbers(normalized(original["text"])):
                result["numeric_changes"].append(key)
        for start, end in reversed(spans):
            body = body[:start] + body[end:]
        body = re.sub(r"\\(?:newpage|clearpage)\b", "", body).strip()
        # Arbitrary content outside the anchor contract is never silently accepted.
        if body:
            result["errors"].append("Unanchored output content requires review (possible unsupported addition)")
        if result["missing_units"] or result["unexpected_units"] or duplicates or result["changed_protected_facts"] or result["numeric_changes"] or result["untranslated_source_units"] or result["errors"]:
            result["status"] = "failed"
        elif result["draft_mismatches"]:
            result["status"] = "review_required"
        else:
            result["status"] = "mechanical_checks_passed"
    except (ValueError, OSError, UnicodeError) as exc:
        if "Unbalanced" in str(exc):
            result["truncation_suspected"] = True
        result["errors"].append(str(exc))
    return result


def layout(log_text, bbox_text, expected_pages):
    """Bounding-box/TeX alarms are partial layout checks; no RTL/visual certification."""
    errors = []
    if re.search(r"Overfull \\[hv]box|Missing character:", log_text):
        errors.append("overfull_box_or_missing_glyph")
    try:
        document = ET.fromstring(bbox_text)
        pages = document.findall(".//{*}page")
        if len(pages) != expected_pages:
            errors.append("unexpected_page_count")
        for page in pages:
            width, height = float(page.attrib["width"]), float(page.attrib["height"])
            words = page.findall(".//{*}word")
            if not words:
                errors.append("empty_page")
            for word in words:
                x0, y0, x1, y1 = (float(word.attrib[key]) for key in ("xMin", "yMin", "xMax", "yMax"))
                if not (0 <= x0 <= x1 <= width and 0 <= y0 <= y1 <= height):
                    errors.append("text_outside_page")
    except (ValueError, ET.ParseError, KeyError):
        errors.append("unreadable_pdf_geometry")
    return {"status": "alarms_detected" if errors else "mechanical_checks_passed", "errors": sorted(set(errors)),
            "visual_review": "unavailable", "rtl_reading_order": "unreviewed"}
