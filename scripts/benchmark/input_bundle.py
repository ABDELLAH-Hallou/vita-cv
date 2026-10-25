"""Pinned local document inputs for real-world development pilots."""

from pathlib import PurePosixPath

from scripts.benchmark import runner


def validate(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"path", "candidate_id", "job_id", "files"}:
        raise ValueError("Input bundle requires path, candidate_id, job_id and pinned files")
    for key in ("candidate_id", "job_id"):
        if not isinstance(bundle[key], str) or not runner.NAME.fullmatch(bundle[key]):
            raise ValueError("Invalid bundle source identity")
    relative = PurePosixPath(bundle["path"])
    if relative.is_absolute() or ".." in relative.parts or ":" in str(relative):
        raise ValueError("Input bundle path must stay inside the checkout")
    root = (runner.ROOT / str(relative)).resolve()
    if not root.is_relative_to(runner.ROOT.resolve()) or root.is_symlink():
        raise ValueError("Input bundle escaped the checkout")
    files = bundle["files"]
    if not isinstance(files, dict) or not {"main.tex", "job.md", "requirements.json"}.issubset(files) or len(files) > 100:
        raise ValueError("Bundle requires main.tex, job.md and source-linked control requirements")
    size = 0
    for name, expected in files.items():
        file = PurePosixPath(name)
        if file.is_absolute() or ".." in file.parts or ":" in name or any(p.startswith(".") for p in file.parts):
            raise ValueError("Unsafe bundle filename")
        if file.suffix not in (".tex", ".sty", ".cls", ".bib") and name not in ("job.md", "requirements.json"):
            raise ValueError("Bundle accepts document sources only, never credentials or executable helpers")
        source = root / name
        if source.is_symlink() or not source.resolve().is_relative_to(root) or not source.is_file():
            raise ValueError("Missing or external bundle file")
        size += source.stat().st_size
        if size > 10_000_000:
            raise ValueError("Input bundle exceeded 10 MB")
        data = source.read_bytes()
        if size > 10_000_000 or runner.digest(data) != expected:
            raise ValueError("Input bundle changed or exceeded 10 MB; freeze a new plan")
    return root


def copy(bundle, destination):
    root = validate(bundle)
    for name, expected in bundle["files"].items():
        data = (root / name).read_bytes()
        if runner.digest(data) != expected:
            raise ValueError("Bundle changed during capture")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    frozen = destination / ".vita/benchmark-inputs"
    for name in bundle["files"]:
        target = frozen / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((destination / name).read_bytes())
    runner.write(frozen / "manifest.json", {"split": "public_development_pilot", **bundle})
