"""vita ai CLI commands for generating prompts."""

from pathlib import Path

LANGUAGE_MAP = {
    "en": "English",
    "fr": "French",
    "ar": "Arabic",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese"
}

def run(step: str, language: str = None) -> None:
    # Look for prompts in the package assets directory
    base_dir = Path(__file__).parent.parent
    prompt_file = base_dir / "assets" / "prompts" / f"{step}.md"
    
    if not prompt_file.exists():
        # Fallback to local prompts directory for development
        local_prompt_file = Path("prompts") / f"{step}.md"
        if local_prompt_file.exists():
            prompt_file = local_prompt_file
        else:
            print(f"❌ '{prompt_file}' not found.")
            return

    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    # Only load job.md if required by the template
    if "{{JOB_DESCRIPTION}}" in prompt_text:
        job_file = Path("job.md")
        if not job_file.exists():
            print("⚠️  'job.md' not found. Creating an empty 'job.md'.")
            print("    Please paste the job description into 'job.md' and run this command again.")
            job_file.write_text("Paste target job description here.", encoding="utf-8")
            return
        
        with open(job_file, "r", encoding="utf-8") as f:
            job_text = f.read().strip()
            
        prompt_text = prompt_text.replace("{{JOB_DESCRIPTION}}", job_text)

    # Inject translation instructions if requested
    if step == "adapt" and language and language.lower() != "en":
        target_lang = LANGUAGE_MAP.get(language.lower(), language)
        prompt_text += f"\n\n🚨 CRITICAL LANGUAGE INSTRUCTION:\nThe tailored CV content you write must be translated and written ENTIRELY in **{target_lang}**.\nDo NOT leave the bullet points in English unless the job description explicitly asks for it."

    # Output to terminal
    print(f"\n{'='*60}")
    print(f"✨ AI Prompt for '{step}' ✨")
    print(f"{'='*60}\n")
    print(prompt_text)
    print(f"\n{'='*60}")
    
    # Save to file
    out_file = Path(".vita") / "current_prompt.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(prompt_text)
        
    print(f"✅ Generated prompt saved to {out_file}.")
    print(f"   Tell your AI assistant: \"Execute what is in {out_file}\"\n")
