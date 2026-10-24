"""Deterministic UTF-8 fixtures with observable units, not human gold labels."""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
LOCALES = json.loads((HERE / "locales.json").read_text(encoding="utf-8"))
LANGUAGES = ("en", "es", "fr", "ar")
PAGES = (1, 3, 8)
FACTS = {"metric": r"40\%", "latency": "250 ms", "budget": "125000",
         "credential": "Certificado Delta", "expiry": "2020", "citation": "Delta2021",
         "oop": "OOP", "ttr": "TTR", "campaign": "Lumière 2030",
         "colleague": "José Núñez", "url": "https://example.invalid/cv", "date": "Sen 2017"}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def inventory(language, pages):
    locale = LOCALES[language]
    units = {"name": {"kind": "CVText", "text": r"Nadia El-Haddad / \textarabic{نور الحداد}",
                      "protected": ["Nadia El-Haddad", "نور الحداد"]}}
    keys = ("profile", "experience", "education", "publication", "skills", "award", "volunteering", "custom")
    for index, key in enumerate(keys):
        units["heading-" + key] = {"kind": "CVHeading", "text": locale["headings"][index], "protected": []}
        values = {name: r"\textenglish{" + value + "}" for name, value in FACTS.items()}
        if key == "custom":
            values["url"] = r"\textenglish{\texttt{" + FACTS["url"] + "}}"
        text = locale[key].format(**values)
        units[key] = {"kind": "CVText", "text": text,
                      "protected": [value for name, value in FACTS.items() if "{" + name + "}" in locale[key]]}
    for page in range(pages):
        # Oldest history is last: a trailing omission cannot hide behind a short first page.
        values = {"employer": "Atelier Boréal " + str(page + 1), "year": str(2016 - page)}
        units[f"history-heading-{page}"] = {"kind": "CVHeading", "text": locale["headings"][8], "protected": []}
        units[f"history-{page}"] = {"kind": "CVText", "text": locale["history"].format(**{
            key: r"\textenglish{" + value + "}" for key, value in values.items()}), "protected": list(values.values())}
        # Substantial included history, rather than padding eight mostly empty pages.
        if page:
            for entry in range(1, 6):
                employer = f"Atelier Boréal {page + 1}-{entry}"
                units[f"history-{page}-detail-{entry}"] = {"kind": "CVText", "text": locale["history"].format(
                    employer=r"\textenglish{" + employer + "}", year=r"\textenglish{" + values["year"] + "}"),
                    "protected": [employer, values["year"]]}
    return units


def materialize(root, language, pages):
    """One page single-file; 3/8 pages use literal nested includes. Refuse reuse."""
    if language not in LANGUAGES or pages not in PAGES:
        raise ValueError("Supported fixture languages en/es/fr/ar; page counts 1/3/8")
    root.mkdir(parents=True, exist_ok=False)
    (root / ".vita").mkdir()
    (root / "sections").mkdir()
    units = inventory(language, pages)
    header = r"""\documentclass[10pt,a4paper]{article}
\usepackage[margin=18mm]{geometry}
\usepackage{fontspec}
\usepackage{polyglossia}
\setmainfont{DejaVu Serif}
\newfontfamily\arabicfont[Script=Arabic]{Amiri}
\newfontfamily\englishfont{DejaVu Serif}
\setdefaultlanguage{MAINLANG}
OTHERLANGS
\newcommand{\CVHeading}[2]{\par\medskip\textbf{#2}\par}
\newcommand{\CVText}[2]{#2\par}
\setlength{\parindent}{0pt}
\begin{document}
""".replace("MAINLANG", LOCALES[language]["language"])
    # All fixtures include an Arabic proper name and explicit LTR protected spans.
    # Set all non-default languages after the main language.
    others = [name for name in ("arabic", "english") if name != LOCALES[language]["language"]]
    header = header.replace("OTHERLANGS", "\n".join(r"\setotherlanguage{" + name + "}" for name in others))
    def render(ids):
        return "\n".join("\\" + units[key]["kind"] + "{" + key + "}{" + units[key]["text"] + "}" for key in ids) + "\n"
    core = [key for key in units if not key.startswith("history")]
    body = render(core)
    for page in range(pages):
        chunk = render([f"history-heading-{page}", f"history-{page}"] +
                       ([f"history-{page}-detail-{entry}" for entry in range(1, 6)] if page else []))
        if page:
            body += "\\newpage\n"
        if pages == 1:
            body += chunk
        else:
            # Includes inside an include test recursive capture, using project-root paths.
            path = f"sections/history-{page}.tex"
            (root / path).write_text(chunk, encoding="utf-8")
            body += "\\input{" + path + "}\n"
    if pages > 1:
        (root / "sections/body.tex").write_text(body, encoding="utf-8")
        body = "\\input{sections/body.tex}\n"
    (root / "main.tex").write_text(header + body + "\\end{document}\n", encoding="utf-8")
    (root / "job.md").write_text("Synthetic data engineer role. Python and reliable data pipelines. No extra credentials required.\n", encoding="utf-8")
    (root / ".vita/config.json").write_text(json.dumps({"tex_entry": "main.tex", "author": "synthetic",
        "latex_engine": "xelatex", "output_dir": "out", "output_filename": "cv.pdf"}), encoding="utf-8")
    manifest = {"schema_version": 1, "origin": LOCALES["origin"], "language": language, "expected_pages": pages,
                "linguistic_review": LOCALES["linguistic_review"], "units": units,
                "sources": {p.relative_to(root).as_posix(): digest(p.read_text(encoding="utf-8")) for p in sorted(root.rglob("*.tex"))}}
    (root / "fixture.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
