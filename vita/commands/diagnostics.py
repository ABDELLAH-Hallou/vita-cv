"""Inspect local diagnostics and explicitly export a technical-only bundle."""

from pathlib import Path

from vita.helpers.diagnostics import destination, export_trace, inspect_trace, project_root
from vita.helpers.structured import json_text


def run(action, trace_id=None, output=None, as_json=False):
    try:
        if action == "list":
            base = destination(project_root())
            values = sorted(p.name for p in base.iterdir() if len(p.name) == 32 and p.is_dir()) if base.exists() else []
            results = []
            for value in values:
                try:
                    results.append(inspect_trace(value))
                except ValueError:
                    continue
            print(json_text({"schema_version": 1, "traces": results}) if as_json else "\n".join(v["trace_id"] for v in results))
            return True
        if action == "export":
            export_trace(trace_id, Path(output))
            print(f"Sanitized technical bundle saved to {Path(output).resolve()}")
        else:
            result = inspect_trace(trace_id)
            if as_json:
                print(json_text(result))
            else:
                print(f"Trace {trace_id}: {destination(project_root()) / trace_id}")
                for process in result["processes"]:
                    print(f"{process['status']}: phase={process['failed_phase'] or 'none'}; category={process['failure'].get('category', 'none')}")
                for artifact in result["artifacts"]:
                    print(f"{artifact['kind']}: {artifact['capture_status']}; content_exists={artifact['content_exists']}; {artifact['path'] or 'no content file'}")
        return True
    except (OSError, ValueError, TypeError, KeyError):
        print("Could not read/export diagnostics. Check the trace ID, destination access and output path. Existing files are not overwritten.")
        return False
