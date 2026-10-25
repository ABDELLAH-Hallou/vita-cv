"""vita/helpers/context_builder.py — Packages local files into LLM context."""
import re
from datetime import date
from pathlib import Path

from vita.helpers.diagnostics import phase
from vita.helpers.skills import skill_context

JOB_HEADER_RE = re.compile(r"(?im)^#\s*Job\s+\d+\b.*$")
CV_KNOWLEDGE_FILE = Path(".vita") / "cv.yaml"


def parse_job_descriptions(job_text: str) -> list[tuple[str, str]]:
    """Parse job.md sections headed by '# Job N'."""
    matches = list(JOB_HEADER_RE.finditer(job_text))
    if len(matches) < 2:
        return []

    jobs = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(job_text)
        title = match.group(0).lstrip("#").strip()
        body = job_text[start:end].strip()
        if body:
            jobs.append((title, body))
    return jobs


def format_job_descriptions(job_text: str) -> tuple[str, int]:
    """Return a prompt-ready job description block and detected job count."""
    jobs = parse_job_descriptions(job_text)
    if not jobs:
        return job_text, 1 if job_text.strip() else 0

    sections = ["MULTIPLE JOB DESCRIPTIONS DETECTED:"]
    for title, body in jobs:
        sections.append(f"\n## {title}\n{body}")
    return "\n".join(sections), len(jobs)


def multi_job_instruction(job_count: int, document: str = "CV") -> str:
    return (
        f"\n\nMULTI-JOB OPTIMIZATION INSTRUCTION:\n"
        f"Multiple job descriptions detected ({job_count} jobs).\n"
        f"Your goal is to produce ONE optimized {document} that maximizes the probability "
        "of matching across ALL job descriptions. Prioritize keywords and "
        f"requirements that appear in more than one job. Do NOT produce separate {document}s."
    )


def current_date_instruction() -> str:
    today = date.today().isoformat()
    return (
        "\n\nCURRENT DATE INSTRUCTION:\n"
        f"Today's date is {today}.\n"
        "When reviewing or adapting CV dates, treat this as the current date. "
        "Do not rewrite, shorten, or correct CV dates, including future or apparently inconsistent dates. "
        "Preserve ambiguous tokens and overlapping Present roles; flag interpretations for confirmation."
    )


def read_cv_knowledge_base() -> str:
    """Return .vita/cv.yaml content when the file exists and is not empty."""
    if not CV_KNOWLEDGE_FILE.exists() or not CV_KNOWLEDGE_FILE.is_file():
        return ""

    content = CV_KNOWLEDGE_FILE.read_text(encoding="utf-8").strip()
    return content


def cv_knowledge_instruction() -> str:
    content = read_cv_knowledge_base()
    if not content:
        return ""

    return (
        "\n\nMASTER CV KNOWLEDGE BASE INSTRUCTION:\n"
        "The user has provided `.vita/cv.yaml` as a structured master CV knowledge base. "
        "Treat unverified knowledge as context only, never as proof of candidate facts. "
        "Only knowledge spans explicitly approved in `.vita/cv-verified.json` and included in the "
        "host-captured snapshot may support candidate facts. Do not treat source presence as semantic verification.\n"
        "Only captured CV sources and verified knowledge spans support candidate facts. Job descriptions "
        "and generated analyses describe requirements, not evidence of qualifications. "
        "Do not invent facts. Keep the final document concise and credible.\n\n"
        "==== FILE: .vita/cv.yaml ====\n"
        f"{content}\n"
        "=============================="
    )


def cv_source_files(entry: str, *, strict: bool = False) -> dict[str, str]:
    """Capture the CV and literal project-local input/include files, once each.

    Includes use TeX's project working directory, not the including file's directory.
    Dynamic macros and paths outside the project are intentionally unsupported.
    """
    root = Path.cwd().resolve()
    seen: set[Path] = set()
    active: set[Path] = set()
    files = {}

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if strict and resolved in active:
            raise ValueError("Cyclic CV input/include graph; prepare a complete finite source")
        if resolved in seen:
            return
        if not resolved.is_relative_to(root) or not resolved.is_file():
            if strict:
                raise ValueError("Required CV/include missing or outside project; supply every literal source before generation")
            return
        seen.add(resolved)
        active.add(resolved)
        content = resolved.read_text(encoding="utf-8")
        files[resolved.relative_to(root).as_posix()] = content
        uncommented = re.sub(r"(?m)(?<!\\)%.*$", "", content)
        if strict and re.search(r"\\(?:input|include)\b(?!\s*\{)", uncommented):
            raise ValueError("Unbraced input/include is unsupported; use explicit literal braced paths")
        for name in re.findall(r"\\(?:input|include)\s*\{([^{}]+)\}", uncommented):
            if "\\" in name or "#" in name:
                if strict:
                    raise ValueError("Dynamic input/include cannot be captured completely; prepare an explicit complete source")
                continue
            included = Path(name)
            if not included.suffix:
                included = included.with_suffix(".tex")
            visit(root / included)
        active.remove(resolved)

    visit(Path(entry))
    return files


def complete_generation_context(entry: str) -> str:
    """Validate the source graph and include prior artifacts with explicit trust boundaries."""
    cv_source_files(entry, strict=True)
    root = Path.cwd().resolve()
    if CV_KNOWLEDGE_FILE.exists() and not CV_KNOWLEDGE_FILE.resolve().is_relative_to(root):
        raise ValueError("Knowledge context must remain inside the project")
    extra = ["Supplied source snapshots establish text support only. Prior reports are generated advice, never candidate evidence."]
    for name in ("analysis.json", "analysis.md", "analyze.md", "review.json", "review.md", "adapt.md"):
        path = Path(".vita/results") / name
        if path.is_file():
            if not path.resolve().is_relative_to(root):
                raise ValueError("Prior artifacts must remain inside the project")
            extra.append(f"==== NON-EVIDENTIARY PRIOR ARTIFACT: {path.as_posix()} ====\n" + path.read_text(encoding="utf-8"))
        else:
            extra.append(f"Prior artifact unavailable: {path.as_posix()}; do not discover it or invent its contents.")
    return "\n".join(extra)


def cv_source_context(entry: str) -> str:
    return "\n".join(f"==== FILE: {path} ====\n{content}\n"
                     for path, content in cv_source_files(entry).items())


@phase("context")
def build_system_context(
    prompt_text: str, step: str | None = None, resume_entry: str = "main.tex",
    include_job: bool = True,
) -> str:
    """Scan the prompt and project for necessary files to inject as context."""
    context = "You are VITA, an expert AI agent that writes LaTeX CVs and cover letters.\n"
    context += "Below is the context gathered from the user's local file system.\n\n"
    context += current_date_instruction().strip()
    context += "\n\n"
    
    # Inject main.tex
    context += cv_source_context(resume_entry)
        
    # Inject job.md
    if include_job and Path("job.md").exists():
        job_text = Path("job.md").read_text(encoding="utf-8")
        formatted_jobs, job_count = format_job_descriptions(job_text)
        label = f"job.md ({job_count} jobs)" if job_count > 1 else "job.md"
        context += f"==== FILE: {label} ====\n"
        context += formatted_jobs
        context += "\n======================\n\n"
        
    # Inject referenced results (e.g. results/analysis.md used by adapt prompt)
    # Note: results are stored in .vita/results/ internally
    if step in (None, "adapt", "cover") and (
        "results/analysis.md" in prompt_text or ".vita/results/analyze.md" in prompt_text
    ):
        res_file = Path(".vita/results/analysis.md")
        if not res_file.exists():
            res_file = Path(".vita/results/analyze.md")
        if res_file.exists():
            context += "==== FILE: .vita/results/analyze.md ====\n"
            context += res_file.read_text(encoding="utf-8")
            context += "\n===================================\n\n"
            
    # Explicit tasks select skills independently of text in the CV/job description.
    if step is not None:
        return context + "\n" + skill_context(step)

    # Compatibility for callers that only supply a prompt.
    base_dir = Path(__file__).parent.parent
    skill_matches = set(re.findall(r"skills/[a-zA-Z0-9_-]+\.md", prompt_text))
    
    for skill_ref in sorted(skill_matches):
        skill_name = skill_ref.split("/")[1]
        skill_path = base_dir / "assets" / "skills" / skill_name
        if skill_path.exists():
            context += f"==== SKILL: {skill_name} ====\n"
            context += skill_path.read_text(encoding="utf-8")
            context += "\n=============================\n\n"
            
    return context
