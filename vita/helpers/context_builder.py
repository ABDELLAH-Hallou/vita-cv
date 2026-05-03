"""vita/helpers/context_builder.py — Packages local files into LLM context."""
import re
from pathlib import Path

def build_system_context(prompt_text: str) -> str:
    """Scan the prompt and project for necessary files to inject as context."""
    context = "You are VITA, an expert AI agent that writes and adapts LaTeX CVs.\n"
    context += "Below is the context gathered from the user's local file system.\n\n"
    
    # Inject main.tex
    if Path("main.tex").exists():
        context += "==== FILE: main.tex ====\n"
        context += Path("main.tex").read_text(encoding="utf-8")
        context += "\n========================\n\n"
        
    # Inject job.md
    if Path("job.md").exists():
        context += "==== FILE: job.md ====\n"
        context += Path("job.md").read_text(encoding="utf-8")
        context += "\n======================\n\n"
        
    # Inject referenced results (e.g. results/analysis.md used by adapt prompt)
    # Note: results are stored in .vita/results/ internally
    if "results/analysis.md" in prompt_text:
        res_file = Path(".vita") / "results" / "analyze.md"  # stored as analyze.md
        if res_file.exists():
            context += "==== FILE: results/analysis.md ====\n"
            context += res_file.read_text(encoding="utf-8")
            context += "\n===================================\n\n"
            
    # Inject referenced skills
    base_dir = Path(__file__).parent.parent
    skill_matches = set(re.findall(r"skills/[a-zA-Z0-9_-]+\.md", prompt_text))
    
    for skill_ref in skill_matches:
        skill_name = skill_ref.split("/")[1]
        skill_path = base_dir / "assets" / "skills" / skill_name
        if skill_path.exists():
            context += f"==== SKILL: {skill_name} ====\n"
            context += skill_path.read_text(encoding="utf-8")
            context += f"\n=============================\n\n"
            
    return context
