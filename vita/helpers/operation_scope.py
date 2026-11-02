"""Shared input hashes for authorization and generation; no approval decisions."""

import hashlib
import json
from pathlib import Path

from vita.helpers.fallback import configured
from vita.helpers.pipeline_config import load_pipeline_settings


def scope_sha256():
    # Preserve the original serialized shape, including legacy disabled-policy
    # hashes. Only hashes leave this helper, never source text or credentials.
    files = [Path("job.md"), *(Path(".vita") / name for name in
              ("config.json", "extensions.json", ".env"))]
    values = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
              for p in files}
    values["project"] = str(Path.cwd().resolve())
    settings = load_pipeline_settings()
    values["routing"] = {step: route.kwargs() for step, route in settings.routes.items()}
    values["extraction"] = settings.extraction_enabled
    if policies := configured():
        values["fallback"] = policies
    for path in sorted(Path(".vita/skills").rglob("*")):
        if path.is_file():
            values[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def input_fingerprint(step):
    from vita.helpers.candidate_evidence import capture_candidate_sources, stable_hash

    value = {"scope": scope_sha256()}
    if step not in ("extract", "requirements"):
        value["sources"] = capture_candidate_sources()["sha256"]
    if step == "cover":
        from vita.helpers.config import load_config
        target = Path(load_config().get("cover_tex_entry", "cover-letter.tex"))
        value["target"] = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    return stable_hash(value)
