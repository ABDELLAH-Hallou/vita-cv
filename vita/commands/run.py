"""vita/commands/run.py — Chain all AI steps into a single command.

Usage:
  vita run          # run analyze → adapt → review → cover, prompts only
  vita run --auto   # run autonomously using configured LLM
"""

from pathlib import Path

from vita.commands.ai_step import run as ai_step_run
from vita.helpers import approval as approval_policy
from vita.helpers.diagnostics import diagnosed, failure
from vita.helpers.job_extraction import read_job
from vita.helpers.pipeline_config import load_pipeline_settings
from vita.helpers.requirements import active_requirements

STEPS = ["analyze", "adapt", "review", "cover"]


@diagnosed("workflow")
def run(auto: bool = False, language: str = "en", provider: str | None = None,
        approval: str = "auto", resume: bool = False, authorization=None) -> bool:
    """Execute analyze → adapt → review → cover in sequence."""
    try:
        approval_policy.policy(approval)
        if approval == "unattended" or resume or (approval == "human" and auto):
            if not auto:
                raise ValueError("Unattended/resume requires --auto")
            return _durable_run(language, provider, approval, resume, authorization)
        if authorization is not None:
            raise ValueError("Authorization requires explicit unattended policy")
        settings = load_pipeline_settings()
        approved = active_requirements(read_job()) if settings.extraction_enabled and Path("job.md").is_file() else None
    except (ValueError, OSError) as exc:
        failure("configuration", exc, category="configuration")
        print("Invalid pipeline configuration. See execution diagnostics.")
        return False
    steps = (["extract"] if settings.extraction_enabled and approved is None else []) + STEPS
    print(f"\n{'='*60}")
    print(f"  VITA Pipeline — {'Autonomous' if auto else 'Prompt'} Mode")
    print(f"  Steps: {' → '.join(steps)}")
    print(f"{'='*60}\n")

    for i, step in enumerate(steps, start=1):
        print(f"\n[{i}/{len(steps)}] Running step: {step.upper()}")
        print(f"{'─'*40}")
        lang = language if step in ("adapt", "cover") else None
        selected_provider = None if step == "extract" else provider
        options = {"approval": approval} if approval != "auto" else {}
        if ai_step_run(step, language=lang, auto=auto, provider=selected_provider, **options) is False:
            print(f"Pipeline stopped: {step} failed. Later steps were not run.")
            return False
        
    print(f"\n{'='*60}")
    if auto:
        print("✅ Pipeline complete!")
        print("   → .vita/results/analysis.json + analysis.md — initial evaluation")
        print("   → main.tex                 — current CV after the adapt step")
        print("   → .vita/results/review.json + review.md — final evaluation")
        print("   → .vita/results/delta.json + delta.md — comparable score changes")
        print("   → .vita/results/cover.md   — cover letter report")
        print("   → Cover letter LaTeX source ready; run `vita build both` for both PDFs.")
    else:
        instructions = (
            "Execute these task prompts in order. After each task, save its outputs "
            "before reading the next prompt. Read the CV from disk again for each task "
            "so the cover letter uses the adapted CV. Stop if a task fails.\n\n"
            + "\n".join(f"{i}. Read and execute `.vita/prompts/{step}.md`." for i, step in enumerate(steps, 1))
        )
        (Path(".vita") / "current_prompt.md").write_text(instructions, encoding="utf-8")
        print("✅ All prompts generated!")
        print("   → .vita/current_prompt.md  — instructions for the complete workflow")
        print("   → .vita/prompts/           — individual task prompts with custom skills")
    print(f"{'='*60}\n")
    return True


def _durable_run(language, provider, approval, resume, authorization):
    """Use the same checkpoint/approval engine as isolated Jobenu workspaces."""
    from vita.helpers import batch_import

    path = Path(".vita/workflow.json")
    with batch_import.locked(Path.cwd()):
        state = batch_import._read(path) if resume else None
        if resume and state is None:
            raise ValueError("No workflow checkpoint to resume")
        if state is None:
            previous = batch_import._read(path)
            if previous:
                import uuid
                batch_import._save(Path(".vita/workflows") / (uuid.uuid4().hex + ".json"), previous)
            state = {"workspace": str(Path.cwd()), "status": "imported", "completed_steps": []}
            if authorization is not None:
                state["authorization"] = authorization
                state["approval_policy"] = approval_policy.policy(approval)
        options = {"language": language, "provider": provider, "approval": approval}
        try:
            batch_import.execute(state, options, lambda: batch_import._save(path, state))
        except (ValueError, OSError, RuntimeError):
            state["status"] = "failed"
            batch_import._save(path, state)
            raise
        print(f"Workflow: {state['status']}. Checkpoint: {path}")
        return state["status"] == "complete"
