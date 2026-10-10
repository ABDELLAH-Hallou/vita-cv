"""Install a built wheel in isolation and exercise the public CLI."""

import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def python_in(virtual_environment: Path) -> Path:
    if os.name == "nt":
        return virtual_environment / "Scripts" / "python.exe"
    return virtual_environment / "bin" / "python"


def smoke_test(distribution_directory: Path, expected_version: str | None = None) -> None:
    version_pattern = expected_version or "*"
    wheels = list(distribution_directory.glob(f"vita_cv-{version_pattern}-*.whl"))
    source_distributions = list(distribution_directory.glob(f"vita_cv-{version_pattern}.tar.gz"))
    if len(wheels) != 1 or len(source_distributions) != 1:
        raise AssertionError(
            "Expected exactly one vita-cv wheel and one source distribution in "
            f"{distribution_directory}"
        )

    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        required_assets = {
            "vita/assets/prompts/analyze.md",
            "vita/assets/prompts/adapt.md",
            "vita/assets/prompts/review.md",
        }
        missing_assets = required_assets - names
        if missing_assets:
            raise AssertionError(f"Wheel is missing assets: {sorted(missing_assets)}")

    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        virtual_environment = root / "venv"
        project = root / "project"
        project.mkdir()
        venv.EnvBuilder(with_pip=True).create(virtual_environment)
        python = python_in(virtual_environment)

        run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                str(wheels[0].resolve()),
            ]
        )
        version = run([str(python), "-m", "vita", "--version"], cwd=project).stdout.strip()
        if not version.startswith("vita-cv "):
            raise AssertionError(f"Unexpected version output: {version!r}")

        help_text = run([str(python), "-m", "vita", "--help"], cwd=project).stdout
        for command in ("init", "new", "build", "analyze", "adapt", "review", "run"):
            if command not in help_text:
                raise AssertionError(f"CLI help is missing command {command!r}")

        run([str(python), "-m", "vita", "init"], cwd=project)
        config_file = project / ".vita" / "config.json"
        registry_file = project / ".vita" / "companies.json"
        if not config_file.is_file() or not registry_file.is_file():
            raise AssertionError("vita init did not create its required configuration files")
        if not isinstance(json.loads(config_file.read_text(encoding="utf-8")), dict):
            raise AssertionError("vita init created invalid config.json")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: run_installed_package.py DIST_DIRECTORY [VERSION]")
    smoke_test(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) == 3 else None)
    print("Installed package smoke test passed")
