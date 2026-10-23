"""Optional JD-only extraction, versioned cache, and runtime context selection."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from vita.helpers.context_builder import format_job_descriptions, parse_job_descriptions
from vita.helpers.diagnostics import diagnosed, phase
from vita.helpers.llm import generate
from vita.helpers.pipeline_config import PipelineSettings, load_pipeline_settings
from vita.helpers.requirements import active_requirements, canonical_text
from vita.helpers.skills import skill_context
from vita.helpers.structured import JOB_SCHEMA, json_text, parse_json, validate, write_artifact
from vita.helpers.structured_output import run_structured
from vita.helpers.toon import encode_job

RESULTS = Path(".vita") / "results"


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@phase("context")
def read_job() -> str:
    path = Path("job.md")
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        raise ValueError("A nonempty job.md is required for this task")
    return path.read_text(encoding="utf-8")


def job_ids(raw: str) -> tuple[str, ...]:
    count = len(parse_job_descriptions(raw)) or 1
    return tuple(f"job-{index}" for index in range(1, count + 1))


def validate_job(data: dict, raw: str) -> None:
    validate(data, JOB_SCHEMA)
    if data["source_sha256"] != fingerprint(raw):
        raise ValueError("Extracted job metadata belongs to a different job.md")
    if tuple(job["id"] for job in data["jobs"]) != job_ids(raw):
        raise ValueError("Extraction must preserve every job section and its ordered ID")


def cached_job(raw: str) -> dict | None:
    try:
        data = parse_json((RESULTS / "job.json").read_text(encoding="utf-8"))
        validate_job(data, raw)
        return data
    except (ValueError, OSError, UnicodeError):
        return None


@diagnosed(name="extract")
def extract(*, auto: bool = False, provider: str | None = None) -> bool:
    try:
        raw = read_job()
        settings = load_pipeline_settings()
        template = (Path(__file__).parent.parent / "assets/prompts/extract.md").read_text(encoding="utf-8")
        prompt = (
            template + "\n\nJSON SCHEMA:\n" + json_text(JOB_SCHEMA)
            + f"\nSet schema_version to 1 and source_sha256 to {fingerprint(raw)}."
            + "\nRAW JOB DESCRIPTION:\n" + format_job_descriptions(raw)[0]
        )
        skills = skill_context("extract")
        if not auto:
            prompt = skills + "\n\n" + prompt + (
                "\n\nSave the JSON to .vita/results/job.json. Generate .vita/results/job.toon "
                "from that JSON using vita.helpers.toon.encode_job; do not invent a TOON dialect."
            )
            write_artifact(Path(".vita/prompts/extract.md"), prompt)
            write_artifact(Path(".vita/current_prompt.md"), prompt)
            print("Extraction prompt saved to .vita/prompts/extract.md")
            return True
        def finalize(data):
            validate_job(data, raw)
            return data

        def save(data):
            write_artifact(RESULTS / "job.toon", encode_job(data))
            write_artifact(RESULTS / "job.json", json_text(data))

        run_structured(step="extract", generate=generate,
                       system="You extract job metadata. " + skills, prompt=prompt,
                       route=settings.route("extract", provider).kwargs(), schema=JOB_SCHEMA,
                       finalize=finalize, save=save)
        print("Job metadata saved to .vita/results/job.json and job.toon")
        return True
    except (ValueError, OSError, RuntimeError, KeyError, UnicodeError):
        print("Extraction failed. See execution diagnostics for the failed phase and provider category.")
        return False


@dataclass(frozen=True)
class JobContext:
    text: str
    source_sha256: str
    context_sha256: str
    ids: tuple[str, ...]
    structured: bool
    requirements: dict | None = None


@phase("context")
def prepare_job(settings: PipelineSettings, *, auto: bool) -> JobContext:
    raw = read_job()
    requirements = active_requirements(raw)
    if requirements is not None:
        text = "APPROVED CANONICAL JOB REQUIREMENTS:\n" + canonical_text(requirements)
        return JobContext(text, fingerprint(raw), fingerprint(text), job_ids(raw), True, requirements)
    data = cached_job(raw)
    if data is None and settings.extraction_enabled and auto:
        if not extract(auto=True):
            raise ValueError("Enabled JD extraction failed; downstream tasks were not run")
        data = cached_job(raw)
        if data is None:
            raise ValueError("Extraction did not produce a valid job cache")
    if data is not None:
        # JSON is the authority: regenerate missing/stale/edited TOON without an LLM.
        toon = encode_job(data)
        path = RESULTS / "job.toon"
        if not path.exists() or path.read_text(encoding="utf-8") != toon:
            write_artifact(path, toon)
        text = "JOB METADATA (TOON):\n" + toon
    else:
        text = "RAW JOB DESCRIPTION:\n" + format_job_descriptions(raw)[0]
    return JobContext(text, fingerprint(raw), fingerprint(text), job_ids(raw), data is not None)
