"""Reproduce synthetic translation, context and rendering checks without AI calls."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.multilingual.checks import capture, layout, structural
from scripts.multilingual.fixtures import LANGUAGES, PAGES, digest, inventory, materialize
from vita import __version__
from vita.commands import ai_step
from vita.helpers.provider_errors import ProviderError

REPOSITORY = Path(__file__).resolve().parents[2]


@contextlib.contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def command(argv, cwd, timeout=90):
    started = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                                capture_output=True, timeout=timeout)
        return {"argv": argv, "exit_status": result.returncode, "stdout": result.stdout,
                "stderr": result.stderr, "elapsed_seconds": time.monotonic() - started}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "exit_status": None, "error": type(exc).__name__,
                "elapsed_seconds": time.monotonic() - started}


def pdf_check(root, pages):
    """Real Vita build plus geometry and page images; no semantic/visual verdict."""
    required = ("latexmk", "xelatex", "kpsewhich", "fc-match", "pdftotext", "pdftoppm")
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        return {"status": "unavailable", "missing_tools": missing,
                "action": "Install TeX Live XeTeX, latexmk, fontconfig, Poppler, DejaVu Serif and Amiri. Windows without fontconfig needs manual font verification; it is not silently passed."}
    probes = [command(["kpsewhich", name + ".sty"], root) for name in ("fontspec", "polyglossia")]
    for font in ("Amiri", "DejaVu Serif"):
        probe = command(["fc-match", "-f", "%{family}", font], root)
        probes.append(probe)
        if probe.get("exit_status") != 0 or font not in probe.get("stdout", ""):
            return {"status": "unsupported", "probes": probes, "action": "Install the exact fixture font: " + font + "; fallback fonts are not accepted as measured coverage."}
    if any(p.get("exit_status") != 0 or not p.get("stdout", "").strip() for p in probes):
        return {"status": "unsupported", "probes": probes, "action": "Install fontspec and polyglossia for XeLaTeX; do not replace Arabic with Latin text."}
    env = {**os.environ, "PYTHONPATH": str(REPOSITORY), "PYTHONUTF8": "1"}
    with patch.dict(os.environ, env):
        build = command([sys.executable, "-m", "vita", "build"], root)
    (root / "build-result.json").write_text(json.dumps(build, ensure_ascii=False, indent=2), encoding="utf-8")
    if build.get("exit_status") != 0:
        return {"status": "compile_failed", "build": build, "probes": probes,
                "action": "Inspect build-result.json and out/cv.log for engine, package or font errors."}
    extracted = command(["pdftotext", "-bbox-layout", "out/cv.pdf", "out/cv.bbox.html"], root)
    log = (root / "out/cv.log").read_text(encoding="utf-8", errors="replace")
    if extracted.get("exit_status") != 0:
        return {"status": "inspection_failed", "inspection": extracted}
    measured = layout(log, (root / "out/cv.bbox.html").read_text(encoding="utf-8"), pages)
    # Preserve every page for competent human inspection, including the oldest history.
    rendered = command(["pdftoppm", "-scale-to", "1200", "-png", "out/cv.pdf", "out/page"], root)
    images = sorted(p.relative_to(root).as_posix() for p in (root / "out").glob("page-*.png"))
    okay = measured["status"] == "mechanical_checks_passed" and rendered.get("exit_status") == 0 and len(images) == pages
    return {"status": "mechanical_checks_passed" if okay else "layout_failed", "layout": measured,
            "build": {key: value for key, value in build.items() if key not in ("stdout", "stderr")},
            "probes": probes, "render": rendered, "page_images": images,
            "pdf_sha256": hashlib.sha256((root / "out/cv.pdf").read_bytes()).hexdigest(),
            "linguistic_review": "unavailable", "visual_review": "unavailable"}


def run_case(root, source_language, target_language, pages):
    started = time.monotonic()
    source = materialize(root / "source", source_language, pages)
    materialize(root / "draft", target_language, pages)
    candidate, _ = capture(root / "draft")
    (root / "proposal").mkdir()
    (root / "proposal/main.tex").write_text(candidate, encoding="utf-8")
    backend = Mock(return_value="```latex\n" + candidate + "\n```")
    stream = io.StringIO()
    with working_directory(root / "source"), contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream), patch.dict(os.environ, {"ENABLE_JD_EXTRACTION": "false"}), patch.object(ai_step, "llm_generate", backend):
        manual = ai_step.run("adapt", language=target_language, auto=False)
        manual_text = Path(".vita/current_prompt.md").read_text(encoding="utf-8")
        automatic = ai_step.run("adapt", language=target_language, auto=True, provider="openai")
    (root / "execution.txt").write_text(stream.getvalue(), encoding="utf-8")
    system, prompt = backend.call_args.args
    _, files = capture(root / "source")
    full_capture = all(content in system for content in files.values())
    unchanged = all(digest((root / "source" / path).read_text(encoding="utf-8")) == sha for path, sha in source["sources"].items())
    outcome = json.loads((root / "source/.vita/results/adapt.outcome.json").read_text(encoding="utf-8"))
    factual = root / "source/.vita/results/adapt.facts.json"
    state = json.loads(factual.read_text(encoding="utf-8"))["status"] if factual.exists() else None
    checks = structural(source, root / "proposal", target_language)
    okay = manual and full_capture and backend.call_count == 1 and checks["status"] == "mechanical_checks_passed" and (automatic or (state == "confirmation_required" and unchanged))
    return {"case_id": f"{source_language}-{target_language}-{pages}", "source_language": source_language,
            "target_language": target_language, "expected_pages": pages, "status": "passed" if okay else "failed",
            "transport": "deterministic synthetic draft; not model generation or human gold",
            "manual_prompt": {"generated": manual, "sha256": digest(manual_text)},
            "automatic": {"exit_success": automatic, "factual_status": state, "all_source_files_in_context": full_capture,
                          "source_bytes_unchanged": unchanged, "attempts": outcome["attempt_count"],
                          "route": outcome["attempts"][0]["route"],
                          "system_sha256": digest(system), "prompt_sha256": digest(prompt)},
            "checks": checks, "elapsed_seconds": time.monotonic() - started}


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator, "value": numerator / denominator if denominator else None}


def limit_control(root, language, kind):
    source = materialize(root, language, 8)
    if kind == "truncated_document":
        backend = Mock(return_value="```latex\n\\documentclass{article}\n\\begin{document}\nPartial\n```")
    else:
        backend = Mock(side_effect=ProviderError(code="invalid_request" if kind == "input_context" else "incomplete_response", limit_kind=kind))
    stream = io.StringIO()
    with working_directory(root), contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream), patch.dict(os.environ, {"ENABLE_JD_EXTRACTION": "false"}), patch.object(ai_step, "llm_generate", backend):
        succeeded = ai_step.run("adapt", language="en", auto=True, provider="openai")
    (root / "execution.txt").write_text(stream.getvalue(), encoding="utf-8")
    unchanged = all(digest((root / path).read_text(encoding="utf-8")) == sha for path, sha in source["sources"].items())
    full = all((root / path).read_text(encoding="utf-8") in backend.call_args.args[0] for path in source["sources"])
    outcome = json.loads((root / ".vita/results/adapt.outcome.json").read_text(encoding="utf-8"))
    okay = not succeeded and unchanged and full and backend.call_count == 1
    return {"language": language, "kind": kind, "status": "passed" if okay else "failed",
            "execution_success": succeeded, "source_bytes_unchanged": unchanged, "all_source_files_in_context": full,
            "attempts": outcome["attempt_count"], "error": outcome.get("error"),
            "failure_phase": "validation" if kind == "truncated_document" else "provider_request",
            "scope": "Expected deterministic failure control, not a live provider failure-rate estimate"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", help="One source-target-page case, e.g. fr-ar-8")
    parser.add_argument("--real-pdf", action="store_true", help="Local TeX/Poppler only; no model calls")
    parser.add_argument("--check-project", type=Path, help="Check an external proposal instead of executing fixtures")
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--target-language", choices=LANGUAGES)
    args = parser.parse_args(argv)
    try:
        destination = args.output.resolve()
        destination.mkdir(parents=True, exist_ok=False)
        if args.check_project:
            if not args.source_manifest or not args.target_language:
                raise ValueError("External checks require --source-manifest and --target-language")
            manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
            source_root = args.source_manifest.resolve().parent
            if manifest["schema_version"] != 1 or manifest["language"] not in LANGUAGES or manifest["expected_pages"] not in PAGES or manifest["units"] != inventory(manifest["language"], manifest["expected_pages"]):
                raise ValueError("Expected the versioned synthetic fixture contract, not arbitrary reference labels")
            _, captured = capture(source_root)
            if set(captured) != set(manifest["sources"]) or any(digest((source_root / name).read_text(encoding="utf-8")) != sha for name, sha in manifest["sources"].items()):
                raise ValueError("Stale fixture source manifest")
            if structural(manifest, source_root, manifest["language"])["status"] != "mechanical_checks_passed":
                raise ValueError("Captured source text does not match the declared synthetic fixture units")
            result = structural(manifest, args.check_project.resolve(), args.target_language)
            (destination / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0 if result["status"] == "mechanical_checks_passed" else 1
        cases = [(source, target, pages) for source in LANGUAGES for target in LANGUAGES for pages in PAGES]
        if args.case:
            cases = [case for case in cases if "-".join(map(str, case)) == args.case]
            if not cases:
                raise ValueError("Unknown case; use en/es/fr/ar pairs and 1/3/8 pages")
        results, pdfs = [], {}
        for source, target, pages in cases:
            case_root = destination / f"{source}-{target}-{pages}"
            result = run_case(case_root, source, target, pages)
            if args.real_pdf:
                key = f"{target}-{pages}"
                if key not in pdfs:
                    pdfs[key] = {"project": str((case_root / "draft").relative_to(destination)), **pdf_check(case_root / "draft", pages)}
                result["render_reference"] = key
            results.append(result)
            print(result["case_id"] + ": " + result["status"], flush=True)
        controls = [limit_control(destination / "limit-controls" / (language + "-" + kind), language, kind)
                    for language in LANGUAGES for kind in ("input_context", "output_length", "truncated_document")]
        report = {"schema_version": 1, "suite": "multilingual-document/1", "python": platform.python_version(),
                  "product_version": __version__, "extraction_enabled": False,
                  "fixture_hashes": {name: digest(Path(__file__).with_name(name).read_text(encoding="utf-8")) for name in ("fixtures.py", "locales.json", "checks.py", "__main__.py")},
                  "cases": results, "renderings": pdfs, "limit_controls": controls,
                  "limit_control_conformance_failure_rate": rate(sum(row["status"] != "passed" for row in controls), len(controls)),
                  "limit_control_execution_failure_rate": rate(sum(not row["execution_success"] for row in controls), len(controls)),
                  "conformance_failure_rate": rate(sum(row["status"] != "passed" for row in results), len(results)),
                  "rendering_nonpass_rate": rate(sum(row["status"] != "mechanical_checks_passed" for row in pdfs.values()), len(pdfs)),
                  "provider_generation": "not attempted; no live spending", "linguistic_review": "unavailable",
                  "semantic_translation_quality": None, "rtl_reading_order": "unreviewed",
                  "claims": {"translation_validated": False, "ats_validated": False, "hiring_outcomes_validated": False}}
        # Case-level alarms on inspectable synthetic outputs, never semantic accuracy.
        report["structural_alarm_rates"] = {name: rate(sum(bool(row["checks"][field]) for row in results), len(results))
            for name, field in (("omission", "missing_units"), ("unanchored_or_invalid_output", "errors"),
                                ("unexpected_units", "unexpected_units"), ("protected_fact_change", "changed_protected_facts"),
                                ("numeric_change", "numeric_changes"), ("untranslated_source", "untranslated_source_units"),
                                ("truncation_suspected", "truncation_suspected"),
                                ("draft_mismatch_requiring_review", "draft_mismatches"))}
        report["strata"] = [{"axis": axis, "value": value, "planned": len(rows),
                              "conformance_failure_rate": rate(sum(row["status"] != "passed" for row in rows), len(rows)),
                              "linguistic_review": "unavailable", "semantic_translation_quality": None}
            for axis in ("source_language", "target_language", "expected_pages")
            for value in sorted({row[axis] for row in results})
            for rows in [[row for row in results if row[axis] == value]]]
        report["rendering_counts"] = {state: sum(row["status"] == state for row in pdfs.values())
            for state in ("unavailable", "unsupported", "compile_failed", "inspection_failed", "layout_failed", "mechanical_checks_passed")}
        (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (destination / "report.md").write_text("# Multilingual structural conformance\n\n"
            + f"Synthetic cases: {len(results)}; failures: {report['conformance_failure_rate']['numerator']}.\n\n"
            + f"Unique target renderings: {len(pdfs)}; nonpasses (including unavailable): {report['rendering_nonpass_rate']['numerator']}.\n\n"
            + "No live generation, independent linguistic review, semantic translation result or RTL reading-order judgment is available. Compilation is not translation validation. ATS/hiring outcomes remain unvalidated.\n", encoding="utf-8")
        return 1 if report["conformance_failure_rate"]["numerator"] or report["rendering_nonpass_rate"]["numerator"] or report["limit_control_conformance_failure_rate"]["numerator"] else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("Multilingual validation failed: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
