"""vita status — show all companies, branches, and current position."""

from vita.utils import load_config, load_registry, get_current_branch, get_all_branches

_LINE = "━" * 44


def run() -> None:
    config   = load_config()
    registry = load_registry()
    author   = config.get("author", "unknown")
    current  = get_current_branch()

    print(f"📋 VITA Status — {author}")
    print(_LINE)
    print(f"Current branch : {current}")
    print()

    if not registry:
        print("  No companies in registry yet.")
        print("  → vita new etp <company> <role>")
        print(_LINE)
        return

    print(f"Companies ({len(registry)}):")
    for company, data in registry.items():
        branches     = data.get("branches", [])
        locked       = " [LOCKED]" if data.get("locked", False) else ""
        count        = len(branches)
        plural       = "s" if count != 1 else ""
        branch_bases = data.get("branch_bases", {})

        print(f"  {company}  [{count} CV{plural}]{locked}")

        for i, branch in enumerate(branches):
            is_last = i == len(branches) - 1
            prefix  = "└──" if is_last else "├──"
            base    = branch_bases.get(branch, "?")
            marker  = "   ← you are here" if branch == current else ""
            print(f"    {prefix} {branch:<32} base: {base}{marker}")
        print()

    # ── Base/gen branches ────────────────────────────────────────────────────
    gen_branches = [b for b in get_all_branches() if b.startswith("gen-")]
    if gen_branches:
        print(f"Base branches:")
        print(f"  {' · '.join(gen_branches)}")
        print()

    print(_LINE)
