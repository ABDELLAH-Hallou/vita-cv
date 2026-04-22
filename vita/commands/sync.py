"""vita sync — reconcile the company registry with actual git branches.

This command scans all git branches, compares them against companies.json,
and offers to fix any discrepancies:
  - Branches that exist in git but NOT in the registry → add them
  - Branches in the registry that DON'T exist in git → remove them
"""

from vita.helpers.registry import load_registry, save_registry
from vita.helpers.logging import log
from vita.helpers import git

_ETP_PREFIX = "etp-"


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
    registry = load_registry()
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
    if not missing and not orphans:
        print("Registry is already in sync with git branches.")
        return

    LINE = "─" * 50
    print("VITA Sync Report")
    print(LINE)

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

    added = 0
    removed = 0

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

    save_registry(registry)

    print(f"Sync complete: {added} added, {removed} removed.")
