"""vita build — compile the LaTeX CV to PDF."""

from pathlib import Path
from vita.utils import load_config, run_shell, log


def run(mode: str = "auto") -> None:
    config   = load_config()
    tex_entry       = config.get("tex_entry", "main.tex")
    output_dir      = config.get("output_dir", "out")
    author          = config.get("author", "cv")
    output_filename = config.get("output_filename", "cv-{author}.pdf").format(author=author)

    if not Path(tex_entry).exists():
        print(f"❌ LaTeX entry file not found: '{tex_entry}'")
        print("   Check 'tex_entry' in .vita/config.json")
        return

    Path(output_dir).mkdir(exist_ok=True)
    tex_stem = Path(tex_entry).stem

    # ── Resolve build mode ───────────────────────────────────────────────────
    if mode == "auto":
        has_bib = any(Path(".").rglob("*.bib"))
        mode = "biber" if has_bib else "latexmk"

    print(f"🔨 Building  : {tex_entry}")
    print(f"   Output    : {output_dir}/{output_filename}")
    print(f"   Mode      : {mode}")
    print()

    # ── Build ────────────────────────────────────────────────────────────────
    if mode == "latexmk":
        if not _step(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", f"-outdir={output_dir}", tex_entry]):
            return

    elif mode == "biber":
        steps = [
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={output_dir}", tex_entry],
            ["biber", f"--input-directory={output_dir}", f"--output-directory={output_dir}", tex_stem],
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={output_dir}", tex_entry],
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={output_dir}", tex_entry],
        ]
        for step in steps:
            if not _step(step):
                return

    # ── Rename output ────────────────────────────────────────────────────────
    generated = Path(output_dir) / f"{tex_stem}.pdf"
    final     = Path(output_dir) / output_filename

    if generated.exists() and generated.resolve() != final.resolve():
        generated.replace(final)

    log(f"Built '{tex_entry}' → '{final}' (mode: {mode})")
    print()
    print(f"✅ PDF ready: {final}")


def _step(cmd: list[str]) -> bool:
    """Run a shell step; print it and return True on success, False on failure."""
    label = " ".join(cmd)
    print(f"   $ {label}")
    result = run_shell(cmd)
    if result.returncode != 0:
        print(f"\n❌ Step failed: {label}")
        print(result.stderr.strip())
        return False
    return True
