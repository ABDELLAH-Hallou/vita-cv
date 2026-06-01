import re
from pathlib import Path
from vita.helpers.extensions import merged_language_map
from vita.helpers.context_builder import (
    build_system_context,
    format_job_descriptions,
    multi_job_instruction,
)
from vita.helpers.llm import generate as llm_generate

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
) -> None:
    base_dir = Path(__file__).parent.parent
    prompt_file = base_dir / "assets" / "prompts" / f"{step}.md"
    
    if not prompt_file.exists():
        local_prompt_file = Path("prompts") / f"{step}.md"
        if local_prompt_file.exists():
            prompt_file = local_prompt_file
        else:
            print(f"'{prompt_file}' not found.")
            return

    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    job_count = 0
    if "{{JOB_DESCRIPTION}}" in prompt_text:
        job_file = Path("job.md")
        if not job_file.exists():
            print("'job.md' not found. Creating an empty 'job.md'.")
            print("Please paste the job description into 'job.md' and run this command again.")
            job_file.write_text("", encoding="utf-8")
            return
        
        with open(job_file, "r", encoding="utf-8") as f:
            job_text = f.read().strip()

        formatted_jobs, job_count = format_job_descriptions(job_text)
        prompt_text = prompt_text.replace("{{JOB_DESCRIPTION}}", formatted_jobs)
        if job_count > 1:
            prompt_text += multi_job_instruction(job_count)

    if step == "adapt" and language and language.lower() != "en":
        language_map = merged_language_map(_BUILTIN_LANGUAGE_MAP)
        target_lang = language_map.get(language.lower(), language)
        prompt_text += f"\n\nCRITICAL LANGUAGE INSTRUCTION:\nThe tailored CV content you write must be translated and written ENTIRELY in **{target_lang}**.\nDo NOT leave the bullet points in English unless the job description explicitly asks for it."

    if not auto:
        print(f"\n{'='*60}")
        print(f"AI Prompt for '{step}'")
        print(f"{'='*60}\n")
        print(prompt_text)
        print(f"\n{'='*60}")
        
        out_file = Path(".vita") / "current_prompt.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(prompt_text)
            
        print(f"Generated prompt saved to {out_file}.")
        print(f"Tell your AI assistant: \"Execute what is in {out_file}\"\n")
        return

    # ── Auto Execution ────────────────────────────────────────────────────────
    print(f"🚀 Running '{step}' autonomously...")
    system_context = build_system_context(prompt_text)
    
    # Override prompt instructions for autonomous mode
    # Strip mentions of 'save' since the LLM can't do it — we do it instead.
    prompt_text += "\n\n---\nNOTE: You are running in autonomous API mode. VITA will handle all file saving."
    prompt_text += " Do NOT include instructions about saving files in your response."
    
    if step == "adapt":
        prompt_text += "\nYou MUST output the complete, updated main.tex file enclosed in a ```latex code block."
        prompt_text += "\nBefore the code block, write a short summary of the changes you made."
    elif step == "analyze":
        prompt_text += "\nOutput your full gap analysis and match score as a markdown report. No code blocks needed."
    elif step == "review":
        prompt_text += "\nOutput your full CV review as a markdown report. No code blocks needed."

    try:
        response = llm_generate(system_context, prompt_text, provider=provider)
    except Exception as e:
        print(f"❌ Failed to run AI: {e}")
        return
        
    results_dir = Path(".vita") / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    
    if step == "adapt":
        # Extract latex
        match = re.search(r"```latex\n(.*?)\n```", response, re.DOTALL)
        if match:
            new_tex = match.group(1).strip()
            with open("main.tex", "w", encoding="utf-8") as f:
                f.write(new_tex)
            print("✅ Successfully updated main.tex!")
            
            # Remove the latex block to get the summary
            summary = re.sub(r"```latex\n.*?\n```", "", response, flags=re.DOTALL).strip()
        else:
            print("⚠️ The AI did not return a latex block. main.tex was not updated.")
            summary = response
            
        summary_file = results_dir / "adapt.md"
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"📝 Summary saved to {summary_file}")
        
    else:
        out_file = results_dir / f"{step}.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(response.strip())
        print(f"✅ AI Report saved to {out_file}")

