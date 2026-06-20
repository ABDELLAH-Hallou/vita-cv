"""vita/helpers/context_builder.py — Packages local files into LLM context."""
import re
from pathlib import Path

JOB_HEADER_RE = re.compile(r"(?im)^#\s*Job\s+\d+\b.*$")


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


def multi_job_instruction(job_count: int) -> str:
    return (
        f"\n\nMULTI-JOB OPTIMIZATION INSTRUCTION:\n"
        f"Multiple job descriptions detected ({job_count} jobs).\n"
        "Your goal is to produce ONE optimized CV that maximizes the probability "
        "of matching across ALL job descriptions. Prioritize keywords and "
        "requirements that appear in more than one job. Do NOT produce separate CVs."
    )


def build_system_context(prompt_text: str) -> str:
    """Scan the prompt and project for necessary files to inject as context."""
    context = "You are VITA, an expert AI agent that writes and adapts LaTeX CVs.\n"
    context += "Below is the context gathered from the user's local file system.\n\n"
    
    # Inject main.tex
    if Path("main.tex").exists():
        context += "==== FILE: main.tex ====\n"
        context += Path("main.tex").read_text(encoding="utf-8")
        context += "\n========================\n\n"
        
    # Inject job.md
    if Path("job.md").exists():
        job_text = Path("job.md").read_text(encoding="utf-8")
        formatted_jobs, job_count = format_job_descriptions(job_text)
        label = f"job.md ({job_count} jobs)" if job_count > 1 else "job.md"
        context += f"==== FILE: {label} ====\n"
        context += formatted_jobs
        context += "\n======================\n\n"
        
    # Inject referenced results (e.g. results/analysis.md used by adapt prompt)
    # Note: results are stored in .vita/results/ internally
    if "results/analysis.md" in prompt_text:
        res_file = Path(".vita") / "results" / "analyze.md"  # stored as analyze.md
        if res_file.exists():
            context += "==== FILE: results/analysis.md ====\n"
            context += res_file.read_text(encoding="utf-8")
            context += "\n===================================\n\n"
            
    # Inject referenced skills
    base_dir = Path(__file__).parent.parent
    skill_matches = set(re.findall(r"skills/[a-zA-Z0-9_-]+\.md", prompt_text))
    
    for skill_ref in skill_matches:
        skill_name = skill_ref.split("/")[1]
        skill_path = base_dir / "assets" / "skills" / skill_name
        if skill_path.exists():
            context += f"==== SKILL: {skill_name} ====\n"
            context += skill_path.read_text(encoding="utf-8")
            context += f"\n=============================\n\n"
            
    return context
