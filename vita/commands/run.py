"""vita/commands/run.py — Chain all AI steps into a single command.

Usage:
  vita run          # run analyze → adapt → review, prompts only
  vita run --auto   # run autonomously using configured LLM
"""

from vita.commands.ai_step import run as ai_step_run


STEPS = ["analyze", "adapt", "review"]


def run(auto: bool = False, language: str = "en", provider: str | None = None) -> None:
    """Execute analyze → adapt → review in sequence."""
    print(f"\n{'='*60}")
    print(f"  VITA Pipeline — {'Autonomous' if auto else 'Prompt'} Mode")
    print(f"  Steps: {' → '.join(STEPS)}")
    print(f"{'='*60}\n")

    for i, step in enumerate(STEPS, start=1):
        print(f"\n[{i}/{len(STEPS)}] Running step: {step.upper()}")
        print(f"{'─'*40}")
        lang = language if step == "adapt" else None
        ai_step_run(step, language=lang, auto=auto, provider=provider)
        
    print(f"\n{'='*60}")
    if auto:
        print("✅ Pipeline complete!")
        print("   → .vita/results/analyze.md — gap analysis")
        print("   → main.tex                 — adapted CV")
        print("   → .vita/results/review.md  — final review")
    else:
        print("✅ All prompts generated!")
        print("   → .vita/current_prompt.md  — last prompt (review)")
    print(f"{'='*60}\n")
