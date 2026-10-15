"""vita/commands/run.py — Chain all AI steps into a single command.

Usage:
  vita run          # run analyze → adapt → review → cover, prompts only
  vita run --auto   # run autonomously using configured LLM
"""

from pathlib import Path

from vita.commands.ai_step import run as ai_step_run

STEPS = ["analyze", "adapt", "review", "cover"]


def run(auto: bool = False, language: str = "en", provider: str | None = None) -> bool:
    """Execute analyze → adapt → review → cover in sequence."""
    print(f"\n{'='*60}")
    print(f"  VITA Pipeline — {'Autonomous' if auto else 'Prompt'} Mode")
    print(f"  Steps: {' → '.join(STEPS)}")
    print(f"{'='*60}\n")

    for i, step in enumerate(STEPS, start=1):
        print(f"\n[{i}/{len(STEPS)}] Running step: {step.upper()}")
        print(f"{'─'*40}")
        lang = language if step in ("adapt", "cover") else None
        if ai_step_run(step, language=lang, auto=auto, provider=provider) is False:
            print(f"Pipeline stopped: {step} failed. Later steps were not run.")
            return False
        
    print(f"\n{'='*60}")
    if auto:
        print("✅ Pipeline complete!")
        print("   → .vita/results/analyze.md — gap analysis")
        print("   → main.tex                 — adapted CV")
        print("   → .vita/results/review.md  — final review")
        print("   → .vita/results/cover.md   — cover letter report")
        print("   → Cover letter LaTeX source ready; run `vita build both` for both PDFs.")
    else:
        instructions = (
            "Execute these task prompts in order. After each task, save its outputs "
            "before reading the next prompt. Read the CV from disk again for each task "
            "so the cover letter uses the adapted CV. Stop if a task fails.\n\n"
            + "\n".join(f"{i}. Read and execute `.vita/prompts/{step}.md`." for i, step in enumerate(STEPS, 1))
        )
        (Path(".vita") / "current_prompt.md").write_text(instructions, encoding="utf-8")
        print("✅ All prompts generated!")
        print("   → .vita/current_prompt.md  — instructions for the complete workflow")
        print("   → .vita/prompts/           — individual task prompts with custom skills")
    print(f"{'='*60}\n")
    return True
