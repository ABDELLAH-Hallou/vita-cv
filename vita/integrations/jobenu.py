"""Local Jobenu applications JSON; no API, link fetching or model calls."""

import json
from pathlib import Path

from vita.integrations import Application, Export

MAX_BYTES = 10 * 1024 * 1024
MAX_APPLICATIONS = 1000


def _constant(value):
    raise ValueError("Non-finite numbers are not valid Jobenu JSON.")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Jobenu JSON contains a duplicate field.")
        result[key] = value
    return result


def read(path, *, statuses=None, include_demo=False):
    path = Path(path)
    with path.open("rb") as handle:
        content = handle.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError("Jobenu export exceeds the 10-MiB limit; split it into smaller batches.")
    try:
        data = json.loads(content.decode("utf-8-sig"), parse_constant=_constant, object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Expected a UTF-8 Jobenu JSON export.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("applications"), list):
        raise ValueError("Jobenu export must contain an applications array.")
    if len(data["applications"]) > MAX_APPLICATIONS:
        raise ValueError("Jobenu export exceeds 1,000 applications; split the batch.")
    exported_at = data.get("exportedAt")
    if exported_at is not None and not isinstance(exported_at, str):
        raise ValueError("Jobenu exportedAt must be text or null.")
    selected = {s.upper() for s in (statuses or ["SAVED"])}
    if "ALL" in selected and len(selected) != 1:
        raise ValueError("Use --status ALL by itself.")
    seen, applications, skipped = set(), [], 0
    for index, record in enumerate(data["applications"], 1):
        if not isinstance(record, dict):
            raise ValueError(f"Jobenu application {index} must be an object.")
        for field in ("id", "company", "position", "description"):
            value = record.get(field)
            if not isinstance(value, str) or not value.strip() or "\0" in value:
                raise ValueError(f"Jobenu application {index} needs nonempty text in {field}.")
        if len(record["id"]) > 512 or len(record["company"]) > 512 or len(record["position"]) > 2048:
            raise ValueError(f"Jobenu application {index} has an oversized identity/title.")
        if record["id"] in seen:
            raise ValueError(f"Jobenu application {index} repeats an application ID.")
        seen.add(record["id"])
        if not isinstance(record.get("isDemo", False), bool):
            raise ValueError(f"Jobenu application {index} has an invalid isDemo flag.")
        status = record.get("status", "SAVED")
        if not isinstance(status, str):
            raise ValueError(f"Jobenu application {index} has an invalid status.")
        if (record.get("isDemo") and not include_demo) or ("ALL" not in selected and status.upper() not in selected):
            skipped += 1
            continue
        applications.append(Application(
            source="jobenu", id=record["id"], company=record["company"],
            position=record["position"], description=record["description"],
            metadata={k: v for k, v in record.items() if k != "description"},
        ))
    return Export("jobenu", exported_at, tuple(applications), skipped)
