"""Reviewable failed-step route amendments. Never rewrite captured checkpoints."""

import contextlib
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from vita.helpers import approval, batch_import, factual_changes
from vita.helpers import fallback as routing
from vita.helpers.provider_errors import TRANSIENT
from vita.helpers.structured import parse_json


def _locate():
    workspace = Path.cwd().resolve()
    path = workspace / ".vita/workflow.json"
    if path.exists():
        state = batch_import._read(path)
        if Path(state["workspace"]).resolve() != workspace:
            raise ValueError("Workflow belongs to a different workspace")
        return workspace, state, lambda: batch_import._save(path, state)
    for root in workspace.parents:
        path = batch_import.store(root) / "index.json"
        if not path.exists():
            continue
        index = batch_import._index(root)
        for app in index["applications"].values():
            for state in app["versions"].values():
                if Path(state["workspace"]).resolve() == workspace:
                    batch_import._owned_workspace(root, state)
                    return root, state, lambda path=path, index=index: batch_import._save(path, index)
    raise ValueError("No durable workflow found. Run in the returned Jobenu worktree or standalone workflow project.")


def _plan(state, step, policy):
    if state["status"] != "failed" or state.get("current_step") != step or state.get("pending"):
        raise ValueError("Only the current failed provider step can be amended; approval/rejected/published drafts need their existing resolution flow")
    if state.get("checkpoint") is None or state["checkpoint"] != batch_import._checkpoint():
        raise ValueError("Captured checkpoint is missing or stale. Restore dependencies; routing amendment cannot authorize stale reuse")
    job_hash = state.get("job_sha256")
    if job_hash is None and Path(".vita/results/analysis.json").exists():
        report = parse_json(Path(".vita/results/analysis.json").read_text(encoding="utf-8"))
        job_hash = report.get("metadata", {}).get("job_sha256")
    if job_hash != batch_import.digest(Path("job.md").read_text(encoding="utf-8")):
        raise ValueError("The saved job capture is missing or stale; no routing amendment may reuse it")
    outcome = parse_json(Path(f".vita/results/{step}.outcome.json").read_text(encoding="utf-8"))
    error = outcome.get("error") or {}
    if outcome.get("status") != "failed" or error.get("category") not in policy["categories"]:
        raise ValueError("Failure is not eligible under the new policy. Validation, source, approval and publication failures cannot be amended into fallback")
    if not factual_changes.guard(("adapt",) if step in ("review", "cover") else ()):
        raise ValueError("Resolve the factual-change contract before amending routing")
    if state.get("authorization"):
        approval.assert_authorized(state["authorization"])
    completed = state.get("completed_steps", [])
    if step in completed:
        raise ValueError("A completed step cannot be silently invalidated by a failed-step amendment")
    steps = state.get("steps", [])
    if step not in steps or completed != steps[:steps.index(step)]:
        raise ValueError("Completed stages are not a valid prefix of this failed workflow; inspect its dependencies before recovery")
    result = {"schema_version": 1, "version": routing.VERSION, "step": step,
              "previous_run_id": routing.outcome_view(step)["run_id"],
              "state_sha256": batch_import.digest(state), "checkpoint": state["checkpoint"],
              "old_policy": state.get("fallback_overrides", {}).get(step, routing.load_policy(step)),
              "new_policy": policy, "preserved_steps": completed,
              "invalidated_steps": [s for s in state.get("steps", []) if s not in completed]}
    result["plan_id"] = batch_import.digest(result)
    return result


def run(step, *, provider, model, reasoning_effort=None, categories=None, apply=False,
        plan_id=None, as_json=False):
    try:
        policy = {"version": routing.VERSION, "enabled": True,
                  "backup": {"provider": provider, "model": model},
                  "categories": sorted(set(categories.split(","))) if categories else sorted(TRANSIENT)}
        if reasoning_effort is not None:
            policy["backup"]["reasoning_effort"] = reasoning_effort
        routing.validate_policy(policy)
        root, state, persist = _locate()
        with batch_import.locked(root):
            fresh_root, state, persist = _locate()
            if root != fresh_root:
                raise ValueError("Workflow owner changed during amendment")
            with contextlib.redirect_stdout(io.StringIO()):
                planned = _plan(state, step, policy)
            if apply:
                if plan_id != planned["plan_id"]:
                    raise ValueError("Review the current amendment with --dry-run, then --apply --plan-id EXACT_ID")
                amendment = {**planned, "id": uuid.uuid4().hex,
                             "timestamp": datetime.now(timezone.utc).isoformat(),
                             "source": "explicit_routing_amendment"}
                # History and the original checkpoint stay intact. Resume will
                # recheck every dependency and repeat the explicit approval mode.
                batch_import._save(Path(".vita/routing-amendments") / (amendment["id"] + ".json"), amendment)
                state.setdefault("routing_amendments", []).append(amendment)
                state.setdefault("fallback_overrides", {})[step] = policy
                persist()
            result = {**planned, "status": "applied" if apply else "planned"}
        print(json.dumps(result, indent=2) if as_json else f"Routing amendment {result['status']}; plan ID: {result['plan_id']}")
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        result = {"schema_version": 1, "version": routing.VERSION, "status": "failed",
                  "action": "Run in the failed worktree, verify unchanged inputs and an eligible provider failure, then preview/apply the exact amendment plan. Inspect local diagnostics for details."}
        print(json.dumps(result, indent=2) if as_json else result["action"])
        return 1
