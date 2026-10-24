"""Local synthetic integration checks. No real CVs, providers or actual human reviews.

Requires the synthetic PDF corpus produced by scripts.multilingual. Explicitly
simulated attestations test only the software gate; they are not human evidence.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

from vita.commands import build
from vita.ingestion import pipeline, render
from vita.ingestion.contracts import IngestionError, sha

TEXTS = {"en": "Synthetic engineer at Atelier Boréal. Sen 2017; TTR undefined; 40% reduction; 250 ms; 125000, currency unspecified. Certificado Delta expired 2020; master's coursework in progress, degree not awarded.",
         "es": "Ingeniera en Atelier Boréal. Sen 2017; TTR no definido; reducción del 40%; 250 ms; 125000, moneda no especificada. Certificado Delta caducado en 2020; máster en curso, título no obtenido.",
         "fr": "Ingénieure chez Atelier Boréal. Sen 2017; TTR non défini; réduction de 40%; 250 ms; 125000, devise non précisée. Certificado Delta expiré en 2020; master en cours, diplôme non obtenu.",
         "ar": "نور الحداد لدى Atelier Boréal. Sen 2017؛ اختصار TTR غير معرّف؛ خفض بنسبة 40%؛ 250 ms؛ 125000 بعملة غير محددة. Certificado Delta انتهت صلاحيتها في 2020؛ الماجستير قيد الإنجاز ولم تمنح الدرجة."}


@contextlib.contextmanager
def cwd(path):
    old = Path.cwd()
    path.mkdir(parents=True, exist_ok=False)
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def run_tool(argv, root):
    result = subprocess.run(list(map(str, argv)), cwd=root, capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError("Synthetic fixture tool failed: " + str(argv[0]))
    return result.stdout


def pdf(path, contents, image=None):
    """Minimal synthetic PDF, with explicit text positions or a raster-only page."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    page_ids = []
    for content in contents:
        page_id, stream_id = len(objects) + 1, len(objects) + 2
        page_ids.append(page_id)
        resources = b"/Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >>"
        if image:
            width, height, pixels = image
            image_id = stream_id + 1
            resources += f" /XObject << /Im1 {image_id} 0 R >>".encode()
            content = b"q 550 0 0 750 25 25 cm /Im1 Do Q"
        objects.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << ".encode() + resources + f" >> /Contents {stream_id} 0 R >>".encode())
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        if image:
            compressed = zlib.compress(pixels)
            objects.append(f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(compressed)} >>\nstream\n".encode() + compressed + b"\nendstream")
    objects[1] = ("<< /Type /Pages /Count " + str(len(page_ids)) + " /Kids [" + " ".join(f"{i} 0 R" for i in page_ids) + "] >>").encode()
    data, offsets = b"%PDF-1.4\n", [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    offset = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{position:010d} 00000 n \n".encode() for position in offsets[1:])
    data += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{offset}\n%%EOF\n".encode()
    path.write_bytes(data)


def ppm(path):
    with path.open("rb") as handle:
        def token():
            value = b""
            while True:
                byte = handle.read(1)
                if byte == b"#":
                    handle.readline()
                elif byte.isspace():
                    if value:
                        return value
                elif not byte:
                    raise ValueError("Truncated synthetic raster")
                else:
                    value += byte
        assert token() == b"P6"
        width, height, maximum = int(token()), int(token()), int(token())
        assert maximum == 255
        pixels = handle.read()
        assert len(pixels) == width * height * 3
    return width, height, pixels


def docx(path, text):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        package.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')


def simulate_gate(extracted, language):
    """Synthetic software-gate test, never an actual source/language reviewer."""
    plan = Path(".vita/ingestion/simulated-review.json")
    form = pipeline.review_template(extracted["revision"], plan)
    form.update(reviewer="SYNTHETIC-CI-ATTESTATION-NOT-HUMAN-EVIDENCE", original_viewed=True, reading_order_checked=True)
    for paragraph in form["paragraphs"]:
        paragraph.update(decision="keep", approved_text=paragraph["original_text"], source_checked=True,
                         association="preserve_unassigned", rationale="Synthetic conformance fixture only: test a source-checked keep without inferred associations.")
    plan.write_text(json.dumps(form, ensure_ascii=False), encoding="utf-8")
    approved = pipeline.approve(extracted["revision"], plan)
    exported = render.generate(approved["revision"], "imported.tex", language)
    Path(".vita/config.json").write_text(json.dumps({"tex_entry": "imported.tex", "latex_engine": "xelatex", "output_dir": "out", "output_filename": "imported.pdf"}), encoding="utf-8")
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        compiled = build.run()
    Path("compile.txt").write_text(stream.getvalue(), encoding="utf-8")
    assert compiled
    run_tool(["pdftoppm", "-scale-to", "1200", "-png", "out/imported.pdf", "out/page"], Path.cwd())
    assert list(Path("out").glob("page-*.png"))
    assert exported["stages"]["compile"] == "not_run"  # Build is separate from ingestion.
    return {"export_revision": exported["revision"], "compile_test": "passed", "human_review": "simulated_software_test_only"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output, corpus = args.output.resolve(), args.pdf_corpus.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = output / "synthetic-sources"
    sources.mkdir()
    required = ("pdfinfo", "pdftotext", "pdftoppm", "tesseract", "qpdf", "latexmk", "xelatex")
    missing = [tool for tool in required if shutil.which(tool) is None]
    if missing:
        (output / "report.json").write_text(json.dumps({"status": "unavailable", "missing_tools": missing, "human_review": "unavailable", "ocr_accuracy": None}), encoding="utf-8")
        print("Missing explicit integration tools: " + ", ".join(missing))
        return 1
    rows = []
    for language in TEXTS:
        path = sources / (language + ".docx")
        docx(path, TEXTS[language])
        with cwd(output / ("docx-" + language)):
            captured = pipeline.capture(path)
            extracted = pipeline.extract(captured["id"])
            assert extracted["state"] == "review_required" and extracted["paragraphs"][0]["text"] == TEXTS[language]
            converted = simulate_gate(extracted, language)
            rows.append({"case": "docx-" + language, "status": "passed", "source_sha256": captured["sha256"], **converted})
    for language in TEXTS:
        source = corpus / ("en-" + language + "-1/draft/out/cv.pdf")
        with cwd(output / ("text-pdf-" + language)):
            captured = pipeline.capture(source)
            extracted = pipeline.extract(captured["id"])
            assert extracted["state"] == "review_required" and len(extracted["pages"]) == 1
            assert extracted["usage"]["ocr_invocations"] == 0
            metric = any("40%" in p["text"] for p in extracted["paragraphs"])
            assert metric or language == "ar"  # RTL extraction order needs independent review.
            assert all(p["locator"]["page"] == 1 for p in extracted["paragraphs"])
            rows.append({"case": "text-pdf-" + language, "status": "passed", "paragraphs": len(extracted["paragraphs"]),
                         "exact_metric_marker_present": metric, "semantic_fidelity": None, "review": "pending", "usage": extracted["usage"]})
    columns = sources / "columns.pdf"
    pdf(columns, [b"BT /F1 12 Tf 30 740 Td (Employer A) Tj 0 -20 Td (Engineer) Tj 330 20 Td (2017-2020) Tj 0 -20 Td (40% reduction) Tj ET"])
    with cwd(output / "columns"):
        extracted = pipeline.extract(pipeline.capture(columns)["id"])
        assert extracted["state"] == "review_required"
        assert any("possible_columns_or_role_date_fragmentation" in p["flags"] for p in extracted["paragraphs"])
        rows.append({"case": "two-columns", "status": "passed", "associations": "unverified", **simulate_gate(extracted, "en")})
    long_pdf = corpus / "en-en-8/draft/out/cv.pdf"
    with cwd(output / "long-pdf"):
        extracted = pipeline.extract(pipeline.capture(long_pdf)["id"])
        assert extracted["state"] == "review_required" and len(extracted["pages"]) == 8
        assert any("2009" in p["text"] for p in extracted["paragraphs"] if p["locator"]["page"] == 8)
        rows.append({"case": "eight-page-history", "status": "passed", "pages": 8, "review": "pending"})
    # Rasterize known synthetic source pages, never a real-person document.
    for language, ocr_language in (("en", "eng"), ("es", "spa"), ("fr", "fra"), ("ar", "ara")):
        source = corpus / ("en-" + language + "-1/draft/out/cv.pdf")
        run_tool(["pdftoppm", "-singlefile", "-r", "120", source, sources / language], sources)
        raster = ppm(sources / (language + ".ppm"))
        scan = sources / (language + "-scan.pdf")
        pdf(scan, [b""], raster)
        with cwd(output / ("scan-" + language)):
            captured = pipeline.capture(scan)
            pending = pipeline.extract(captured["id"])
            assert pending["stages"]["extract"] == "partial" and pending["usage"]["ocr_invocations"] == 0
            extracted = pipeline.extract(captured["id"], ocr=True, language=ocr_language)
            assert extracted["state"] == "review_required" and extracted["usage"]["ocr_invocations"] == 1
            assert any(p["method"] == "tesseract_tsv" for p in extracted["paragraphs"])
            assert extracted["stages"]["review"] == "not_started" and sha(scan.read_bytes()) == captured["sha256"]
            plan = Path(".vita/ingestion/pending.json")
            pipeline.review_template(extracted["revision"], plan)
            try:
                pipeline.approve(extracted["revision"], plan)
            except IngestionError:
                pass
            else:
                raise AssertionError("Unreviewed OCR reached approval")
            rows.append({"case": "scanned-pdf-" + language, "status": "passed", "usage": extracted["usage"], "review": "pending", "ocr_accuracy": None})
    encrypted = sources / "encrypted.pdf"
    run_tool(["qpdf", "--encrypt", "synthetic-user", "synthetic-owner", "256", "--", columns, encrypted], sources)
    corrupt = sources / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4\ncorrupt fixture\n")
    oversized = sources / "31-pages.pdf"
    pdf(oversized, [b"BT /F1 12 Tf 30 740 Td (History retained) Tj ET"] * 31)
    for case, path in (("encrypted", encrypted), ("corrupt", corrupt), ("page-limit", oversized)):
        with cwd(output / case):
            extracted = pipeline.extract(pipeline.capture(path)["id"])
            assert extracted["state"] == "blocked" and not extracted["paragraphs"]
            assert not list(Path.cwd().glob("*.tex"))
            rows.append({"case": case, "status": "passed", "expected_block": extracted["error"]})
    report = {"contract_version": "ingestion-smoke/1", "status": "passed", "cases": rows,
              "human_review": "unavailable; named attestations are synthetic software tests, not humans",
              "linguistic_review": "unavailable", "ocr_accuracy": None, "rtl_reading_order": "unreviewed",
              "original_layout_replication": False, "external_uploads_by_ingestion": False,
              "claims": {"ats_validated": False, "hiring_outcomes_validated": False}}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(len(rows)) + " synthetic ingestion integration cases passed; human source/OCR review remains unavailable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
