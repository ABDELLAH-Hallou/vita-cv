import re
from pathlib import Path

from vita.helpers import approval as approval_policy
from vita.helpers.assessment import run_assessment
from vita.helpers.config import load_config
from vita.helpers.context_builder import (
    build_system_context,
    current_date_instruction,
    cv_knowledge_instruction,
    multi_job_instruction,
)
from vita.helpers.diagnostics import diagnosed, failure, journal, local_artifact
from vita.helpers.extensions import merged_language_map
from vita.helpers.factual_changes import capture, guard, instruction, resume_unattended, stage
from vita.helpers.job_extraction import extract, prepare_job
from vita.helpers.llm import generate as llm_generate
from vita.helpers.pipeline_config import load_pipeline_settings
from vita.helpers.skills import skill_context
from vita.helpers.structured import json_text, write_artifact
from vita.helpers.structured_output import run_text

# ── Built-in language codes ───────────────────────────────────────────────────
# Users can extend this via .vita/extensions.json ("language_map" key).

_BUILTIN_LANGUAGE_MAP: dict[str, str] = {
    "en": "English",
    "fr": "French",
    "ar": "Arabic",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese",
}

@diagnosed()
def run(
    step: str,
    language: str = None,
    auto: bool = False,
    provider: str | None = None,
    reassess: bool = False,
    qualitative: bool = False,
    approval: str = "auto",
    authorization=None,
) -> bool:
    approval_policy.policy(approval)
    if step == "extract":
        return extract(auto=auto, provider=provider)
    try:
        if approval == "unattended":
            if not auto:
                raise ValueError("--approval unattended requires --auto; generated prompts cannot carry consent")
            authorization = authorization or approval_policy.capture(approval)
            approval_policy.assert_authorized(authorization)
            from vita.commands.requirements import ensure_unattended
            ensure_unattended(authorization)
            if step == "cover":
                from vita.helpers.factual_changes import RESULTS, assert_applied_current, load
                if (RESULTS / "adapt.facts.json").exists():
                    report = load("adapt")
                    if report["status"] in ("approved", "applied"):
                        assert_applied_current(report)
            if step in ("adapt", "cover") and resume_unattended(step, authorization):
                return True
        elif authorization is not None:
            raise ValueError("Authorization requires explicit unattended policy")
        settings = load_pipeline_settings()
        job = prepare_job(settings, auto=auto)
    except (ValueError, OSError, RuntimeError) as exc:
        failure("context", exc, category="validation_error")
        print("Cannot prepare job criteria. See execution diagnostics for the failed phase.")
        return False
    config = load_config()
    resume_entry = config.get("tex_entry", "main.tex")
    cover_entry = config.get("cover_tex_entry", "cover-letter.tex")
    if step in ("review", "cover") and not guard(("adapt",)):
        return False
    if step in ("analyze", "review"):
        return run_assessment(step, job, settings=settings, resume_entry=resume_entry,
                              generate=llm_generate, auto=auto, provider=provider,
                              reassess=reassess, qualitative=qualitative)
    if step == "cover":
        if not Path(resume_entry).is_file():
            print(f"CV source not found: '{resume_entry}'. Create or adapt the CV first.")
            return False
        if Path(cover_entry).resolve() == Path(resume_entry).resolve():
            print("'cover_tex_entry' must differ from 'tex_entry'.")
            return False
    base_dir = Path(__file__).parent.parent
    prompt_file = base_dir / "assets" / "prompts" / f"{step}.md"
    
    if not prompt_file.exists():
        local_prompt_file = Path("prompts") / f"{step}.md"
        if local_prompt_file.exists():
            prompt_file = local_prompt_file
        else:
            print(f"'{prompt_file}' not found.")
            return False

    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    job_text = job.text
    if not auto and settings.extraction_enabled and job.requirements is None:
        job_text = (
            "At execution time, read .vita/results/job.json and job.toon produced by extraction. "
            f"Require job.json source_sha256={job.source_sha256}; use its TOON representation. "
            "If no matching validated extraction exists, read the raw job.md."
        )
    if "{{JOB_DESCRIPTION}}" not in prompt_text:
        prompt_text += "\n\nJOB CRITERIA:\n{{JOB_DESCRIPTION}}"
    prompt_text = prompt_text.replace("{{JOB_DESCRIPTION}}", job_text)
    if len(job.ids) > 1:
        document = "cover letter" if step == "cover" else "CV"
        prompt_text += multi_job_instruction(len(job.ids), document)

    if step == "adapt" and language:
        language_map = merged_language_map(_BUILTIN_LANGUAGE_MAP)
        target_lang = language_map.get(language.lower(), language)
        prompt_text += (
            f"\n\nCRITICAL LANGUAGE INSTRUCTION:\n"
            f"The entire CV must be written in **{target_lang}**.\n"
            "Translate every human-readable CV string in `main.tex`, including all headings, "
            "the title/headline, professional summary, experience, education, projects, "
            "publications/articles, skills, awards, volunteering, custom sections, labels, "
            "and short helper text. Translate human-readable text inside LaTeX macro arguments too.\n"
            "Translation applies to the whole document, even where job-tailoring instructions "
            "focus on particular sections. Do not leave untranslated source-language prose "
            "in sections outside that tailoring focus.\n"
            "Preserve LaTeX commands, environments, formatting macros, layout, document structure, "
            "URLs, email addresses, citation keys, and LaTeX label/reference keys. Preserve all "
            "factual information, including dates, metrics, and qualifications. Keep proper nouns "
            "such as personal, company, product, and official certification names unchanged when "
            "appropriate, along with technical terms conventionally retained in the target language."
            " Translate prose in every captured input/include file as well. Preserve every employment "
            "history entry, qualification, date, metric and unit; never silently shorten history to "
            "satisfy an input/output context limit. If the complete document cannot fit, stop and "
            "report the limit instead of returning a partial CV. For Arabic/RTL, preserve logical "
            "reading order and mixed-direction names, dates and URLs; report required Unicode engine "
            "and fonts rather than silently dropping unsupported characters."
        )

    if step == "cover":
        language_map = merged_language_map(_BUILTIN_LANGUAGE_MAP)
        target_lang = language_map.get((language or "en").lower(), language or "English")
        prompt_text += (
            f"\n\nCRITICAL LANGUAGE INSTRUCTION:\n"
            f"The entire cover letter must be written in **{target_lang}**, including "
            "the salutation, date, subject, body, and sign-off. Preserve proper nouns "
            "and technical terms normally kept in their original language."
        )

    if step in ("adapt", "cover"):
        prompt_text += cv_knowledge_instruction()

    prompt_text += current_date_instruction()
    if step in ("adapt", "cover"):
        prompt_text += instruction(step, auto=auto, approval_mode=approval)
    prompt_text = prompt_text.replace("`main.tex`", f"`{resume_entry}`")
    prompt_text = prompt_text.replace("`cover-letter.tex`", f"`{cover_entry}`")

    if not auto:
        prompt_text = skill_context(step) + "\n\n==== TASK ====\n" + prompt_text
        local_artifact("generated-prompt", prompt_text)
        print(f"\n{'='*60}")
        print(f"AI Prompt for '{step}'")
        print(f"{'='*60}\n")
        print(prompt_text)
        print(f"\n{'='*60}")
        
        out_file = Path(".vita") / "current_prompt.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        write_artifact(out_file, prompt_text)
        task_prompt = Path(".vita") / "prompts" / f"{step}.md"
        task_prompt.parent.mkdir(parents=True, exist_ok=True)
        write_artifact(task_prompt, prompt_text)
            
        print(f"Generated prompt saved to {out_file}.")
        print(f"Tell your AI assistant: \"Execute what is in {out_file}\"\n")
        return True

    # ── Auto Execution ────────────────────────────────────────────────────────
    print(f"🚀 Running '{step}' autonomously...")
    try:
        factual_context = capture(step) if step in ("adapt", "cover") else None
    except (ValueError, OSError) as exc:
        failure("context", exc, category="validation_error")
        print("Cannot capture factual sources. Check the CV, included files, and document configuration.")
        return False
    if factual_context:
        prompt_text += "\n\nCAPTURED FACTUAL SOURCES (identity and text, not proof of equivalence):\n" + json_text(factual_context["candidate_sources"])
    system_context = build_system_context(
        prompt_text, step=step, resume_entry=resume_entry, include_job=False,
    )
    
    # Override prompt instructions for autonomous mode
    # Strip mentions of 'save' since the LLM can't do it — we do it instead.
    prompt_text += "\n\n---\nNOTE: You are running in autonomous API mode. VITA will handle all file saving."
    prompt_text += " Do NOT include instructions about saving files in your response."
    
    if step in ("adapt", "cover"):
        target = cover_entry if step == "cover" else resume_entry
        prompt_text += f"\nYou MUST output the complete {target} file in exactly one ```latex code block."
        if step == "adapt":
            prompt_text += ("\nThe returned file must contain translated content from all captured input/include "
                            "files inline, because this response can replace only the entry file. Do not leave "
                            "prose in unchanged includes. Preserve source history and all protected facts.")
        prompt_text += "\nBefore the code block, write a short summary of the changes you made."

    results_dir = Path(".vita") / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    try:
        response = run_text(step=step, generate=llm_generate, system=system_context,
                            prompt=prompt_text, route=settings.route(step, provider).kwargs())
    except Exception as exc:
        failure("provider_request", exc)
        print("Failed to run AI. See execution diagnostics for the failed phase and provider category.")
        return False
    
    if step in ("adapt", "cover"):
        # Extract latex
        pattern = r"```latex[^\S\r\n]*\r?\n(.*?)\r?\n```"
        matches = list(re.finditer(pattern, response, re.DOTALL))
        new_tex = matches[0].group(1).strip() if len(matches) == 1 else ""
        valid = bool(new_tex)
        standalone = step == "cover" or r"\begin{document}" in (factual_context["target_before"] or "")
        if standalone:
            valid = valid and all(
                marker in new_tex
                for marker in (r"\documentclass", r"\begin{document}", r"\end{document}")
            )
        if not valid:
            journal("validation.document_rejected", level="ERROR", target=target,
                    latex_block_count=len(matches), reason="Expected one nonempty LaTeX block; cover requires a standalone document.")
            failure("validation", category="validation_error")
            write_artifact(results_dir / f"{step}.md", response)
            print(f"⚠️ The AI did not return one valid LaTeX document. '{target}' was not updated.")
            return False
        try:
            if approval == "unattended":
                applied = stage(factual_context, new_tex, authorization=authorization)
            else:
                applied = (stage(factual_context, new_tex, require_approval=True)
                           if approval == "human" else stage(factual_context, new_tex))
            if not applied:
                write_artifact(results_dir / f"{step}.md", "Document not applied: confirmation required. See " + f"{step}.facts.md and {step}.facts.json.\n")
                return False
        except (ValueError, OSError) as exc:
            failure("persistence" if isinstance(exc, OSError) else "validation", exc, category="artifact_error" if isinstance(exc, OSError) else "validation_error")
            print("Factual-change validation or persistence failed; inspect sources and the proposal before retrying.")
            return False
        print(f"✅ Successfully updated {target}!")
        summary = re.sub(pattern, "", response, flags=re.DOTALL).strip()
        if approval == "unattended":
            summary = (approval_policy.WARNING + "\n\nApproval source: unattended_run_policy. "
                       "See the exact revision and unverified changes in " + f"{step}.facts.md.\n\n"
                       + summary)

        summary_file = results_dir / f"{step}.md"
        write_artifact(summary_file, summary)
        print(f"📝 Summary saved to {summary_file}")
        
    else:
        out_file = results_dir / f"{step}.md"
        write_artifact(out_file, response.strip())
        print(f"✅ AI Report saved to {out_file}")
    return True

