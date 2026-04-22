import subprocess
from pathlib import Path
from vita.helpers.config import load_config
from vita.helpers.logging import log


def run() -> None:
    config   = load_config()
    tex_entry       = config.get("tex_entry", "main.tex")
    output_dir      = config.get("output_dir", "out")
    author          = config.get("author", "cv")
    output_filename = config.get("output_filename", "cv-{author}.pdf").format(author=author)

    if not Path(tex_entry).exists():
        print(f"LaTeX entry file not found: '{tex_entry}'")
        print("Check 'tex_entry' in .vita/config.json")
        return

    Path(output_dir).mkdir(exist_ok=True)
    tex_stem = Path(tex_entry).stem

    # ── Build ────────────────────────────────────────────────────────────────
    
    print(f"Building  : {tex_entry}")
    print(f"Output    : {output_dir}/{output_filename}")


    if not _step(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", f"-outdir={output_dir}", tex_entry]):
        return

    # ── Rename output ────────────────────────────────────────────────────────
    generated = Path(output_dir) / f"{tex_stem}.pdf"
    final     = Path(output_dir) / output_filename

    if generated.exists() and generated.resolve() != final.resolve():
        generated.replace(final)

    log(f"Built '{tex_entry}' → '{final}'")
    print()
    print(f"Your CV is ready: {final}")


def _step(cmd: list[str]) -> bool:
    label = " ".join(cmd)
    print(f"   $ {label}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"\nStep failed: {label}")
        print(result.stderr.strip())
        return False
    return True
