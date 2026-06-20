"""vita sync — reconcile .vita project state with git branches.

This command checks the .vita directory structure and scans all git branches,
comparing them against companies.json. It offers to fix discrepancies:
  - Missing .vita files/directories → create safe defaults
  - Branches that exist in git but NOT in the registry → add them
  - Branches in the registry that DON'T exist in git → remove them
"""

import json
from pathlib import Path

from vita.helpers.config import CONFIG_FILE, DEFAULT_CONFIG, VITA_DIR
from vita.helpers.env import ENV_EXAMPLE_FILE, ENV_FILE
from vita.helpers.extensions import EXTENSIONS_FILE
from vita.helpers.registry import REGISTRY_FILE
from vita.helpers.registry import load_registry, save_registry
from vita.helpers.logging import log
from vita.helpers import git

_ETP_PREFIX = "etp-"


def _default_extensions() -> dict:
    return {
        "_doc": "See EXTENSIONS.md for full documentation. Keys starting with '_' are ignored.",
        "llm_providers": {
            "openai": {"model": "gpt-4-turbo"},
            "anthropic": {"model": "claude-3-opus-20240229"},
            "_codex_example": {"model": ""},
        },
        "role_aliases": {},
        "language_map": {},
    }


def _env_example_text() -> str:
    return "OPENAI_API_KEY=your_key_here\nANTHROPIC_API_KEY=your_key_here\n"


def _missing_vita_paths() -> list[tuple[Path, str]]:
    expected = [
        (VITA_DIR, "dir"),
        (VITA_DIR / "logs", "dir"),
        (VITA_DIR / "results", "dir"),
        (VITA_DIR / "tmp", "dir"),
        (CONFIG_FILE, "json_config"),
        (REGISTRY_FILE, "json_registry"),
        (EXTENSIONS_FILE, "json_extensions"),
        (ENV_FILE, "env"),
        (ENV_EXAMPLE_FILE, "env_example"),
        (VITA_DIR / "logs" / ".gitkeep", "empty"),
    ]
    return [(path, kind) for path, kind in expected if not path.exists()]


def _create_vita_path(path: Path, kind: str) -> None:
    if kind == "dir":
        path.mkdir(parents=True, exist_ok=True)
    elif kind == "json_config":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    elif kind == "json_registry":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({}, indent=2), encoding="utf-8")
    elif kind == "json_extensions":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_default_extensions(), indent=2), encoding="utf-8")
    elif kind == "env":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    elif kind == "env_example":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_env_example_text(), encoding="utf-8")
    elif kind == "empty":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def _load_json(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(fallback)


def _merge_missing(defaults: dict, current: dict) -> tuple[dict, int]:
    merged = dict(current)
    added = 0
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
            added += 1
        elif isinstance(value, dict) and isinstance(merged[key], dict):
            merged[key], nested_added = _merge_missing(value, merged[key])
            added += nested_added
    return merged, added


def _missing_json_keys() -> list[tuple[Path, dict, int]]:
    checks = [
        (CONFIG_FILE, DEFAULT_CONFIG),
        (EXTENSIONS_FILE, _default_extensions()),
    ]
    missing = []
    for path, defaults in checks:
        if not path.exists():
            continue
        current = _load_json(path, {})
        merged, count = _merge_missing(defaults, current)
        if count:
            missing.append((path, merged, count))
    return missing


def _parse_etp_branch(branch: str) -> tuple[str, str] | None:
    """Parse 'etp-<company>-<role>' → (company, role) or None."""
    if not branch.startswith(_ETP_PREFIX):
        return None
    rest = branch[len(_ETP_PREFIX):]
    parts = rest.split("-", 1)
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def run(auto: bool = False, dry_run: bool = False) -> None:
    missing_vita = _missing_vita_paths()
    missing_json_keys = _missing_json_keys()
    registry = {} if not REGISTRY_FILE.exists() else load_registry()
    git_branches = git.all_branches()

    # ── 1. Find etp-* branches present in git ────────────────────────────────
    git_etp = {}  # company → set of branch names
    for branch in git_branches:
        parsed = _parse_etp_branch(branch)
        if parsed:
            company, _ = parsed
            git_etp.setdefault(company, set()).add(branch)

    # ── 2. Find missing branches (in git, not in registry) ───────────────────
    missing: list[tuple[str, str]] = []  # (company, branch)
    for company, branches in git_etp.items():
        reg_branches = set(registry.get(company, {}).get("branches", []))
        for branch in branches:
            if branch not in reg_branches:
                missing.append((company, branch))

    # ── 3. Find orphan entries (in registry, not in git) ─────────────────────
    orphans: list[tuple[str, str]] = []  # (company, branch)
    for company, data in registry.items():
        for branch in data.get("branches", []):
            if branch.startswith(_ETP_PREFIX) and branch not in git_branches:
                orphans.append((company, branch))

    # ── 4. Report ─────────────────────────────────────────────────────────────
    if not missing_vita and not missing_json_keys and not missing and not orphans:
        print(".vita directory and registry are already in sync.")
        return

    LINE = "─" * 50
    print("VITA Sync Report")
    print(LINE)

    if missing_vita:
        print(f"\nMissing .vita files/directories ({len(missing_vita)}):")
        for path, _ in missing_vita:
            print(f"   + {path}")

    if missing_json_keys:
        print(f"\nIncomplete .vita JSON files ({len(missing_json_keys)}):")
        for path, _, count in missing_json_keys:
            print(f"   + {path}  ({count} missing keys)")

    if missing:
        print(f"\nBranches in git NOT in registry ({len(missing)}):")
        for company, branch in missing:
            print(f"   + {branch}  (company: {company})")

    if orphans:
        print(f"\nRegistry entries with no git branch ({len(orphans)}):")
        for company, branch in orphans:
            print(f"   - {branch}  (company: {company})")

    print()

    if dry_run:
        print("Dry-run mode — no changes written.")
        return

    # ── 5. Prompt / apply ────────────────────────────────────────────────────
    if not auto:
        answer = input("Apply these changes? (y/n): ").strip().lower()
        if answer != "y":
            print("Aborted — no changes made.")
            return

    repaired = 0
    added = 0
    removed = 0

    # Restore missing .vita files/directories without overwriting existing config.
    for path, kind in missing_vita:
        _create_vita_path(path, kind)
        log(f"sync: created missing '{path}'")
        repaired += 1

    # Fill missing default keys in existing JSON files without overwriting user values.
    for path, merged, count in missing_json_keys:
        path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        log(f"sync: added {count} missing keys to '{path}'")
        repaired += count

    # Add missing branches to registry
    for company, branch in missing:
        if company not in registry:
            registry[company] = {
                "branches": [],
                "roles": [],
                "locked": False,
                "branch_bases": {},
            }
        if branch not in registry[company]["branches"]:
            registry[company]["branches"].append(branch)
            # Try to infer role from branch name
            parsed = _parse_etp_branch(branch)
            if parsed:
                _, role = parsed
                if role not in registry[company]["roles"]:
                    registry[company]["roles"].append(role)
            log(f"sync: added '{branch}' to registry (company: {company})")
            added += 1

    # Remove orphan branches from registry
    for company, branch in orphans:
        if company in registry:
            branches = registry[company]["branches"]
            if branch in branches:
                branches.remove(branch)
            # Also clean up branch_bases entry
            registry[company].get("branch_bases", {}).pop(branch, None)
            # Remove company entry entirely if no branches left
            if not registry[company]["branches"]:
                del registry[company]
                log(f"sync: removed empty company '{company}' from registry")
            else:
                log(f"sync: removed orphan branch '{branch}' from registry (company: {company})")
            removed += 1

    if missing or orphans or missing_vita:
        save_registry(registry)

    print(f"Sync complete: {repaired} .vita repaired, {added} added, {removed} removed.")
