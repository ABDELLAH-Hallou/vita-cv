"""vita diff — show git diff between a company's CV branch and its base."""

from vita.utils import load_registry, run_shell


def run(company: str) -> None:
    company  = company.lower()
    registry = load_registry()

    if company not in registry:
        print(f"❌ No CVs found for '{company}' in the registry.")
        return

    data         = registry[company]
    branches     = data.get("branches", [])
    branch_bases = data.get("branch_bases", {})

    if not branches:
        print(f"⚠️  '{company}' exists in registry but has no branches recorded.")
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
    print(f"📊 Diff: {base}  →  {branch}")
    print("─" * 50)

    result = run_shell(["git", "diff", f"{base}...{branch}", "--", "*.tex", "sections/"])

    if result.returncode != 0:
        print(f"❌ git diff failed:\n{result.stderr.strip()}")
        return

    if result.stdout.strip():
        print(result.stdout)
    else:
        print("(no differences found — branch is identical to base)")
