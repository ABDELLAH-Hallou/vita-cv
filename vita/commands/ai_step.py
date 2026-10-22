import re
from pathlib import Path

from vita.helpers.config import load_config
from vita.helpers.context_builder import (
    build_system_context,
    current_date_instruction,
    cv_knowledge_instruction,
    multi_job_instruction,
)
from vita.helpers.evaluation import (
    compute_delta,
    evaluation_instruction,
    finalize,
    load_baseline,
    save_delta,
    save_evaluation,
)
from vita.helpers.extensions import merged_language_map
from vita.helpers.job_extraction import extract, prepare_job
from vita.helpers.llm import generate as llm_generate
from vita.helpers.pipeline_config import load_pipeline_settings
from vita.helpers.skills import skill_context
from vita.helpers.structured import EVALUATION_OUTPUT_SCHEMA, json_text
from vita.helpers.structured_output import StructuredOutputError, run_structured

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

def run(
    step: str,
    language: str = None,
    auto: bool = False,
    provider: str | None = None,
) -> bool:
    if step == "extract":
        return extract(auto=auto, provider=provider)
    try:
        settings = load_pipeline_settings()
        job = prepare_job(settings, auto=auto)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Cannot prepare job criteria: {exc}")
        return False
    config = load_config()
    resume_entry = config.get("tex_entry", "main.tex")
    cover_entry = config.get("cover_tex_entry", "cover-letter.tex")
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

    baseline = load_baseline(job) if step == "review" else None
    if step in ("analyze", "review"):
        prompt_text += evaluation_instruction(step, job, baseline if auto else None)

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
    prompt_text = prompt_text.replace("`main.tex`", f"`{resume_entry}`")
    prompt_text = prompt_text.replace("`cover-letter.tex`", f"`{cover_entry}`")

    if not auto:
        if step in ("analyze", "review"):
            prompt_text += (
                "\nAt execution time prepare the current job context with "
                "vita.helpers.job_extraction.prepare_job. For review, load the matching "
                "analysis.json with load_baseline and preserve its locked criteria. "
                "Use vita.helpers.evaluation.finalize and save_evaluation to validate and save "
                "both JSON and Markdown. For a matching review, use compute_delta and save_delta. "
                "Do not hand-edit provenance hashes or numeric scores."
            )
        prompt_text = skill_context(step) + "\n\n==== TASK ====\n" + prompt_text
        print(f"\n{'='*60}")
        print(f"AI Prompt for '{step}'")
        print(f"{'='*60}\n")
        print(prompt_text)
        print(f"\n{'='*60}")
        
        out_file = Path(".vita") / "current_prompt.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(prompt_text)
        task_prompt = Path(".vita") / "prompts" / f"{step}.md"
        task_prompt.parent.mkdir(parents=True, exist_ok=True)
        task_prompt.write_text(prompt_text, encoding="utf-8")
            
        print(f"Generated prompt saved to {out_file}.")
        print(f"Tell your AI assistant: \"Execute what is in {out_file}\"\n")
        return True

    # ── Auto Execution ────────────────────────────────────────────────────────
    print(f"🚀 Running '{step}' autonomously...")
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
        prompt_text += "\nBefore the code block, write a short summary of the changes you made."
    elif step in ("analyze", "review"):
        prompt_text += "\nReturn only the evaluation JSON. VITA writes both JSON and Markdown."

    results_dir = Path(".vita") / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    if step in ("analyze", "review"):
        def save(report):
            delta = compute_delta(baseline, report) if baseline else None
            save_evaluation(step, report)
            if delta is not None:
                save_delta(delta)
            else:
                # A new baseline or an unrelated review invalidates the old comparison.
                for extension in ("json", "md"):
                    (results_dir / f"delta.{extension}").unlink(missing_ok=True)

        try:
            run_structured(
                step=step, generate=llm_generate, system=system_context, prompt=prompt_text,
                route=settings.route(step, provider).kwargs(), schema=EVALUATION_OUTPUT_SCHEMA,
                finalize=lambda data: finalize(json_text(data), job, baseline, step=step), save=save,
            )
            print(f"Validated {step} saved as JSON and Markdown in {results_dir}")
            return True
        except (StructuredOutputError, ValueError, OSError, KeyError, TypeError) as exc:
            print(f"Could not validate or save {step} evaluation: {exc}")
            return False

    try:
        response = llm_generate(system_context, prompt_text, **settings.route(step, provider).kwargs())
    except Exception as e:
        print(f"❌ Failed to run AI: {e}")
        return False
    
    if step in ("adapt", "cover"):
        # Extract latex
        pattern = r"```latex[^\S\r\n]*\r?\n(.*?)\r?\n```"
        matches = list(re.finditer(pattern, response, re.DOTALL))
        new_tex = matches[0].group(1).strip() if len(matches) == 1 else ""
        valid = bool(new_tex)
        if step == "cover":
            valid = valid and all(
                marker in new_tex
                for marker in (r"\documentclass", r"\begin{document}", r"\end{document}")
            )
        if not valid:
            (results_dir / f"{step}.md").write_text(response, encoding="utf-8")
            print(f"⚠️ The AI did not return one valid LaTeX document. '{target}' was not updated.")
            return False
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(new_tex, encoding="utf-8")
        print(f"✅ Successfully updated {target}!")
        summary = re.sub(pattern, "", response, flags=re.DOTALL).strip()

        summary_file = results_dir / f"{step}.md"
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"📝 Summary saved to {summary_file}")
        
    else:
        out_file = results_dir / f"{step}.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(response.strip())
        print(f"✅ AI Report saved to {out_file}")
    return True

