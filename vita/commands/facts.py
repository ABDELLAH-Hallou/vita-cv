"""CLI transport for the factual-change contract; never calls a provider."""

import json
from pathlib import Path

from vita.helpers import factual_changes as facts
from vita.helpers.structured import parse_json


def run(action, step, *, revision=None, proposal=None, as_json=False, approval="auto"):
    try:
        if action == "capture":
            if not facts.guard(("adapt",) if step == "cover" else ()):
                return False
            context = facts.capture(step)
            facts._save(facts.ROOT / (step + ".capture.json"), context)
            print(
                f"Captured sources for {step}; generate a separate proposal, then use vita facts check."
            )
            return True
        if action == "check":
            context = parse_json(
                (facts.ROOT / (step + ".capture.json")).read_text(encoding="utf-8")
            )
            if context["step"] != step:
                raise ValueError("Mismatched captured step")
            if not Path(proposal).resolve().is_relative_to(Path.cwd().resolve()):
                raise ValueError("Proposal must be inside the project")
            if approval not in ("human", "auto"):
                raise ValueError("Deferred prompts cannot carry unattended authorization")
            options = {"require_approval": True} if approval == "human" else {}
            return facts.stage(context, Path(proposal).read_text(encoding="utf-8"), **options)
        if action in ("approve", "reject"):
            report = facts.decide(step, revision, action == "approve")
        else:
            report = facts.load(step)
        if as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"{step}: {report['status']} — {report['revision']}")
            for item in report["changes"]:
                print(f"{item['id']} [{item['verification']}] {item['reason']}")
                print(f"  Original: {item['original']}\n  Proposed: {item['proposed']}")
            if report["status"] == "confirmation_required":
                print(
                    "Review every item. To explicitly confirm all interpretations: "
                    f"vita facts approve {step} {report['revision']}; or use facts reject with the same arguments."
                )
        return True
    except (ValueError, OSError, KeyError, TypeError):
        message = "Cannot use factual-change proposal: missing, invalid, or stale sources/target/job/revision. Recapture and regenerate."
        print(
            json.dumps({"contract_version": facts.VERSION, "status": "error", "message": message})
            if as_json
            else message
        )
        return False
