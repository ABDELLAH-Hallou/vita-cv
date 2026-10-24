"""Synthetic conformance only. No native-speaker, model or human-review findings."""

import io
import itertools
import json
import urllib.error
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.multilingual.__main__ import main, pdf_check, rate, run_case
from scripts.multilingual.checks import capture, layout, structural
from scripts.multilingual.fixtures import LANGUAGES, PAGES, digest, inventory, materialize
from vita.commands import ai_step, build
from vita.helpers import llm
from vita.helpers.provider_errors import PROVIDER_ERROR_SCHEMA, ProviderError
from vita.helpers.structured import validate


@pytest.mark.parametrize("source,target,pages", list(itertools.product(LANGUAGES, LANGUAGES, PAGES)))
def test_language_and_length_matrix_preserves_observable_contract(tmp_path, source, target, pages):
    original = materialize(tmp_path / "source", source, pages)
    materialize(tmp_path / "output", target, pages)
    result = structural(original, tmp_path / "output", target)
    assert result["status"] == "mechanical_checks_passed"
    assert result["semantic_translation_quality"] is None
    assert result["linguistic_review"] == "unavailable"
    assert result["rtl_reading_order"] == "unreviewed"
    text, files = capture(tmp_path / "source")
    assert len(files) == (1 if pages == 1 else pages + 2)
    assert "Atelier Boréal " + str(pages) in text
    assert f"history-{pages - 1}" in text


@pytest.mark.parametrize("source,target", [("en", "es"), ("es", "fr"), ("fr", "ar"), ("ar", "en")])
def test_multifile_prompt_capture_and_unattended_confirmation(tmp_path, source, target):
    result = run_case(tmp_path / "case", source, target, 8)
    assert result["status"] == "passed"
    assert result["manual_prompt"]["generated"]
    assert result["automatic"]["all_source_files_in_context"]
    assert result["automatic"]["source_bytes_unchanged"]
    assert result["automatic"]["factual_status"] == "confirmation_required"
    assert result["automatic"]["attempts"] == 1
    prompt = (tmp_path / "case/source/.vita/current_prompt.md").read_text(encoding="utf-8")
    assert "never silently shorten history" in prompt
    assert "every captured input/include file" in prompt


@pytest.fixture
def documents(tmp_path):
    source = materialize(tmp_path / "source", "fr", 8)
    materialize(tmp_path / "output", "en", 8)
    text, _ = capture(tmp_path / "output")
    (tmp_path / "flat").mkdir()
    output = tmp_path / "flat/main.tex"
    output.write_text(text, encoding="utf-8")
    return source, output


@pytest.mark.parametrize("mutation,field", [
    ("oldest", "missing_units"), ("education", "missing_units"),
    ("metric", "changed_protected_facts"), ("unit", "changed_protected_facts"),
    ("official_name", "changed_protected_facts"), ("credential", "changed_protected_facts"),
    ("date", "changed_protected_facts"), ("url", "changed_protected_facts"),
    ("number_addition", "numeric_changes"), ("fictional_employer", "errors"),
    ("unknown_unit", "unexpected_units"), ("duplicate", "duplicate_units"),
    ("untranslated_heading", "untranslated_source_units"), ("truncation", "errors"),
    ("hidden_history", "errors"),
])
def test_omissions_additions_truncation_and_protected_facts(documents, mutation, field):
    source, output = documents
    text = output.read_text(encoding="utf-8")
    if mutation in ("oldest", "education"):
        key = "history-7" if mutation == "oldest" else "education"
        text = "\n".join(line for line in text.splitlines() if not line.startswith("\\CVText{" + key + "}"))
    else:
        before, after = {
            "metric": (r"40\%", r"60\%"), "unit": ("250 ms", "250 s"),
            "official_name": ("Lumière 2030", "Light 2030"),
            "credential": ("Certificado Delta", "Delta Certified Expert"),
            "date": ("Sen 2017", "Sep 2017"), "url": ("example.invalid/cv", "invented.invalid/cv"),
            "number_addition": ("Data engineer", "Managed 900 staff. Data engineer"),
            "fictional_employer": (r"\end{document}", "Worked at Fictional Employer.\n" + r"\end{document}"),
            "unknown_unit": (r"\end{document}", r"\CVText{invented}{Fictional Employer}" + "\n" + r"\end{document}"),
            "duplicate": (r"\end{document}", r"\CVText{profile}{Data engineer.}" + "\n" + r"\end{document}"),
            "untranslated_heading": (r"\CVHeading{heading-education}{Education}", r"\CVHeading{heading-education}{Formation}"),
            "truncation": (r"\end{document}", ""),
            "hidden_history": (r"\newcommand{\CVText}[2]{#2\par}", r"\newcommand{\CVText}[2]{}"),
        }[mutation]
        assert before in text
        text = text.replace(before, after)
    output.write_text(text, encoding="utf-8")
    result = structural(source, output.parent, "en")
    assert result["status"] == "failed"
    assert result[field]


@pytest.mark.parametrize("before,after", [
    ("expired", "valid"), ("degree not awarded", "degree awarded"),
    ("OOP", "Object Oriented Design"), ("TTR", "Time To Resolve"),
    ("currency unspecified", "USD"),
])
def test_semantic_changes_never_receive_an_automatic_quality_pass(documents, before, after):
    source, output = documents
    text = output.read_text(encoding="utf-8")
    assert before in text
    output.write_text(text.replace(before, after), encoding="utf-8")
    result = structural(source, output.parent, "en")
    assert result["status"] in ("failed", "review_required")
    assert result["draft_mismatches"]
    assert result["semantic_translation_quality"] is None


@pytest.mark.parametrize("change", ["missing", "cycle", "outside", "dynamic"])
def test_unmeasurable_includes_are_explicit(tmp_path, change):
    source = materialize(tmp_path / "source", "en", 3)
    materialize(tmp_path / "output", "fr", 3)
    paths = {"missing": "absent", "cycle": "main.tex", "outside": "../source/main.tex", "dynamic": r"\path"}
    (tmp_path / "output/main.tex").write_text(r"\input{" + paths[change] + "}", encoding="utf-8")
    result = structural(source, tmp_path / "output", "fr")
    assert result["status"] == "failed" and result["errors"]


@pytest.mark.parametrize("limit_kind", ["input_context", "output_length"])
def test_context_and_output_limits_preserve_all_source_history(tmp_path, monkeypatch, limit_kind):
    root = tmp_path / "project"
    original = materialize(root, "ar", 8)
    monkeypatch.chdir(root)
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    code = "invalid_request" if limit_kind == "input_context" else "incomplete_response"
    backend = Mock(side_effect=ProviderError(code=code, status=400 if limit_kind == "input_context" else None, limit_kind=limit_kind))
    monkeypatch.setattr(ai_step, "llm_generate", backend)
    assert ai_step.run("adapt", language="fr", auto=True, provider="openai") is False
    backend.assert_called_once()
    system, prompt = backend.call_args.args
    for path in original["sources"]:
        assert (root / path).read_text(encoding="utf-8") in system
    assert "Atelier Boréal 8" in system
    assert "2016" in system and "2009" in system
    for path, sha in original["sources"].items():
        assert digest((root / path).read_text(encoding="utf-8")) == sha
    outcome = json.loads(Path(".vita/results/adapt.outcome.json").read_text(encoding="utf-8"))
    assert outcome["attempt_count"] == 1
    assert outcome["error"]["limit_kind"] == limit_kind
    assert outcome["error"]["retryable"] is False
    validate(outcome["error"], PROVIDER_ERROR_SCHEMA)


@pytest.mark.parametrize("message", ["context_length_exceeded", "The input token count (9999) exceeds the maximum number of tokens allowed (1000).", "prompt is too long: 9999 tokens"])
def test_explicit_http_context_limit_is_safe_and_actionable(monkeypatch, message):
    body = json.dumps({"error": {"message": message + " private candidate content"}}).encode()
    error = urllib.error.HTTPError("https://example.invalid", 400, "bad request", {}, io.BytesIO(body))
    monkeypatch.setattr(llm.urllib.request, "urlopen", Mock(side_effect=error))
    with pytest.raises(ProviderError) as stopped:
        llm._post("https://example.invalid", {}, {"messages": []})
    assert stopped.value.code == "invalid_request"
    assert stopped.value.limit_kind == "input_context"
    assert "private candidate" not in str(stopped.value)
    assert "history was not shortened" in str(stopped.value)


@pytest.mark.parametrize("provider", ["openai", "gemini", "anthropic"])
def test_adapter_output_length_never_accepts_partial_text(monkeypatch, provider):
    responses = {
        "openai": {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]},
        "gemini": {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "partial"}]}}]},
        "anthropic": {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "partial"}]},
    }
    monkeypatch.setattr(llm, "_post", lambda *a, **k: responses[provider])
    with pytest.raises(ProviderError) as stopped:
        getattr(llm, "_call_" + provider)("full context", "full prompt", "not-a-key", "fixture-model")
    assert stopped.value.code == "incomplete_response"
    assert stopped.value.limit_kind == "output_length"


def test_truncated_standalone_adapt_is_rejected_before_factual_staging(tmp_path, monkeypatch):
    materialize(tmp_path / "project", "en", 1)
    monkeypatch.chdir(tmp_path / "project")
    monkeypatch.setenv("ENABLE_JD_EXTRACTION", "false")
    before = Path("main.tex").read_bytes()
    backend = Mock(return_value="```latex\n\\documentclass{article}\n\\begin{document}\nPartial\n```")
    monkeypatch.setattr(ai_step, "llm_generate", backend)
    stage = Mock()
    monkeypatch.setattr(ai_step, "stage", stage)
    assert ai_step.run("adapt", auto=True) is False
    stage.assert_not_called()
    assert Path("main.tex").read_bytes() == before


@pytest.mark.parametrize("engine,flag", [("pdflatex", "-pdf"), ("xelatex", "-xelatex"), ("lualatex", "-lualatex")])
def test_explicit_build_engine(tmp_path, monkeypatch, engine, flag):
    monkeypatch.chdir(tmp_path)
    Path("main.tex").write_text(r"\documentclass{article}\begin{document}Text\end{document}", encoding="utf-8")
    Path(".vita").mkdir()
    Path(".vita/config.json").write_text(json.dumps({"latex_engine": engine, "output_filename": "cv.pdf"}), encoding="utf-8")
    calls = []
    def compile_document(argv):
        calls.append(argv)
        Path("out/cv.pdf").write_bytes(b"%PDF-fixture")
        return True
    monkeypatch.setattr(build, "_step", compile_document)
    assert build.run()
    assert flag in calls[0]


@pytest.mark.parametrize("engine", ["pdflatex", "unknown-engine"])
def test_unsupported_engine_font_contract_is_actionable(tmp_path, monkeypatch, capsys, engine):
    materialize(tmp_path / "project", "ar", 3)
    monkeypatch.chdir(tmp_path / "project")
    Path(".vita/config.json").write_text(json.dumps({"latex_engine": engine}), encoding="utf-8")
    compiler = Mock()
    monkeypatch.setattr(build, "_step", compiler)
    assert build.run() is False
    compiler.assert_not_called()
    assert "latex_engine" in capsys.readouterr().out


@pytest.mark.parametrize("change,alarm", [("outside", "text_outside_page"), ("empty", "empty_page"),
                                        ("count", "unexpected_page_count"), ("glyph", "overfull_box_or_missing_glyph")])
def test_layout_checks_do_not_claim_semantic_quality(change, alarm):
    x = "900" if change == "outside" else "10"
    word = "" if change == "empty" else f'<word xMin="{x}" yMin="20" xMax="950" yMax="30">text</word>'
    if change != "outside":
        word = word.replace('xMax="950"', 'xMax="40"')
    bbox = f'<html><page width="600" height="800">{word}</page></html>'
    result = layout("Missing character: test" if change == "glyph" else "", bbox, 3 if change == "count" else 1)
    assert result["status"] == "alarms_detected" and alarm in result["errors"]
    assert result["visual_review"] == "unavailable"
    assert result["rtl_reading_order"] == "unreviewed"


def test_missing_render_tools_and_no_attempts_are_not_successes(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.multilingual.__main__.shutil.which", lambda _: None)
    result = pdf_check(tmp_path, 1)
    assert result["status"] == "unavailable" and result["missing_tools"]
    assert rate(0, 0)["value"] is None


def test_external_check_is_reproducible_and_rejects_stale_sources(tmp_path):
    source = materialize(tmp_path / "source", "fr", 1)
    materialize(tmp_path / "output", "es", 1)
    args = ["--check-project", str(tmp_path / "output"), "--source-manifest", str(tmp_path / "source/fixture.json"), "--target-language", "es"]
    assert main([*args, "--output", str(tmp_path / "report")]) == 0
    assert main([*args, "--output", str(tmp_path / "report")]) == 2
    first = next(iter(source["sources"]))
    (tmp_path / "source" / first).write_text("changed", encoding="utf-8")
    assert main([*args, "--output", str(tmp_path / "stale")]) == 2


def test_fixture_qualifications_and_history_have_independent_review_boundaries():
    for language in LANGUAGES:
        units = inventory(language, 8)
        assert "2020" in units["education"]["text"]
        assert "Sen 2017" in units["custom"]["text"]
        assert "2009" in units["history-7"]["text"]
        assert len([key for key in units if key.startswith("history-") and not key.startswith("history-heading")]) == 43
        assert r"\textenglish{Nadia El-Haddad}" in units["name"]["text"]
        assert sum(len(value["text"].split()) for key, value in units.items() if key.startswith("history-")) > 2500


def test_recomputed_hashes_cannot_mask_changed_source_facts(tmp_path):
    manifest = materialize(tmp_path / "source", "fr", 1)
    materialize(tmp_path / "output", "es", 1)
    entry = tmp_path / "source/main.tex"
    entry.write_text(entry.read_text(encoding="utf-8").replace(r"40\%", r"60\%"), encoding="utf-8")
    manifest["sources"]["main.tex"] = digest(entry.read_text(encoding="utf-8"))
    path = tmp_path / "source/fixture.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert main(["--check-project", str(tmp_path / "output"), "--source-manifest", str(path),
                 "--target-language", "es", "--output", str(tmp_path / "report")]) == 2
