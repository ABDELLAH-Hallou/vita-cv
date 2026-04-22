from vita.helpers.registry import load_registry
from vita.helpers import git


def run(company: str) -> None:
    company  = company.lower()
    registry = load_registry()

    if company not in registry:
        print(f"No CVs found for '{company}' in the registry.")
        return

    data         = registry[company]
    branches     = data.get("branches", [])
    branch_bases = data.get("branch_bases", {})

    if not branches:
        print(f"'{company}' exists in registry but has no branches recorded.")
        return

    # ── Pick branch ──────────────────────────────────────────────────────────
    if len(branches) == 1:
        branch = branches[0]
    else:
        print(f"Multiple CVs for '{company}':")
        for i, b in enumerate(branches, 1):
            print(f"  {i}. {b}")
        choice = input("Which branch to diff? (number): ").strip()
        try:
            branch = branches[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid choice.")
            return

    base = branch_bases.get(branch, "master")

    print()
    print(f"Diff: {base}  →  {branch}")
    print("─" * 50)

    result = git.diff(base, branch, paths=["*.tex", "sections/"])

    if not result.ok:
        print(f"git diff failed:\n{result.stderr}")
        return

    if result.stdout:
        print(result.stdout)
    else:
        print("(no differences found — branch is identical to base)")
