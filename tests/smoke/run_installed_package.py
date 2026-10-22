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
        encoding="utf-8",
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
            "vita/assets/prompts/requirements.md",
            "vita/assets/prompts/extract.md",
            "vita/assets/prompts/analyze.md",
            "vita/assets/prompts/adapt.md",
            "vita/assets/prompts/review.md",
            "vita/assets/prompts/cover.md",
            "vita/assets/skills/cover-letter-generator.md",
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
        for command in ("init", "new", "build", "extract", "requirements", "analyze", "adapt", "review", "cover", "run"):
            if command not in help_text:
                raise AssertionError(f"CLI help is missing command {command!r}")

        run([str(python), "-m", "vita", "init"], cwd=project)
        config_file = project / ".vita" / "config.json"
        registry_file = project / ".vita" / "companies.json"
        if not config_file.is_file() or not registry_file.is_file():
            raise AssertionError("vita init did not create its required configuration files")
        if not isinstance(json.loads(config_file.read_text(encoding="utf-8")), dict):
            raise AssertionError("vita init created invalid config.json")

        for task in ("extract", "analyze", "adapt", "review", "cover"):
            if not (project / ".vita/skills" / task).is_dir():
                raise AssertionError(f"Missing custom skill directory for {task}")
        (project / "main.tex").write_text(
            r"\documentclass{article}\begin{document}Python engineer\end{document}",
            encoding="utf-8",
        )
        (project / "job.md").write_text("Acme seeks a Python engineer.", encoding="utf-8")
        (project / ".vita/skills/cover/style.md").write_text(
            "CUSTOM LETTER STYLE: use short paragraphs.", encoding="utf-8"
        )
        run([str(python), "-m", "vita", "run", "--language", "fr"], cwd=project)
        cover_prompt = (project / ".vita/prompts/cover.md").read_text(encoding="utf-8")
        if "CUSTOM LETTER STYLE" not in cover_prompt or "**French**" not in cover_prompt:
            raise AssertionError("Installed cover workflow lost custom skills or language")
        if "Cover Letter Philosophy" not in cover_prompt:
            raise AssertionError("Installed cover workflow did not load its bundled skill")
        # Exercise the installed translation code using only generated prompts.
        # No provider call or assertion about model translation quality is involved.
        for language, target, content in (
            ("en", "English", r"\section{Formation}Master.\section{Articles}Analyse.\section{Engagements}Ateliers."),
            ("fr", "French", r"\section{Education}Master.\section{Articles}Analysis.\section{Community}Workshops."),
        ):
            (project / "main.tex").write_text(
                r"\documentclass{article}\begin{document}" + content + r"\end{document}",
                encoding="utf-8",
            )
            run([str(python), "-m", "vita", "adapt", "--language", language], cwd=project)
            prompt = (project / ".vita/prompts/adapt.md").read_text(encoding="utf-8")
            required = (f"The entire CV must be written in **{target}**",
                        "Translation applies to the whole document", "publications/articles",
                        "custom sections", "citation keys", "factual information")
            if not all(text in prompt for text in required):
                raise AssertionError(f"Installed {language} adaptation lost full-document translation")
            if "Do NOT leave English sections behind" in prompt:
                raise AssertionError("Installed adaptation retained contradictory translation wording")
        run([str(python), "-m", "vita", "extract"], cwd=project)
        extraction_prompt = (project / ".vita/prompts/extract.md").read_text(encoding="utf-8")
        if "source_sha256" not in extraction_prompt or "job.toon" not in extraction_prompt:
            raise AssertionError("Installed extraction workflow lost its schema or TOON instructions")
        run([str(python), "-c", (
            "from vita.helpers.structured import JOB_SCHEMA, EVALUATION_SCHEMA; "
            "from vita.helpers.toon import encode_job; "
            "from vita.helpers.evaluation import compute_delta; "
            "assert JOB_SCHEMA['type'] == EVALUATION_SCHEMA['type'] == 'object'"
        )], cwd=project)
        run([str(python), str(Path(__file__).with_name("assessment_authority.py").resolve())], cwd=project)
        run([str(python), str(Path(__file__).with_name("structured_recovery.py").resolve())], cwd=project)
        run([str(python), str(Path(__file__).with_name("canonical_requirements.py").resolve())], cwd=project)
        build_help = run([str(python), "-m", "vita", "build", "--help"], cwd=project).stdout
        for option in ("both", "--resume", "--cover"):
            if option not in build_help:
                raise AssertionError(f"Missing build option: {option}")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: run_installed_package.py DIST_DIRECTORY [VERSION]")
    smoke_test(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) == 3 else None)
    print("Installed package smoke test passed")
