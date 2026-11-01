"""Jobenu JSON import CLI and stable plan/result envelopes for Vita Tree."""

import contextlib
import io
import json
import sys
from pathlib import Path

from vita.helpers import batch_import


def _emit(result, as_json):
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"Jobenu batch: {result['status']}")
    if "base_branch" in result:
        print(f"Base: {result['base_branch']} ({result['base_commit'][:12]})")
        print(f"Plan: {result['plan_id']}")
    for item in result.get("results", result.get("entries", [])):
        print(f"  {item['branch']}: {item.get('status', item['action'])}")
        if item.get("role_resolution") == "slug_fallback":
            print("    No short role alias matched. Add the full position title to .vita/extensions.json role_aliases to override it.")
        if item.get("workspace"):
            print(f"    Workspace: {item['workspace']}")
        if item.get("pending"):
            pending = item["pending"]
            print(f"    Review: vita facts show {pending['step']}")
            print(f"    Approve in that workspace: vita facts approve {pending['step']} {pending['revision']}")
        if item.get("pending_requirements"):
            print("    " + item["pending_requirements"])
        if item.get("error"):
            print("    " + item["error"])
    if result.get("skipped"):
        print(f"Skipped by status/demo filters: {result['skipped']}")
    if result.get("error"):
        print(result["error"])


def run(source, path, *, base_branch=None, dry_run=False, run_pipeline=False, approval=None,
        approve_plan=False, plan_id=None, statuses=None, include_demo=False, new_revision=False,
        language=None, provider=None, rerun=False, as_json=False):
    if source != "jobenu":
        _emit({"schema_version": 1, "status": "failed", "error": "Only Jobenu exports are currently supported."}, as_json)
        return 1
    try:
        if not dry_run and approval is None:
            raise ValueError("Select --approval human, auto, or unattended (not required for --dry-run).")
        if rerun and not run_pipeline:
            raise ValueError("--rerun requires --run.")
        path = Path(path).resolve()
        options = {"base_branch": base_branch, "statuses": statuses, "include_demo": include_demo,
                   "new_revision": new_revision, "language": language, "provider": provider,
                   "run": run_pipeline, "approval": approval, "rerun": rerun}
        with contextlib.redirect_stdout(io.StringIO()):
            planned, applications, export = batch_import.plan(path, **options)
        conflicts = [e for e in planned["entries"] if e["action"] not in ("create", "existing")]
        if conflicts:
            _emit({**planned, "status": "conflict", "error": "Resolve locked companies/branch conflicts; changed exports need --new-revision. Nothing was imported."}, as_json)
            return 1
        if dry_run:
            _emit({**planned, "status": "planned"}, as_json)
            return 0
        if not planned["entries"]:
            _emit({**planned, "status": "empty"}, as_json)
            return 0
        if plan_id and plan_id != planned["plan_id"]:
            raise ValueError("The batch plan changed. Preview it again before approving.")
        if approval == "human" and not approve_plan:
            if as_json or not sys.stdin.isatty():
                _emit({**planned, "status": "awaiting_plan_approval",
                       "error": "Review this plan, then pass --approve-plan and --plan-id with its exact ID. No branches were created."}, as_json)
                return 2
            _emit({**planned, "status": "planned"}, False)
            if input("Create these branches and run the selected batch? [y/N]: ").strip().lower() != "y":
                _emit({**planned, "status": "cancelled"}, False)
                return 2
        root = Path(planned["project_root"])
        with batch_import.locked(root), batch_import.project(root):
            # Bind consent to source, base commit, configuration and current
            # registry/index state, including changes while the user reviewed.
            with contextlib.redirect_stdout(io.StringIO()):
                fresh, applications, export = batch_import.plan(path, **options)
            if fresh["plan_id"] != planned["plan_id"]:
                raise ValueError("The batch plan changed while awaiting approval. Preview it again.")
            result = batch_import.apply(fresh, applications, export, rerun=rerun)
            statuses_found = {s["status"] for s in result["results"]}
            code = 1 if statuses_found & {"failed", "rejected"} else 2 if statuses_found & {"awaiting_approval", "awaiting_requirements_approval"} else 0
            result["status"] = "failed" if code == 1 else "awaiting_approval" if code == 2 else "complete" if run_pipeline else "imported"
            batch_import._save(batch_import.store(root) / "last-batch.json", result)
        _emit(result, as_json)
        return code
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _emit({"schema_version": 1, "status": "failed", "error": str(exc)}, as_json)
        return 1
