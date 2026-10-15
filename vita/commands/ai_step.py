import re
from pathlib import Path

from vita.helpers.config import load_config
from vita.helpers.context_builder import (
    build_system_context,
    current_date_instruction,
    cv_knowledge_instruction,
    format_job_descriptions,
    multi_job_instruction,
)
from vita.helpers.extensions import merged_language_map
from vita.helpers.llm import generate as llm_generate
from vita.helpers.skills import skill_context

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

    job_count = 0
    if "{{JOB_DESCRIPTION}}" in prompt_text:
        job_file = Path("job.md")
        if not job_file.exists():
            print("'job.md' not found. Creating an empty 'job.md'.")
            print("Please paste the job description into 'job.md' and run this command again.")
            job_file.write_text("", encoding="utf-8")
            return False
        
        with open(job_file, "r", encoding="utf-8") as f:
            job_text = f.read().strip()
        if not job_text:
            print("'job.md' is empty. Add a job description before running this task.")
            return False

        formatted_jobs, job_count = format_job_descriptions(job_text)
        prompt_text = prompt_text.replace("{{JOB_DESCRIPTION}}", formatted_jobs)
        if job_count > 1:
            document = "cover letter" if step == "cover" else "CV"
            prompt_text += multi_job_instruction(job_count, document)

    if step == "adapt" and language:
        language_map = merged_language_map(_BUILTIN_LANGUAGE_MAP)
        target_lang = language_map.get(language.lower(), language)
        prompt_text += (
            f"\n\nCRITICAL LANGUAGE INSTRUCTION:\n"
            f"The entire CV must be written in **{target_lang}**.\n"
            "Translate every human-readable CV string in `main.tex`, including the title/headline, "
            "professional summary, section headings, experience bullets, project descriptions, "
            "education details, skills, labels, and any short helper text.\n"
            "Preserve LaTeX commands, environments, formatting macros, URLs, email addresses, "
            "company names, product names, certificate/certification names, proper nouns, and "
            "technical keywords that are normally kept in English in the target language.\n"
            "Do NOT leave English sections behind unless the job description explicitly requires "
            "those exact words to remain in English."
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
    system_context = build_system_context(prompt_text, step=step, resume_entry=resume_entry)
    
    # Override prompt instructions for autonomous mode
    # Strip mentions of 'save' since the LLM can't do it — we do it instead.
    prompt_text += "\n\n---\nNOTE: You are running in autonomous API mode. VITA will handle all file saving."
    prompt_text += " Do NOT include instructions about saving files in your response."
    
    if step in ("adapt", "cover"):
        target = cover_entry if step == "cover" else resume_entry
        prompt_text += f"\nYou MUST output the complete {target} file in exactly one ```latex code block."
        prompt_text += "\nBefore the code block, write a short summary of the changes you made."
    elif step == "analyze":
        prompt_text += "\nOutput your full gap analysis and match score as a markdown report. No code blocks needed."
    elif step == "review":
        prompt_text += "\nOutput your full CV review as a markdown report. No code blocks needed."

    try:
        response = llm_generate(system_context, prompt_text, provider=provider)
    except Exception as e:
        print(f"❌ Failed to run AI: {e}")
        return False
        
    results_dir = Path(".vita") / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    
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

