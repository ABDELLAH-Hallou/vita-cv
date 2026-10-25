"""Versioned, content-addressed local ingestion artifacts and declared limits."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

VERSION = "ingestion/1"
STORE = Path(".vita/ingestion")
MAX_INPUT = 20 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_PAGES = 30
MAX_PIXELS = 25_000_000
MAX_CHARACTERS = 2_000_000
MAX_PARAGRAPHS = 20_000


class IngestionError(ValueError):
    def __init__(self, category, action):
        self.category = category
        self.action = action
        super().__init__(action)


def require(condition, action, category="invalid_review"):
    if not condition:
        raise IngestionError(category, action)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def read(path):
    require(path.is_file() and path.stat().st_size <= MAX_EXPANDED, "Artifact missing or exceeds the declared read limit.", "artifact_error")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON fields are not allowed.")
            result[key] = value
        return result
    def invalid_number(_):
        raise IngestionError("invalid_review", "Non-finite JSON numbers are not allowed.")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=invalid_number)


def store():
    root = STORE.resolve()
    require(root.is_relative_to(Path.cwd().resolve()), "The ingestion store must remain inside this project.", "configuration")
    root.mkdir(parents=True, exist_ok=True)
    ignore = root / ".gitignore"
    if not ignore.exists():
        with ignore.open("x", encoding="utf-8") as handle:
            handle.write("*\n")
    require(ignore.read_text(encoding="utf-8") == "*\n", "Restore the ingestion store's private .gitignore before continuing.", "privacy_configuration")
    return root


def identifier(value, document=False):
    require(isinstance(value, str) and re.fullmatch(("doc-" if document else "") + r"[0-9a-f]{64}", value), "Use the complete document or revision ID shown by ingestion.")
    return value


def within(root, path):
    require(path.resolve().is_relative_to(root.resolve()), "Ingestion artifacts must remain inside their private store.", "artifact_error")
    return path


def document(document_id):
    root = store()
    folder = within(root, root / "documents" / identifier(document_id, True))
    data = read(folder / "document.json")
    original = folder / "original.bin"
    require(data["contract_version"] == VERSION and data["id"] == document_id, "Unsupported or mismatched captured document.", "stale_source")
    require(original.is_file() and original.stat().st_size <= MAX_INPUT and sha(original.read_bytes()) == data["sha256"], "Captured original changed or is missing. Capture a new original; existing approvals are invalid.", "stale_source")
    require(document_id == "doc-" + data["sha256"], "Captured document identity is invalid.", "stale_source")
    return data, original


def seal(body):
    return {**body, "revision": fingerprint(body)}


def load(kind, revision):
    base = store()
    require(kind in ("extractions", "approvals", "exports"), "Unsupported ingestion artifact kind.")
    root = within(base, base / kind / identifier(revision))
    data = read(root / "record.json")
    body = {key: value for key, value in data.items() if key != "revision"}
    require(data["revision"] == revision == fingerprint(body) and data["contract_version"] == VERSION,
            "Artifact revision changed; do not reuse a stale review or approval.", "stale_source")
    document(data["document_id"])
    return data, root


def stages(extraction="not_started", review="not_started", latex="not_started"):
    return {"capture": "complete", "extract": extraction, "review": review,
            "latex": latex, "compile": "not_run", "layout_review": "pending", "linguistic_review": "unavailable"}
