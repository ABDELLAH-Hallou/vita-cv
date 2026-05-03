"""vita new — create a new tailored CV branch."""

from datetime import date
from vita.helpers.config import load_config
from vita.helpers.registry import load_registry, save_registry, normalize_role
from vita.helpers.logging import log
from vita.helpers import git


def run(branch_type: str, company: str, role: str, force: bool = False, commit_changes: bool = False) -> None:
    company = company.lower().replace(" ", "-")
    role    = normalize_role(role)
    branch  = f"{branch_type}-{company}-{role}"

    config   = load_config()
    registry = load_registry()

    # ── Guard: company locked ────────────────────────────────────────────────
    if company in registry and registry[company].get("locked", False):
        print(f"'{company}' is locked — you decided to keep a fixed CV for this company.")
        print("   Use `python -m vita unlock {company}` to remove the lock.")
        return

    # ── Guard: duplicate warning ─────────────────────────────────────────────
    if company in registry and not force:
        if config.get("warn_on_duplicate", True):
            existing = registry[company].get("branches", [])
            if existing:
                print(f"⚠️  WARNING: You already have CV(s) for '{company}':")
                for b in existing:
                    print(f"   - {b}")
                print()
                answer = input("Creating another may cause inconsistency. Continue? (y/n): ").strip()
                if answer.lower() != "y":
                    print("Aborted.")
                    return

    # ── Guard: Uncommitted changes ────────────────────────────────────────────
    if not git.has_commits():
        print("No initial commit found. Branches created now will be 'unborn' until the first commit.")
        action = input("Would you like to make your initial commit now? [Y/n]: ").strip().lower()
        if action != 'n':
            msg = input(f"Commit message [Initial commit]: ").strip()
            if not msg:
                msg = "Initial commit"
            git.add_and_commit(msg,git.current_branch())
            print("Initial commit created.")
    elif commit_changes and not git.is_clean():
        print("Uncommitted changes found and --commit flag was passed.")
        action = input("What would you like to do? [a]dd and commit / [s]tash / [c]ontinue without committing. Default [a]: ").strip().lower()
        if action == "s":
            git.stash()
            print("Changes stashed.")
        elif action != "c":
            msg = input(f"Commit message [Auto-commit: prep before branching '{branch}']: ").strip()
            if not msg:
                msg = f"Auto-commit: prep before branching '{branch}'"
            git.add_and_commit(msg,git.current_branch())
            print("Changes committed.")

    # ── Resolve base branch ────────────────────────────────────────────
    default_base = f"gen-{role}"
    base = input(f"Base branch? [{default_base}]: ").strip() or default_base

    # ── Create git branch ────────────────────────────────────────────
    current = git.current_branch()
    if base != current:
        if not git.branch_exists(base):
            print(f"Base branch '{base}' does not exist.")
            print(f"Automatically creating '{base}' from current branch...")
            create_base = git.create_branch(base)
            if not create_base.ok:
                print(f"Failed to create base branch '{base}':")
                print(f"   {create_base.stderr}")
                return
        else:
            checkout_base = git.checkout(base)
            if not checkout_base.ok:
                print(f"Failed to checkout base branch '{base}':")
                print(f"   {checkout_base.stderr}")
                return

    result = git.create_branch(branch)
    if not result.ok:
        print(f"Failed to create branch '{branch}':")
        print(f"   {result.stderr}")
        return

    # ── Update registry ──────────────────────────────────────────────────────
    if company not in registry:
        registry[company] = {
            "branches": [],
            "roles": [],
            "locked": False,
            "branch_bases": {},
        }

    if branch not in registry[company]["branches"]:
        registry[company]["branches"].append(branch)
    if role not in registry[company]["roles"]:
        registry[company]["roles"].append(role)

    registry[company]["branch_bases"][branch] = base
    registry[company]["last_updated"] = str(date.today())

    save_registry(registry)
    log(f"Created branch '{branch}' (base: {base}) for company '{company}'")

    print()
    print(f"Branch created  : {branch}")
    print(f"Base branch     : {base}")
    print(f"Registry updated: .vita/companies.json")
