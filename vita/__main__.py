"""
python -m vita <command> [args]

Entry point for the VITA CLI.
"""

import argparse
import sys

from vita import __version__
from vita.commands import init, new, build, status, diff, lock, ai_step, sync, keys


def main() -> None:
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        prog="vita",
        description="VITA — Resume as a Service. Personal CV management CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  init                     Initialize VITA in the current directory
  new etp <company> <role> Create a new tailored CV branch
  build                    Compile the LaTeX CV to PDF
  status                   Show all companies and branches
  sync                     Reconcile registry with git branches
  diff <company>           Show diff from base CV
  lock <company>           Lock a company (block new CVs)
  unlock <company>         Unlock a company
  keys                     Manage LLM API keys (list, set, remove)
        """,
    )
    parser.add_argument("-V", "--version", action="version", version=f"vita-cv {__version__}")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # ── init ─────────────────────────────────────────────────────────────────
    init_p = subparsers.add_parser("init", help="Initialize VITA in the current directory")
    init_p.add_argument("-f", "--force", action="store_true", help="Delete existing .vita directory and re-initialize")

    # ── new ──────────────────────────────────────────────────────────────────
    new_p = subparsers.add_parser("new", help="Create a new CV branch")
    new_p.add_argument("type",    choices=["etp"], help="Branch type (etp = employer-targeted)")
    new_p.add_argument("company", help="Company name (e.g. google)")
    new_p.add_argument("role",    help="Role (e.g. swe, 'data engineer')")
    new_p.add_argument("-f", "--force", action="store_true", help="Skip duplicate warning")
    new_p.add_argument("-c", "--commit", action="store_true", help="Commit uncommitted changes before branching")

    # ── build ─────────────────────────────────────────────────────────────────
    subparsers.add_parser("build", help="Compile the LaTeX CV to PDF")


    # ── status ────────────────────────────────────────────────────────────────
    subparsers.add_parser("status", help="Show all companies and branches")

    # ── diff ──────────────────────────────────────────────────────────────────
    diff_p = subparsers.add_parser("diff", help="Show diff from base CV")
    diff_p.add_argument("company", help="Company name")

    # ── lock / unlock ─────────────────────────────────────────────────────────
    lock_p = subparsers.add_parser("lock", help="Lock a company (block new CVs)")
    lock_p.add_argument("company", help="Company name")

    unlock_p = subparsers.add_parser("unlock", help="Unlock a company")
    unlock_p.add_argument("company", help="Company name")

    # ── sync ──────────────────────────────────────────────────────────────────
    sync_p = subparsers.add_parser("sync", help="Reconcile registry with git branches")
    sync_p.add_argument("-y", "--auto",    action="store_true", help="Apply changes without prompting")
    sync_p.add_argument("-n", "--dry-run", action="store_true", help="Preview changes without writing")

    # ── keys ──────────────────────────────────────────────────────────────────
    keys_p = subparsers.add_parser("keys", help="Manage LLM API keys")
    keys_subp = keys_p.add_subparsers(dest="keys_command")
    
    keys_subp.add_parser("list", help="List configured API keys")
    
    keys_set_p = keys_subp.add_parser("set", help="Set an API key")
    keys_set_p.add_argument("provider", help="Provider name (e.g. openai)")
    keys_set_p.add_argument("key", help="The API key")
    
    keys_remove_p = keys_subp.add_parser("remove", help="Remove an API key")
    keys_remove_p.add_argument("provider", help="Provider name")

    # ── AI Prompts ────────────────────────────────────────────────────────────
    analyze_p = subparsers.add_parser("analyze", help="Generate prompt to analyze CV vs Job")
    analyze_p.add_argument("-a", "--auto", action="store_true", help="Run autonomously using configured LLM")
    
    adapt_p = subparsers.add_parser("adapt", help="Generate prompt to adapt CV to Job")
    adapt_p.add_argument("-l", "--language", default="en", help="Target language for the CV (e.g., en, fr, ar, de)")
    adapt_p.add_argument("-a", "--auto", action="store_true", help="Run autonomously using configured LLM")
    
    review_p = subparsers.add_parser("review", help="Generate prompt to review the CV")
    review_p.add_argument("-a", "--auto", action="store_true", help="Run autonomously using configured LLM")

    # ── Route ─────────────────────────────────────────────────────────────────
    args = parser.parse_args()

    if args.command == "init":
        init.run(args.force)

    elif args.command == "new":
        new.run(args.type, args.company, args.role, args.force, args.commit)

    elif args.command == "build":
        build.run()

    elif args.command == "status":
        status.run()

    elif args.command == "sync":
        sync.run(auto=args.auto, dry_run=args.dry_run)

    elif args.command == "diff":
        diff.run(args.company)

    elif args.command == "lock":
        lock.run(args.company, locked=True)

    elif args.command == "unlock":
        lock.run(args.company, locked=False)

    elif args.command == "keys":
        if getattr(args, "keys_command", None) is None:
            keys_p.print_help()
            sys.exit(1)
        provider = getattr(args, "provider", None)
        key = getattr(args, "key", None)
        keys.run(args.keys_command, provider, key)

    elif args.command in ["analyze", "adapt", "review"]:
        lang = getattr(args, "language", None)
        auto = getattr(args, "auto", False)
        ai_step.run(args.command, language=lang, auto=auto)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
