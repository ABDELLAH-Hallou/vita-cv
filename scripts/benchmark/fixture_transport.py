"""Synthetic wire responses. Never used by the product or by live runs."""

import json
from pathlib import Path

from vita.helpers import evaluation, requirements
from vita.helpers.structured import CATEGORIES


def answer(prompt):
    if "RAW JOB DESCRIPTION:" in prompt and "source_sha256 to " in prompt:
        digest = prompt.split("source_sha256 to ", 1)[1].split(".", 1)[0]
        return json.dumps({"schema_version": 1, "source_sha256": digest, "jobs": [{
            "id": "job-1", "title": "Senior Marketing Manager", "company": "Example Works",
            "location": "Remote, France", "date_posted": None, "hard_skills": ["Python"],
            "soft_skills": [], "requirements": {"must_have": ["Python production experience"],
                                                "nice_to_have": []},
            "responsibilities": ["Build and maintain Python services"],
            "summary": "Title/body role conflict: Marketing Manager title, Python Engineer body.",
        }]})
    marker = "CAPTURED CANDIDATE SOURCES (the only eligible assessment evidence):\n"
    if marker in prompt:
        snapshot, _ = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())
        approved = requirements.active_requirements(Path("job.md").read_text(encoding="utf-8"))
        if approved:
            units = approved["requirements"]
        elif Path(".vita/results/analysis.json").exists():
            units = json.loads(Path(".vita/results/analysis.json").read_text(encoding="utf-8"))["metrics"]["criteria"]
        else:
            units = [{"id": "job-1-python", "job_id": "job-1", "category": "hard_skills",
                      "criterion": "Python production experience", "importance": "must_have"}]
        source = next(s for s in snapshot["sources"] if s["path"] == "main.tex")
        criteria = [{**{k: u[k] for k in evaluation.TAXONOMY_FIELDS}, "status": "partial",
                     "evidence": "Python engineer", "feedback": "Document production scope.",
                     "evidence_kind": "direct", "evidence_refs": [{"source_id": source["id"],
                         "quote": "Python engineer", "line_start": 4, "line_end": 4}]} for u in units]
        return json.dumps({"schema_version": 1, "overall_score": 50,
            "category_scores": {k: 50 if k == "hard_skills" else 0 for k in CATEGORIES},
            "executive_summary": "Python is documented; production scope is unclear.",
            "strengths": ["Python"], "gaps": ["Production scope"],
            "recommendations": ["Document production scope."],
            "metrics": {"criteria": criteria, "total_count": len(criteria),
                        "matched_count": 0, "partial_count": len(criteria), "missing_count": 0}})
    # A visible source edit exercises changed-source review and the factual gate.
    if "cover" in prompt.lower() and "letter" in prompt.lower():
        document = ("\\documentclass{article}\n\\begin{document}\nDear hiring team,\n"
                    "I build Python services. Thank you for your consideration.\n\\end{document}\n")
    else:
        document = Path("main.tex").read_text(encoding="utf-8").replace(
            "Python engineer", "Python engineer (service development)")
    return "```latex\n" + document + "\n```"


def envelope(provider, model, text):
    if provider in ("gemini", "google"):
        return {"modelVersion": model + "-fixture-snapshot", "usageMetadata": {
            "promptTokenCount": 11, "candidatesTokenCount": 7, "totalTokenCount": 18},
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}
    if provider == "anthropic":
        return {"model": model, "usage": {"input_tokens": 11, "output_tokens": 7},
                "stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}
    return {"model": model + "-fixture-snapshot", "usage": {
        "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        "choices": [{"finish_reason": "stop", "message": {"content": text}}]}
