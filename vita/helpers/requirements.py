"""JD-only, immutable requirement revisions and explicit approval/reuse."""

import hashlib
import json
import re
from pathlib import Path

from vita.helpers.context_builder import JOB_HEADER_RE
from vita.helpers.env import load_env
from vita.helpers.structured import (
    CATEGORIES,
    SOURCE_REF_SCHEMA,
    STRING,
    TEXT,
    json_text,
    object_schema,
    parse_json,
    validate,
    write_artifact,
)

CLASSIFICATION = {"type": "string", "enum": ["required", "preferred", "unclear"]}
SOURCE_REFS = {"type": "array", "minItems": 1, "items": SOURCE_REF_SCHEMA}
PROPOSAL_SCHEMA = object_schema({
    "schema_version": {"type": "integer", "const": 1},
    "items": {"type": "array", "minItems": 1, "items": object_schema({
        "job_id": TEXT, "key": TEXT, "text": TEXT,
        "kind": {"type": "string", "enum": ["capability", "employment_condition"]},
        "category": {"type": "string", "enum": list(CATEGORIES[:-1])},
        "classification": CLASSIFICATION, "ambiguity": STRING, "source_refs": SOURCE_REFS,
    })},
})
UNIT_SCHEMA = object_schema({
    "id": TEXT, "job_id": TEXT, "key": TEXT, "criterion": TEXT,
    "category": {"type": "string", "enum": [*CATEGORIES[:-1], "employment_condition"]},
    "classification": CLASSIFICATION,
    "importance": {"type": "string", "enum": ["must_have", "nice_to_have", "unclear"]},
    "weight": {"type": "integer", "enum": [0, 1, 2]},
    "ambiguity": STRING, "source_refs": SOURCE_REFS,
})
REVISION_SCHEMA = object_schema({
    "schema_version": {"type": "integer", "const": 1}, "revision": TEXT,
    "state": {"type": "string", "enum": ["pending", "draft"]},
    "source_sha256": TEXT, "source_text": TEXT,
    "requirements": {"type": "array", "items": UNIT_SCHEMA},
    "employment_conditions": {"type": "array", "items": UNIT_SCHEMA},
})
WEIGHTS = {"required": 2, "preferred": 1, "unclear": 0}
IMPORTANCE = {"required": "must_have", "preferred": "nice_to_have", "unclear": "unclear"}
STATE = Path(".vita/requirements-state.json")
HEX = re.compile(r"[0-9a-f]{64}")
APPROVAL_SCHEMA = object_schema({
    "schema_version": {"type": "integer", "const": 1}, "source_sha256": TEXT, "revision": TEXT,
})


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_text(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def store_dir() -> Path:
    """Worktrees share their Git common directory; non-Git projects use .vita."""
    configured = load_env().get("VITA_REQUIREMENTS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    for parent in (Path.cwd(), *Path.cwd().parents):
        marker = parent / ".git"
        if marker.is_dir():
            return marker / "vita/requirements"
        if marker.is_file():
            value = marker.read_text(encoding="utf-8").strip()
            if value.startswith("gitdir: "):
                git_dir = (parent / value[8:]).resolve()
                common = git_dir / "commondir"
                if common.is_file():
                    git_dir = (git_dir / common.read_text(encoding="utf-8").strip()).resolve()
                return git_dir / "vita/requirements"
    return Path(".vita/requirements")


def source_jobs(raw: str) -> list[str]:
    """Assign original line numbers to the existing '# Job N' ordinal IDs."""
    headers = list(JOB_HEADER_RE.finditer(raw))
    if len(headers) < 2:
        return ["job-1"] * len(raw.splitlines())
    starts = [raw[:match.start()].count("\n") for match in headers]
    result = [""] * len(raw.splitlines())
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(result)
        if not any(line.strip() for line in raw.splitlines()[start + 1:end]):
            raise ValueError("Canonical requirements cannot include an empty job section")
        result[start:end] = [f"job-{i + 1}"] * (end - start)
    return result


def validate_refs(refs: list, raw: str, job_id: str) -> None:
    lines, owners = raw.splitlines(), source_jobs(raw)
    for ref in refs:
        validate(ref, SOURCE_REF_SCHEMA)
        start, end = ref["line_start"], ref["line_end"]
        if not 1 <= start <= end <= len(lines):
            raise ValueError("Requirement source reference has an invalid line range")
        if ref["job_id"] != job_id or any(owner != job_id for owner in owners[start - 1:end]):
            raise ValueError("Requirement source reference belongs to another job")
        if ref["quote"] not in "\n".join(lines[start - 1:end]):
            raise ValueError("Requirement source quote is not present at the referenced lines")


def normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def concept_key(value: str) -> str:
    value = re.sub(r"^(?:hard.skill|soft.skill|skill|keyword|responsibility|experience|capability)[:/_ -]+",
                   "", value.casefold())
    return normalize(value)


def _classification(item: dict, raw: str) -> str:
    required = re.compile(r"\b(?:required|must(?:[- ]have)?|mandatory|essential)\b", re.I)
    preferred = re.compile(r"\b(?:preferred|significant plus|strong plus|a plus|nice[- ]to[- ]have|desirable|optional|bonus)\b", re.I)
    lines = raw.splitlines()
    decisions = []
    for ref in item["source_refs"]:
        text = ref["quote"]
        explicit = (bool(required.search(text)), bool(preferred.search(text)))
        if any(explicit):
            decisions.append("unclear" if all(explicit) else "required" if explicit[0] else "preferred")
            continue
        heading = ""
        for line in reversed(lines[:ref["line_start"] - 1]):
            if line.lstrip().startswith("#") or line.strip().endswith(":") or line.strip().startswith("**"):
                heading = line
                break
        cues = (bool(required.search(heading)), bool(preferred.search(heading)))
        decisions.append("unclear" if all(cues) else "required" if cues[0] else "preferred" if cues[1]
                         else item["classification"])
    return decisions[0] if len(set(decisions)) == 1 else "unclear"


def _condition(item: dict, raw: str) -> bool:
    text = " ".join(ref["quote"] for ref in item["source_refs"])
    return item["kind"] == "employment_condition" or bool(re.search(
        r"\b(?:home[- ]office (?:requirements|setup)|if working (?:remotely|from home)|"
        r"reliable internet|own (?:computer|equipment)|work authorization|employment conditions)\b", text, re.I,
    ))


def compile_revision(proposal: dict, raw: str) -> dict:
    """Deduplicate canonical concepts across skill/keyword/responsibility labels."""
    validate(proposal, PROPOSAL_SCHEMA)
    groups = []
    for item in sorted(proposal["items"], key=lambda x: (x["job_id"], concept_key(x["key"]), x["text"])):
        validate_refs(item["source_refs"], raw, item["job_id"])
        key = concept_key(item["key"])
        if not key:
            raise ValueError("A requirement concept key must contain letters or digits")
        matches = [group for group in groups if group[0]["job_id"] == item["job_id"] and any(
            concept_key(other["key"]) == key or normalize(other["text"]) == normalize(item["text"])
            for other in group
        )]
        if matches:
            matches[0].append(item)
            for group in matches[1:]:
                matches[0].extend(group)
                groups.remove(group)
        else:
            groups.append([item])
    requirements, conditions = [], []
    for group in groups:
        first = group[0]
        key = min(concept_key(item["key"]) for item in group)
        classes = {_classification(item, raw) for item in group}
        classification = next(iter(classes)) if len(classes) == 1 else "unclear"
        condition = any(_condition(item, raw) for item in group)
        refs = {canonical_text(ref): ref for item in group for ref in item["source_refs"]}
        category = "employment_condition" if condition else min(
            (item["category"] for item in group), key=CATEGORIES.index,
        )
        ambiguity = "; ".join(sorted({item["ambiguity"].strip() for item in group if item["ambiguity"].strip()}))
        if classification == "unclear" and not ambiguity:
            ambiguity = "The source does not consistently distinguish required from preferred."
        unit = {"id": "req-" + digest(first["job_id"] + "\n" + key), "job_id": first["job_id"],
                "key": key, "criterion": min(item["text"].strip() for item in group), "category": category,
                "classification": classification, "importance": IMPORTANCE[classification],
                "weight": 0 if condition else WEIGHTS[classification], "ambiguity": ambiguity,
                "source_refs": [refs[key] for key in sorted(refs)]}
        (conditions if condition else requirements).append(unit)
    return _revision(raw, requirements, conditions, "draft")


def _revision(raw: str, requirements: list, conditions: list, state: str) -> dict:
    body = {"schema_version": 1, "state": state, "source_sha256": digest(raw), "source_text": raw,
            "requirements": sorted(requirements, key=lambda x: x["id"]),
            "employment_conditions": sorted(conditions, key=lambda x: x["id"])}
    return {**body, "revision": digest(canonical_text(body))}


def validate_revision(data: dict) -> None:
    validate(data, REVISION_SCHEMA)
    body = {key: value for key, value in data.items() if key != "revision"}
    if data["source_sha256"] != digest(data["source_text"]) or data["revision"] != digest(canonical_text(body)):
        raise ValueError("Requirement revision content/hash mismatch")
    all_units = data["requirements"] + data["employment_conditions"]
    if len({item["id"] for item in all_units}) != len(all_units):
        raise ValueError("Duplicate canonical requirement IDs")
    if len({(item["job_id"], normalize(item["criterion"])) for item in all_units}) != len(all_units):
        raise ValueError("Duplicate canonical requirement text")
    for item in all_units:
        validate_refs(item["source_refs"], data["source_text"], item["job_id"])
        if item["key"] != concept_key(item["key"]) or item["id"] != "req-" + digest(item["job_id"] + "\n" + item["key"]):
            raise ValueError("Canonical requirement ID/key mismatch")
        condition = item in data["employment_conditions"]
        expected_weight = 0 if condition else WEIGHTS[item["classification"]]
        if item["weight"] != expected_weight or item["importance"] != IMPORTANCE[item["classification"]]:
            raise ValueError("Canonical classification/weight mismatch")
        if condition != (item["category"] == "employment_condition"):
            raise ValueError("Employment conditions must be separate from capabilities")
        source_item = {**item, "kind": "employment_condition" if condition else "capability"}
        if not condition and _condition(source_item, data["source_text"]):
            raise ValueError("Source employment conditions cannot be weighted capabilities")
        resolved = _classification(source_item, data["source_text"])
        if item["classification"] != "unclear" and item["classification"] != resolved:
            raise ValueError("Canonical classification contradicts explicit source wording")


def save_revision(data: dict) -> dict:
    validate_revision(data)
    path = store_dir() / "revisions" / f"{data['revision']}.json"
    if path.exists() and parse_json(path.read_text(encoding="utf-8")) != data:
        raise ValueError("An immutable requirement revision was modified")
    write_artifact(path, canonical_text(data))
    write_artifact(STATE, json_text({"schema_version": 1, "source_sha256": data["source_sha256"],
                                    "revision": data["revision"]}))
    return data


def read_revision(revision: str) -> dict:
    if not HEX.fullmatch(revision):
        raise ValueError("A full 64-character requirement revision ID is required")
    data = parse_json((store_dir() / "revisions" / f"{revision}.json").read_text(encoding="utf-8"))
    validate_revision(data)
    if data["revision"] != revision:
        raise ValueError("Requirement revision filename/hash mismatch")
    return data


def approve_revision(revision: str, raw: str) -> dict:
    data = read_revision(revision)
    if data["source_sha256"] != digest(raw):
        raise ValueError("Cannot approve a revision for different job.md content")
    if data["state"] != "draft" or not data["requirements"]:
        raise ValueError("Generate and review nonempty capability requirements before approval")
    if set(source_jobs(raw)) - {""} != {item["job_id"] for item in data["requirements"]}:
        raise ValueError("Approved requirements must cover every job section")
    save_revision(data)
    write_artifact(store_dir() / "approved" / f"{digest(raw)}.json", json_text({
        "schema_version": 1, "source_sha256": digest(raw), "revision": revision,
    }))
    return data


def approved_revision(raw: str) -> dict | None:
    path = store_dir() / "approved" / f"{digest(raw)}.json"
    if not path.exists():
        return None
    approval = parse_json(path.read_text(encoding="utf-8"))
    validate(approval, APPROVAL_SCHEMA)
    if approval["source_sha256"] != digest(raw):
        raise ValueError("Invalid requirement approval record")
    data = read_revision(approval["revision"])
    if data["source_text"] != raw or data["state"] != "draft" or not data["requirements"]:
        raise ValueError("Approved requirement revision does not match the current job")
    return data


def active_requirements(raw: str) -> dict | None:
    data = approved_revision(raw)
    if data is not None:
        if STATE.exists():
            state = parse_json(STATE.read_text(encoding="utf-8"))
            validate(state, APPROVAL_SCHEMA)
        else:
            state = {}
        # Using an approval must not hide a newer draft awaiting review.
        if state.get("source_sha256") != digest(raw):
            save_revision(data)
        return data
    if not STATE.exists():
        return None  # Existing projects retain their legacy workflow until opting in.
    state = parse_json(STATE.read_text(encoding="utf-8"))
    validate(state, APPROVAL_SCHEMA)
    if state.get("source_sha256") != digest(raw):
        save_revision(_revision(raw, [], [], "pending"))
    raise ValueError("Canonical requirements need approval for this job.md revision. Run "
                     "`vita requirements draft`, review it, then `vita requirements approve REVISION`. "
                     "Previous assessments are stale for the changed/unapproved job; source files are preserved.")


def assert_current(data: dict, raw: str) -> None:
    current = approved_revision(raw)
    if current is None or current["revision"] != data["revision"]:
        raise ValueError("The approved requirement revision changed; rerun the assessment")


def export_revision(path: Path, raw: str) -> None:
    data = approved_revision(raw)
    if data is None:
        raise ValueError("No approved requirements are available to export")
    write_artifact(path, json_text({"schema_version": 1, "approved_revision": data}))


def import_revision(path: Path, raw: str) -> dict:
    envelope = parse_json(path.read_text(encoding="utf-8"))
    if set(envelope) != {"schema_version", "approved_revision"} or envelope["schema_version"] != 1:
        raise ValueError("Expected an exported approved requirement revision")
    data = envelope["approved_revision"]
    validate_revision(data)
    if data["source_text"] != raw:
        raise ValueError("Imported requirements do not match job.md")
    save_revision(data)
    return approve_revision(data["revision"], raw)
