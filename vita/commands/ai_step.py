from pathlib import Path
from vita.helpers.extensions import merged_language_map

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

def run(step: str, language: str = None) -> None:
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

    if "{{JOB_DESCRIPTION}}" in prompt_text:
        job_file = Path("job.md")
        if not job_file.exists():
            print("'job.md' not found. Creating an empty 'job.md'.")
            print("Please paste the job description into 'job.md' and run this command again.")
            job_file.write_text("", encoding="utf-8")
            return
        
        with open(job_file, "r", encoding="utf-8") as f:
            job_text = f.read().strip()
            
        prompt_text = prompt_text.replace("{{JOB_DESCRIPTION}}", job_text)

    if step == "adapt" and language and language.lower() != "en":
        language_map = merged_language_map(_BUILTIN_LANGUAGE_MAP)
        target_lang = language_map.get(language.lower(), language)
        prompt_text += f"\n\nCRITICAL LANGUAGE INSTRUCTION:\nThe tailored CV content you write must be translated and written ENTIRELY in **{target_lang}**.\nDo NOT leave the bullet points in English unless the job description explicitly asks for it."

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
