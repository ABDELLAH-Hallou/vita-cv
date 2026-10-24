"""Synthetic ingestion controls; human attestations below are test simulations only."""

import json
import struct
import subprocess
import sys
import zipfile
import zlib
from unittest.mock import Mock

import pytest

from vita.__main__ import main
from vita.ingestion import extractors, pipeline, render
from vita.ingestion.contracts import (
    MAX_INPUT,
    IngestionError,
    read,
    sha,
    store,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx_file(path, paragraphs=None, body=None, parts=None):
    if body is None:
        from xml.sax.saxutils import escape
        body = "".join('<w:p><w:r><w:t xml:space="preserve">' + escape(text) + '</w:t></w:r></w:p>' for text in (paragraphs or ["Synthetic CV", "Data engineer / Atelier Boréal", "Sen 2017; 40% reduction; 250 ms; 125000 currency unspecified."]))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
        for name, content in (parts or {}).items():
            archive.writestr(name, content)
    return path


def png_file(path, width=12, height=12):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\xff\xff" * min(width, 12)) * min(height, 12))) + chunk(b"IEND", b"")
    path.write_bytes(data)
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def extracted_project(project, paragraphs=None):
    source = docx_file(project / "source.docx", paragraphs)
    captured = pipeline.capture(source)
    result = pipeline.extract(captured["id"])
    assert result["state"] == "review_required", result
    return source, captured, result


def simulated_review(project, result):
    """Software fixture, never a real qualified reviewer or actual human evidence."""
    path = project / "review.json"
    form = pipeline.review_template(result["revision"], path)
    form.update(reviewer="synthetic-test-attestation", original_viewed=True, reading_order_checked=True)
    for paragraph in form["paragraphs"]:
        paragraph.update(decision="keep", approved_text=paragraph["original_text"], source_checked=True,
                         association="preserve_unassigned", rationale="Synthetic test: inspect source and preserve ambiguity.")
    for issue in form["issue_resolutions"]:
        form["issue_resolutions"][issue] = "Synthetic test: explicitly inspected original and recorded the limitation."
    path.write_text(json.dumps(form, ensure_ascii=False), encoding="utf-8")
    return path, form


def save_form(path, form):
    path.write_text(json.dumps(form, ensure_ascii=False), encoding="utf-8")


def bbox(pages=1, columns=False, empty=False):
    blocks = '' if empty else '<block xMin="10" yMin="10" xMax="200" yMax="30"><line><word xMin="10" yMin="10" xMax="60" yMax="25">Engineer</word><word xMin="65" yMin="10" xMax="120" yMax="25">40%</word></line></block>'
    if columns:
        blocks += '<block xMin="350" yMin="10" xMax="450" yMax="30"><line><word xMin="350" yMin="10" xMax="450" yMax="25">2017–2020</word></line></block>'
    return '<html><doc>' + ''.join('<page width="600" height="800">' + blocks + '</page>' for _ in range(pages)) + '</doc></html>'


def test_capture_preserves_bytes_is_idempotent_and_never_activates_tex(project):
    source = docx_file(project / "CV.docx")
    original = source.read_bytes()
    captured = pipeline.capture(source)
    assert captured["id"] == "doc-" + sha(original)
    assert (store() / "documents" / captured["id"] / "original.bin").read_bytes() == original
    assert source.read_bytes() == original
    assert pipeline.capture(source) == captured
    assert captured["stages"]["extract"] == "not_started"
    assert (store() / ".gitignore").read_text() == "*\n"
    assert not (project / "main.tex").exists()


@pytest.mark.parametrize("size", [0, MAX_INPUT + 1])
def test_empty_and_oversized_inputs_do_not_complete_capture(project, size):
    source = project / "large.pdf"
    with source.open("wb") as file:
        file.truncate(size)
    with pytest.raises(IngestionError, match="20-MiB"):
        pipeline.capture(source)
    assert not list((store() / "documents").glob("*"))


@pytest.mark.parametrize("source_language", ["English 40%", "Español: formación José Núñez", "Français: diplôme expiré, 250 ms", "العربية نور الحداد 40%"])
def test_docx_wording_and_metrics_are_not_rewritten(project, source_language):
    source, captured, result = extracted_project(project, [source_language])
    assert result["paragraphs"][0]["text"] == source_language
    locator = result["paragraphs"][0]["locator"]
    assert locator["part"] == "word/document.xml" and locator["paragraph"] == 1
    assert locator["page"] is None
    assert "not_rendered" in locator["page_hint_status"]
    assert result["paragraphs"][0]["confidence"] is None
    assert result["stages"]["review"] == "not_started"
    assert sha(source.read_bytes()) == captured["sha256"]


def test_docx_tables_headers_links_changes_and_images_remain_reviewable(project):
    body = '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Employer A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>2017–2020</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    body += '<w:p><w:r><w:t>Credential </w:t></w:r><w:del><w:r><w:delText>expired</w:delText></w:r></w:del></w:p>'
    body += '<w:p><w:r><w:drawing/></w:r></w:p>'
    parts = {"word/header1.xml": f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>Private contact</w:t></w:r></w:p></w:hdr>',
             "word/_rels/document.xml.rels": '<Relationships><Relationship Id="rId1" TargetMode="External" Target="https://example.invalid/cv"/></Relationships>'}
    source = docx_file(project / "table.docx", body=body, parts=parts)
    result = pipeline.extract(pipeline.capture(source)["id"])
    texts = [p["text"] for p in result["paragraphs"]]
    assert "Employer A" in texts and "2017–2020" in texts
    assert "Private contact" in texts and "https://example.invalid/cv" in texts
    assert "Credential expired" in texts
    assert any("tracked_changes_unresolved" in p["flags"] for p in result["paragraphs"])
    assert any("table_cell_association_unverified" in p["flags"] for p in result["paragraphs"])
    assert any(p["method"] == "manual_transcription_required" for p in result["paragraphs"])
    assert result["stages"]["extract"] == "partial"


def test_columns_keep_independent_role_date_fragments_and_page_boxes():
    paragraphs, pages = extractors.pdf_blocks(bbox(2, columns=True), "doc-fixture")
    assert len(pages) == 2 and len(paragraphs) == 4
    assert paragraphs[0]["text"] == "Engineer 40%"
    assert paragraphs[1]["text"] == "2017–2020"
    assert all("possible_columns_or_role_date_fragmentation" in p["flags"] for p in paragraphs)
    assert paragraphs[-1]["locator"]["page"] == 2
    assert paragraphs[0]["words"][1]["text"] == "40%"


def test_empty_pdf_pages_are_not_empty_candidate_facts():
    paragraphs, pages = extractors.pdf_blocks(bbox(empty=True), "doc-fixture")
    assert pages and paragraphs[0]["method"] == "manual_transcription_required"
    assert paragraphs[0]["text"] == ""


@pytest.mark.parametrize("data", [b"not a zip", b"\xd0\xcf\x11\xe0 Office encrypted"])
def test_corrupt_or_encrypted_docx_is_blocked_without_tex(project, data):
    path = project / "bad.docx"
    path.write_bytes(data)
    result = pipeline.extract(pipeline.capture(path)["id"])
    assert result["state"] == "blocked"
    assert result["stages"]["extract"] == "blocked"
    assert result["paragraphs"] == []
    with pytest.raises(IngestionError):
        pipeline.review_template(result["revision"], project / "form.json")
    assert not list(project.glob("*.tex"))


@pytest.mark.parametrize("fault", ["entity", "oversized_zip", "unsupported_zip", "macro"])
def test_unsupported_docx_containers_fail_explicitly(project, fault):
    path = project / "bad.docx"
    if fault == "entity":
        docx_file(path, parts={"word/header1.xml": '<!DOCTYPE x [<!ENTITY e SYSTEM "https://example.invalid">]><x/>'})
    elif fault == "oversized_zip":
        docx_file(path, parts={"huge.txt": "x" * 1_000_000})
    elif fault == "macro":
        docx_file(path, parts={"word/vbaProject.bin": "not executed"})
    else:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("unrelated.txt", "not Word")
    result = pipeline.extract(pipeline.capture(path)["id"])
    assert result["state"] == "blocked" and result["error"]["category"]


def test_explicit_ocr_language_and_low_confidence_source_provenance():
    content = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    content += '5\t1\t2\t3\t1\t1\t10\t20\t30\t15\t42.5\t40%\n'
    content += '5\t1\t2\t3\t1\t2\t45\t20\t30\t15\t93\tJosé\n'
    result = extractors.ocr_tsv(content, "doc-fixture", 4, "ocr-4.tsv")
    assert result[0]["text"] == "40% José"
    assert result[0]["locator"]["page"] == 4
    assert result[0]["words"][0]["bbox_pixels"] == [10, 20, 40, 35]
    assert result[0]["confidence"]["minimum"] == 42.5
    assert "ocr_word_below_80" in result[0]["flags"]
    assert "ocr_accuracy_unverified" in result[0]["flags"]


def test_image_only_requires_explicit_ocr_or_human_transcription(project, monkeypatch):
    path = png_file(project / "scan.png")
    backend = Mock(side_effect=AssertionError("OCR must be explicit"))
    monkeypatch.setattr(extractors, "recognize", backend)
    result = pipeline.extract(pipeline.capture(path)["id"])
    backend.assert_not_called()
    assert result["state"] == "review_required" and result["stages"]["extract"] == "partial"
    form_path, form = simulated_review(project, result)
    with pytest.raises(IngestionError, match="empty image"):
        pipeline.approve(result["revision"], form_path)
    form["paragraphs"][0].update(decision="correct", approved_text="40% reduction; Sen 2017; TTR undefined.",
        manual_transcription=True, factual_change_confirmed=True)
    save_form(form_path, form)
    approved = pipeline.approve(result["revision"], form_path)
    converted = render.generate(approved["revision"], project / "imported.tex", "en")
    assert converted["stages"]["extract"] == "partial"  # Manual review does not falsify extractor completion.
    assert converted["stages"]["latex"] == "generated"
    assert converted["stages"]["compile"] == "not_run"


@pytest.mark.parametrize("options", [{"ocr": True}, {"language": "eng"}, {"ocr_all": True}])
def test_ocr_never_guesses_language_or_activates_implicitly(project, options):
    result = pipeline.extract(pipeline.capture(png_file(project / "scan.png"))["id"], **options)
    assert result["state"] == "blocked" and result["error"]["category"] == "configuration"


def test_missing_ocr_dependency_does_not_upload_or_create_candidate_facts(project, monkeypatch):
    captured = pipeline.capture(png_file(project / "scan.png"))
    monkeypatch.setattr(extractors.shutil, "which", lambda _: None)
    result = pipeline.extract(captured["id"], ocr=True, language="eng")
    assert result["state"] == "blocked" and result["error"]["category"] == "dependency_unavailable"
    assert result["usage"]["ocr_invocations"] == 0 and result["usage"]["external_uploads"] is False


@pytest.mark.parametrize("fault", ["too_many_pixels", "truncated_png", "bad_crc", "truncated_jpeg"])
def test_oversized_or_corrupt_images_fail_without_shortening(project, fault):
    path = png_file(project / "scan.png", 6000 if fault == "too_many_pixels" else 12, 6000 if fault == "too_many_pixels" else 12)
    if fault == "truncated_png":
        path.write_bytes(path.read_bytes()[:30])
    elif fault == "bad_crc":
        path.write_bytes(path.read_bytes()[:-1] + b"x")
    elif fault == "truncated_jpeg":
        path = project / "scan.jpg"
        path.write_bytes(b"\xff\xd8" + b"x" * 30)
    result = pipeline.extract(pipeline.capture(path)["id"])
    assert result["state"] == "blocked" and result["paragraphs"] == []


def test_blank_review_and_unapproved_extraction_cannot_generate_latex(project):
    _, _, result = extracted_project(project)
    path = project / "blank.json"
    form = pipeline.review_template(result["revision"], path)
    assert form["reviewer"] is None and form["original_viewed"] is False
    assert all(p["decision"] == "pending" for p in form["paragraphs"])
    with pytest.raises(IngestionError):
        pipeline.approve(result["revision"], path)
    with pytest.raises(IngestionError):
        render.generate(result["revision"], project / "main.tex", "en")
    assert not (project / "main.tex").exists()


@pytest.mark.parametrize("fault", ["source_unchecked", "association_unresolved", "source_text_changed", "source_ref_changed",
                                   "missing_paragraph", "duplicate_order", "uncorrected_metric", "omission_without_reason", "empty_document"])
def test_review_contract_rejects_unresolved_or_unsupported_decisions(project, fault):
    _, _, result = extracted_project(project)
    path, form = simulated_review(project, result)
    item = form["paragraphs"][0]
    if fault == "source_unchecked":
        item["source_checked"] = False
    elif fault == "association_unresolved":
        item["association"] = None
    elif fault == "source_text_changed":
        item["original_text"] = "Fictional Employer"
    elif fault == "source_ref_changed":
        item["source_ref"]["paragraph"] = 99999
    elif fault == "missing_paragraph":
        form["paragraphs"].pop()
    elif fault == "duplicate_order":
        form["order"][-1] = form["order"][0]
    elif fault == "uncorrected_metric":
        item.update(decision="correct", approved_text="90% reduction")
    elif fault == "omission_without_reason":
        item.update(decision="omit", approved_text=None, rationale="")
    else:
        for p in form["paragraphs"]:
            p.update(decision="omit", approved_text=None)
    save_form(path, form)
    with pytest.raises(IngestionError):
        pipeline.approve(result["revision"], path)
    assert not list(project.glob("*.tex"))


def test_confirmed_corrections_associations_and_omissions_have_conversion_records(project):
    _, _, result = extracted_project(project)
    path, form = simulated_review(project, result)
    form["paragraphs"][0].update(decision="correct", approved_text="Source-checked title", factual_change_confirmed=True)
    form["paragraphs"][1]["association"] = "group:role-1"
    form["paragraphs"][2].update(decision="omit", approved_text=None, rationale="Synthetic explicit omission after source review.")
    form["order"].reverse()
    save_form(path, form)
    approved = pipeline.approve(result["revision"], path)
    output = render.generate(approved["revision"], project / "editable.tex", "en")
    assert len(output["source_map"]) == 2 and len(output["changes"]) == 3
    assert output["changes"][0]["decision"] == "omit"
    assert any(c["association"] == "group:role-1" for c in output["changes"])
    assert output["original_layout_replication"] is False
    assert output["stages"]["compile"] == "not_run"
    assert "Source-checked title" in (project / "editable.tex").read_text(encoding="utf-8")


@pytest.mark.parametrize("tamper", ["original", "extraction_record", "raw_artifact"])
def test_stale_sources_and_artifacts_invalidate_reviews(project, monkeypatch, tamper):
    if tamper == "raw_artifact":
        original = extractors.extract
        def with_artifact(*args, **kwargs):
            result = original(*args, **kwargs)
            (args[3] / "fixture.raw").write_text("Exact synthetic raw bytes", encoding="utf-8")
            return result
        monkeypatch.setattr(extractors, "extract", with_artifact)
    _, captured, result = extracted_project(project)
    path, _ = simulated_review(project, result)
    if tamper == "original":
        (store() / "documents" / captured["id"] / "original.bin").write_bytes(b"changed")
    elif tamper == "extraction_record":
        record_path = store() / "extractions" / result["revision"] / "record.json"
        doc = read(record_path)
        doc["paragraphs"][0]["text"] = "invented"
        record_path.write_text(json.dumps(doc), encoding="utf-8")
    else:
        (store() / "extractions" / result["revision"] / "fixture.raw").write_text("changed raw bytes", encoding="utf-8")
    with pytest.raises((IngestionError, ValueError)):
        pipeline.approve(result["revision"], path)


@pytest.mark.parametrize("text,language", [("José Núñez; 40% & 250 ms; TTR; Sen 2017", "es"),
                                          ("Diplôme expiré; devise non précisée", "fr"),
                                          ("نور الحداد / Nadia El-Haddad 40%", "ar")])
def test_rendering_escapes_facts_without_translation_or_latex_execution(project, text, language):
    _, _, result = extracted_project(project, [text, r"\input{private} $ # { } _ ^ ~"])
    path, _ = simulated_review(project, result)
    approved = pipeline.approve(result["revision"], path)
    converted = render.generate(approved["revision"], project / "imported.tex", language)
    latex = (project / "imported.tex").read_text(encoding="utf-8")
    assert r"\textbackslash{}input\{private\}" in latex
    assert converted["translation"] == "not_performed" and converted["latex_engine"] == "xelatex"
    assert converted["generated_file_status"] == "unchanged"
    if language == "ar":
        assert r"\textenglish{" in latex and "Nadia El-Haddad" in latex
    for mapping in converted["source_map"]:
        assert mapping["source_ref"]["part"] == "word/document.xml"
    (project / "imported.tex").write_text("User edited the editable file", encoding="utf-8")
    assert render.show("exports", converted["revision"])["generated_file_status"] == "edited_source_map_no_longer_exact"


def test_conversion_cannot_overwrite_direct_latex_or_incomplete_persistence(project, monkeypatch):
    _, _, result = extracted_project(project)
    path, _ = simulated_review(project, result)
    approved = pipeline.approve(result["revision"], path)
    existing = project / "main.tex"
    existing.write_text("Original direct-LaTeX CV", encoding="utf-8")
    with pytest.raises(IngestionError):
        render.generate(approved["revision"], existing, "en")
    assert existing.read_text() == "Original direct-LaTeX CV"
    monkeypatch.setattr(render.os, "link", Mock(side_effect=OSError("simulated publication failure")))
    with pytest.raises(OSError):
        render.generate(approved["revision"], project / "new.tex", "en")
    prepared = next((store() / "exports").iterdir())
    assert read(prepared / "record.json")["stages"]["latex"] == "prepared"
    assert not (project / "new.tex").exists()


def test_unsupported_font_script_does_not_drop_characters_or_generate_partial_cv(project):
    _, _, result = extracted_project(project, ["中文资格 40%"])
    path, _ = simulated_review(project, result)
    approved = pipeline.approve(result["revision"], path)
    with pytest.raises(IngestionError, match="CJK"):
        render.generate(approved["revision"], project / "new.tex", "en")
    assert not (project / "new.tex").exists()


def test_cli_stages_and_nonzero_pending_review(project, monkeypatch, capsys):
    source = docx_file(project / "cv.docx")
    monkeypatch.setattr(sys, "argv", ["vita", "ingest", "capture", str(source), "--json"])
    main()
    captured = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(sys, "argv", ["vita", "ingest", "extract", captured["id"], "--json"])
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["stages"]["review"] == "not_started"
    monkeypatch.setattr(sys, "argv", ["vita", "ingest", "review", result["revision"], "--output", "blank.json"])
    main()
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["vita", "ingest", "approve", result["revision"], "--review", "blank.json", "--json"])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_duplicate_json_and_path_escape_are_not_reviewed_facts(project):
    _, _, result = extracted_project(project)
    outside = project.parent / "outside-review.json"
    with pytest.raises(IngestionError):
        pipeline.review_template(result["revision"], outside)
    path = project / "duplicate.json"
    path.write_text('{"reviewer":"one","reviewer":"two"}', encoding="utf-8")
    with pytest.raises(IngestionError, match="Duplicate"):
        pipeline.approve(result["revision"], path)


@pytest.mark.parametrize("fault,category", [("encrypted", "encrypted_document"), ("pages", "oversized_document"),
                                          ("geometry", "oversized_document"), ("missing_page", "tool_failed")])
def test_pdf_limits_and_encryption_are_explicit_before_candidate_facts(project, monkeypatch, fault, category):
    source = project / "source.pdf"
    source.write_bytes(b"%PDF-1.4\nSynthetic tool-fixture input\n")
    def fake_tool(name, args, work, label):
        if label == "pdfinfo":
            return "Pages: " + ("31" if fault == "pages" else "2") + "\nEncrypted: " + ("yes" if fault == "encrypted" else "no")
        if label == "pdfinfo-boxes":
            return "Page 1 size: " + ("99999 x 99999" if fault == "geometry" else "600 x 800") + "\nPage 2 size: 600 x 800\n"
        if label == "pdftotext":
            (work / "text.xhtml").write_text(bbox(1), encoding="utf-8")
            return ""
        return "synthetic version"
    monkeypatch.setattr(extractors, "tool", fake_tool)
    result = pipeline.extract(pipeline.capture(source)["id"])
    assert result["state"] == "blocked" and result["paragraphs"] == []
    assert result["error"]["category"] == category


def test_ocr_usage_is_explicit_and_low_confidence_requires_review(project, monkeypatch):
    source = png_file(project / "scan.png", 100, 100)
    calls = []
    def fake_tool(name, args, work, label):
        calls.append((name, list(map(str, args))))
        if label == "tesseract-languages":
            return "List of available languages:\neng\nfra\n"
        if label == "tesseract-version":
            return "tesseract fixture-version"
        (work / "ocr-1.tsv").write_text('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t10\t20\t20\t15\t4O%\n', encoding="utf-8")
        return ""
    monkeypatch.setattr(extractors, "tool", fake_tool)
    result = pipeline.extract(pipeline.capture(source)["id"], ocr=True, language="eng+fra")
    assert result["usage"]["ocr_invocations"] == 1 and result["usage"]["ocr_language"] == "eng+fra"
    assert result["paragraphs"][0]["text"] == "4O%"  # No automatic metric correction.
    assert "ocr_word_below_80" in result["paragraphs"][0]["flags"]
    assert result["stages"]["review"] == "not_started"
    assert any("eng+fra" in args for _, args in calls)


def test_ocr_evidence_outside_image_is_rejected():
    text = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t90\t90\t20\t20\t99\t40%\n'
    with pytest.raises(IngestionError, match="outside"):
        extractors.ocr_tsv(text, "doc-test", 1, "ocr.tsv", (100, 100))


def test_docx_column_sections_require_an_explicit_resolution(project):
    source = docx_file(project / "columns.docx", body='<w:p><w:r><w:t>Employer A</w:t></w:r></w:p><w:sectPr><w:cols w:num="2"/></w:sectPr>')
    result = pipeline.extract(pipeline.capture(source)["id"])
    assert "multiple_section_columns_reading_order_unverified" in result["issues"]
    path, form = simulated_review(project, result)
    form["issue_resolutions"][result["issues"][0]] = ""
    save_form(path, form)
    with pytest.raises(IngestionError, match="every extraction-wide"):
        pipeline.approve(result["revision"], path)


def test_private_originals_are_not_staged_and_existing_tracking_blocks_ingestion(project):
    subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
    _, captured, _ = extracted_project(project)
    subprocess.run(["git", "add", "--all"], cwd=project, capture_output=True, check=True)
    tracked = subprocess.run(["git", "ls-files", "--", ".vita/ingestion"], cwd=project, capture_output=True, check=True)
    assert not tracked.stdout
    original = store() / "documents" / captured["id"] / "original.bin"
    subprocess.run(["git", "add", "--force", str(original)], cwd=project, capture_output=True, check=True)
    with pytest.raises(IngestionError, match="already tracked"):
        pipeline.extract(captured["id"])


def test_review_report_keeps_source_markdown_as_literal_text(project):
    _, _, result = extracted_project(project, ['```\n![contact](https://example.invalid/no-fetch)\n```'])
    report = (store() / "extractions" / result["revision"] / "review.md").read_text(encoding="utf-8")
    assert "````text\n```\n![contact]" in report


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_xml_entity_declarations_are_blocked_across_encodings(encoding):
    entity = '<!DOCTYPE x [<!ENTITY sample "synthetic">]><x>&sample;</x>'
    with pytest.raises(IngestionError, match="entity declarations"):
        extractors.xml(entity.encode(encoding))
    assert extractors.xml('<x>Élodie — 40% — سيرة</x>'.encode("utf-16")).text == "Élodie — 40% — سيرة"
