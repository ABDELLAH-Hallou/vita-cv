"""Create, inspect, approve, and transport canonical JD requirement revisions."""

from pathlib import Path

from vita.helpers.job_extraction import read_job
from vita.helpers.llm import generate
from vita.helpers.pipeline_config import load_pipeline_settings
from vita.helpers.requirements import (
    PROPOSAL_SCHEMA,
    STATE,
    approve_revision,
    approved_revision,
    compile_revision,
    digest,
    export_revision,
    import_revision,
    read_revision,
    save_revision,
)
from vita.helpers.structured import json_text, parse_json, write_artifact
from vita.helpers.structured_output import run_structured


def run(action: str, *, auto: bool = False, provider: str | None = None,
        revision: str | None = None, path: str | None = None) -> bool:
    try:
        raw = read_job()
        if action == "approve":
            data = approve_revision(revision, raw)
            print(f"Approved requirement revision: {data['revision']}")
        elif action == "show":
            data = read_revision(revision) if revision else None
            if data is None and STATE.exists():
                state = parse_json(STATE.read_text(encoding="utf-8"))
                if state.get("source_sha256") == digest(raw):
                    data = read_revision(state["revision"])
            approved = approved_revision(raw)
            data = data or approved
            if data is None:
                raise ValueError("No requirements exist. Run `vita requirements draft` first.")
            status = "approved" if approved is not None and approved["revision"] == data["revision"] else data["state"]
            print(json_text({"approval_status": status, "revision": data}))
        elif action == "export":
            export_revision(Path(path), raw)
            print(f"Exported approved requirements to {path}")
        elif action == "import":
            data = import_revision(Path(path), raw)
            print(f"Imported approved revision: {data['revision']}")
        elif action == "draft":
            if path:
                data = save_revision(compile_revision(parse_json(Path(path).read_text(encoding="utf-8")), raw))
                print(f"Draft requirement revision (not approved): {data['revision']}")
                return True
            template = (Path(__file__).parent.parent / "assets/prompts/requirements.md").read_text(encoding="utf-8")
            numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(raw.splitlines(), 1))
            prompt = template + "\n\nPROPOSAL SCHEMA:\n" + json_text(PROPOSAL_SCHEMA) + "\n\nJOB.MD (line numbered):\n" + numbered
            if not auto:
                prompt += ("\nSave only the proposal JSON, then run `vita requirements draft --input FILE`. "
                           "Show the resulting revision to the user. Never approve it automatically.")
                write_artifact(Path(".vita/prompts/requirements.md"), prompt)
                write_artifact(Path(".vita/current_prompt.md"), prompt)
                print("JD-only requirements prompt saved to .vita/prompts/requirements.md")
                return True
            data = run_structured(
                step="requirements", generate=generate,
                system="Extract canonical atomic job requirements using only the provided job description. "
                       "You have no candidate CV. Do not read local files or approve revisions.",
                prompt=prompt, route=load_pipeline_settings().route("extract", provider).kwargs(),
                schema=PROPOSAL_SCHEMA, finalize=lambda value: compile_revision(value, raw), save=save_revision,
            )
            print(f"Draft requirement revision (not approved): {data['revision']}")
            print("Run `vita requirements show` to review, then approve its full revision ID.")
        else:
            raise ValueError(f"Unknown requirements action: {action}")
        return True
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(f"Requirements failed: {exc}")
        return False
