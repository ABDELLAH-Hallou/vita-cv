"""
python -m vita <command> [args]

Entry point for the VITA CLI.
"""

import argparse
import sys

from vita import __version__
from vita.commands import init, new, build, status, diff, lock, ai_step, sync


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
    build_p = subparsers.add_parser("build", help="Compile the LaTeX CV to PDF")
    build_p.add_argument(
        "--mode", choices=["auto", "latexmk", "biber"], default="auto",
        help="Build mode (default: auto-detect from .bib presence)"
    )

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

    # ── AI Prompts ────────────────────────────────────────────────────────────
    subparsers.add_parser("analyze", help="Generate prompt to analyze CV vs Job")
    adapt_p = subparsers.add_parser("adapt", help="Generate prompt to adapt CV to Job")
    adapt_p.add_argument("-l", "--language", default="en", help="Target language for the CV (e.g., en, fr, ar, de)")
    subparsers.add_parser("review", help="Generate prompt to review the CV")

    # ── Route ─────────────────────────────────────────────────────────────────
    args = parser.parse_args()

    if args.command == "init":
        init.run(args.force)

    elif args.command == "new":
        new.run(args.type, args.company, args.role, args.force, args.commit)

    elif args.command == "build":
        build.run(args.mode)

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

    elif args.command in ["analyze", "adapt", "review"]:
        lang = getattr(args, "language", None)
        ai_step.run(args.command, language=lang)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
