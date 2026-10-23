import subprocess
from pathlib import Path

from vita.helpers.config import load_config
from vita.helpers.factual_changes import guard
from vita.helpers.logging import log


def run(target: str = "resume") -> bool:
    if not guard(("adapt", "cover") if target in ("cover", "both") else ("adapt",)):
        return False
    config   = load_config()
    output_dir      = config.get("output_dir", "out")
    author          = config.get("author", "cv")
    documents = {
        "resume": (
            config.get("tex_entry", "main.tex"),
            config.get("output_filename", "cv-{author}.pdf").format(author=author),
            "CV",
        ),
        "cover": (
            config.get("cover_tex_entry", "cover-letter.tex"),
            config.get("cover_output_filename", "cover-letter-{author}.pdf").format(author=author),
            "cover letter",
        ),
    }
    if target not in ("resume", "cover", "both"):
        raise ValueError(f"Unknown build target: {target}")
    selected = list(documents.values()) if target == "both" else [documents[target]]
    sources = [Path(entry).resolve() for entry, _, _ in documents.values()]
    outputs = [(Path(output_dir) / name).resolve() for _, name, _ in documents.values()]
    if sources[0] == sources[1] or outputs[0] == outputs[1]:
        print("Resume and cover letter must have different source files and PDF filenames.")
        return False
    for entry, filename, _ in selected:
        if Path(filename).name != filename or Path(filename).suffix != ".pdf":
            print("Output filenames must be plain .pdf filenames; configure output_dir separately.")
            return False
        if not Path(entry).is_file():
            print(f"LaTeX entry file not found: '{entry}'")
            print("Check .vita/config.json; use `vita cover --auto` to generate a cover letter.")
            return False
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    for entry, filename, label in selected:
        if not _build_document(entry, output_dir, filename, label):
            return False
    return True


def _build_document(tex_entry: str, output_dir: str, output_filename: str, label: str) -> bool:
    # Use the final name during compilation so two sources with the same stem
    # cannot overwrite each other's PDFs or auxiliary files.
    final = Path(output_dir) / output_filename
    job_name = final.stem

    # ── Build ────────────────────────────────────────────────────────────────
    
    print(f"Building  : {tex_entry}")
    print(f"Output    : {output_dir}/{output_filename}")


    if not _step([
        "latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
        f"-outdir={output_dir}", f"-jobname={job_name}", tex_entry,
    ]):
        return False
    if not final.is_file():
        print(f"Build did not produce the expected PDF: {final}")
        return False

    log(f"Built '{tex_entry}' → '{final}'")
    print()
    print(f"Your {label} is ready: {final}")
    return True


def _step(cmd: list[str]) -> bool:
    label = " ".join(cmd)
    print(f"   $ {label}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        print(f"Could not run latexmk: {exc}")
        return False
    if result.returncode != 0:
        print(f"\nStep failed: {label}")
        print(result.stderr.strip() or result.stdout.strip())
        return False
    return True
