"""Task-scoped bundled and project-local writing skills."""

from pathlib import Path

TASK_SKILLS = {
    "analyze": ("job-description-analyzer.md",),
    "adapt": (
        "tech-resume-optimizer.md",
        "resume-bullet-writer.md",
        "resume-ats-optimizer.md",
        "resume-tailor.md",
    ),
    "review": ("resume-reviewer.md",),
    "cover": ("cover-letter-generator.md",),
}
SKILLS_DIR = Path(".vita") / "skills"
BUNDLED_SKILLS_DIR = Path(__file__).parent.parent / "assets" / "skills"


def skill_context(step: str) -> str:
    """Replace same-named bundled skills, then append other local Markdown files."""
    local_dir = SKILLS_DIR / step
    local = {
        path.name: path
        for path in sorted(local_dir.glob("*.md"))
        if path.is_file() and path.read_text(encoding="utf-8").strip()
    }
    selected = []
    for name in TASK_SKILLS[step]:
        selected.append(local.pop(name, BUNDLED_SKILLS_DIR / name))
    selected.extend(local.values())
    blocks = [
        "TASK SKILLS:\nApply these embedded definitions to the skill references in the "
        "current task; no separate skill-file lookup is needed. "
        "Project-local skills take precedence over bundled writing and style guidance. "
        "Keep factual accuracy, the requested language, and the task's output format."
    ]
    for path in selected:
        source = "PROJECT SKILL" if path.parent == local_dir else "SKILL"
        blocks.append(
            f"==== {source}: {path.as_posix()} ====\n"
            f"{path.read_text(encoding='utf-8').strip()}\n"
            "============================="
        )
    return "\n\n".join(blocks)
