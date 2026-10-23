"""
python -m vita <command> [args]

Entry point for the VITA CLI.
"""

import argparse
import sys

from vita import __version__
from vita.commands import (
    ai_step,
    build,
    diff,
    init,
    keys,
    lock,
    new,
    push,
    requirements,
    run,
    status,
    sync,
)


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
  build [both]             Compile the CV, cover letter, or both to PDF
  status                   Show all companies and branches
  sync                     Reconcile registry with git branches
  diff <company>           Show diff from base CV
  lock <company>           Lock a company (block new CVs)
  unlock <company>         Unlock a company
  keys                     Manage LLM API keys (list, set, remove)
  requirements             Draft, approve, and reuse canonical JD requirements
  run                      Run pipeline: optional extract → analyze → adapt → review → cover
  save                     Save and push CV changes
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
    build_p = subparsers.add_parser("build", help="Compile the CV, cover letter, or both to PDF")
    build_p.add_argument("target", nargs="?", choices=["both"], help="Build both documents")
    build_group = build_p.add_mutually_exclusive_group()
    build_group.add_argument("-r", "--resume", action="store_true", help="Build only the CV (default)")
    build_group.add_argument("-c", "--cover", action="store_true", help="Build only the cover letter")


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

    # ── run (pipeline) ─────────────────────────────────────────────────────
    run_p = subparsers.add_parser("run", help="Run pipeline: optional extract → analyze → adapt → review → cover")
    run_p.add_argument("-a", "--auto",     action="store_true", help="Run autonomously using configured LLM")
    run_p.add_argument("-l", "--language", default="en",         help="Target language for the CV and cover letter")
    run_p.add_argument("-p", "--provider", help="LLM provider to use for --auto")

    # ── AI Prompts ────────────────────────────────────────────────────────────
    analyze_p = subparsers.add_parser("analyze", help="Generate prompt to analyze CV vs Job")
    analyze_p.add_argument("-a", "--auto", action="store_true", help="Run autonomously using configured LLM")
    analyze_p.add_argument("-p", "--provider", help="LLM provider to use for --auto")

    extract_p = subparsers.add_parser("extract", help="Extract job.json and job.toon from job.md")
    extract_p.add_argument("-a", "--auto", action="store_true", help="Run extraction with the configured LLM")
    extract_p.add_argument("-p", "--provider", help="Override the extraction provider")

    requirements_p = subparsers.add_parser("requirements", help="Manage approved canonical JD requirements")
    requirements_sub = requirements_p.add_subparsers(dest="requirements_action", required=True)
    draft_p = requirements_sub.add_parser("draft", help="Generate a JD-only draft for approval")
    draft_p.add_argument("--auto", action="store_true", help="Use the extraction-stage provider/model")
    draft_p.add_argument("--provider", help="Override the extraction provider")
    draft_p.add_argument("--input", dest="path", help="Compile a reviewed proposal JSON file without AI")
    approve_p = requirements_sub.add_parser("approve", help="Approve an immutable revision for the current JD")
    approve_p.add_argument("revision", help="Full revision ID shown by draft/show")
    show_p = requirements_sub.add_parser("show", help="Show the current approved revision or latest draft")
    show_p.add_argument("revision", nargs="?", help="An earlier revision to inspect")
    for action in ("export", "import"):
        transport_p = requirements_sub.add_parser(action, help=f"{action.title()} an approved revision")
        transport_p.add_argument("path", help="Portable approved-requirements JSON file")
    
    adapt_p = subparsers.add_parser("adapt", help="Generate prompt to adapt CV to Job")
    adapt_p.add_argument("-l", "--language", default="en", help="Target language for the CV (e.g., en, fr, ar, de)")
    adapt_p.add_argument("-a", "--auto", action="store_true", help="Run autonomously using configured LLM")
    adapt_p.add_argument("-p", "--provider", help="LLM provider to use for --auto")
    
    review_p = subparsers.add_parser("review", help="Generate prompt to review the CV")
    review_p.add_argument("-a", "--auto", action="store_true", help="Run autonomously using configured LLM")
    review_p.add_argument("-p", "--provider", help="LLM provider to use for --auto")
    for assessment_parser in (analyze_p, review_p):
        assessment_parser.add_argument("--reassess", action="store_true", help="Request a fresh scoring judgment")
        assessment_parser.add_argument("--qualitative", action="store_true", help="Also write separate task-specific qualitative commentary")

    cover_p = subparsers.add_parser("cover", help="Create a cover letter from the CV and job.md")
    cover_p.add_argument("-l", "--language", default="en", help="Target language for the cover letter")
    cover_p.add_argument("-a", "--auto", action="store_true", help="Run autonomously using configured LLM")
    cover_p.add_argument("-p", "--provider", help="LLM provider to use for --auto")

    # ── save ──────────────────────────────────────────────────────────────────
    save_p = subparsers.add_parser("save", help="Save and push CV changes")
    save_p.add_argument("-m", "--message", help="Commit message")
    save_p.add_argument(
        "-r",
        "--reconcile",
        action="store_true",
        help="After saving, checkout master, sync, and save master",
    )
    # ── Route ─────────────────────────────────────────────────────────────────
    args = parser.parse_args()

    if args.command == "init":
        init.run(args.force)

    elif args.command == "new":
        new.run(args.type, args.company, args.role, args.force, args.commit)

    elif args.command == "build":
        if args.target and (args.resume or args.cover):
            build_p.error("'both' cannot be combined with --resume or --cover")
        target = args.target or ("cover" if args.cover else "resume")
        if build.run(target) is False:
            sys.exit(1)

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

    elif args.command == "run":
        if run.run(auto=args.auto, language=args.language, provider=args.provider) is False:
            sys.exit(1)

    elif args.command == "requirements":
        if requirements.run(args.requirements_action, auto=getattr(args, "auto", False),
                            provider=getattr(args, "provider", None), revision=getattr(args, "revision", None),
                            path=getattr(args, "path", None)) is False:
            sys.exit(1)

    elif args.command in ["extract", "analyze", "adapt", "review", "cover"]:
        lang = getattr(args, "language", None)
        auto = getattr(args, "auto", False)
        provider = getattr(args, "provider", None)
        options = {key: True for key in ("reassess", "qualitative") if getattr(args, key, False)}
        if ai_step.run(args.command, language=lang, auto=auto, provider=provider, **options) is False:
            sys.exit(1)

    elif args.command == "save":
        push.run(message=args.message, reconcile=args.reconcile)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
