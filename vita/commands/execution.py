"""Machine-readable host outcomes; provider prose never supplies approval."""

import contextlib
import io
import json
from pathlib import Path

from vita.helpers import approval
from vita.helpers.structured import write_artifact


def invoke(function, step, *, as_json=False, **options):
    mode = options.get("approval", "auto")
    authorization = None
    result = {"schema_version": 1, "step": step, "approval_policy": approval.policy(mode),
              "status": "failed", "authorization": None,
              "warning": approval.WARNING if mode == "unattended" else None}
    try:
        if mode == "unattended" and step != "run":
            authorization = approval.capture(mode)
            options["authorization"] = authorization
        if mode == "unattended" and not as_json:
            print(approval.WARNING)
        with contextlib.redirect_stdout(io.StringIO()) if as_json else contextlib.nullcontext():
            success = function(**options)
        result["status"] = "complete" if success else "failed"
        if step == "run" and Path(".vita/workflow.json").exists() and (mode != "auto" or options.get("resume")):
            state = json.loads(Path(".vita/workflow.json").read_text(encoding="utf-8"))
            if state.get("approval_policy") == approval.policy(mode):
                status = state["status"]
                result["status"] = status if success or status in ("failed", "rejected", "awaiting_approval", "awaiting_requirements_approval") else "failed"
                authorization = state.get("authorization")
        result["authorization"] = authorization
    except (ValueError, OSError, RuntimeError):
        success = False
    if not success:
        result["action"] = "Inspect the project diagnostics, checkpoint, and exact factual/requirement revision before retrying."
    result["exit_code"] = 0 if success else 1
    write_artifact(Path(f".vita/results/{step}.execution.json"), json.dumps(result, indent=2) + "\n")
    if as_json:
        print(json.dumps(result, indent=2))
    return success


def capabilities():
    return {"schema_version": 1, "policy_version": approval.VERSION,
            "modes": [
                {"id": "human", "description": "Explicit review before applying proposals"},
                {"id": "auto", "description": "Apply only changes allowed by host verification"},
                {"id": "unattended", "description": approval.WARNING}],
            "requires_explicit_selection": ["unattended"],
            "unattended_requires_auto": ["run", "analyze", "adapt", "review", "cover"],
            "generated_prompt_consent": False}
