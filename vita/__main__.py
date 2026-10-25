"""
python -m vita <command> [args]

Entry point for the VITA CLI.
"""

import argparse
import os
import sys

from vita import __version__
from vita.commands import (
    ai_step,
    build,
    diagnostics,
    diff,
    facts,
    ingest,
    init,
    keys,
    lock,
    new,
    providers,
    push,
    requirements,
    run,
    status,
    sync,
)


def main() -> None:
    previous = os.environ.get("VITA_DIAGNOSTIC_CONTENT")
    try:
        _main()
    finally:
        # Embedders can call main repeatedly; --debug affects only this call.
        if previous is None:
            os.environ.pop("VITA_DIAGNOSTIC_CONTENT", None)
        else:
            os.environ["VITA_DIAGNOSTIC_CONTENT"] = previous


def _main() -> None:
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        prog="vita",
        description="VITA — Resume as a Service. Personal CV management CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  init                     Initialize VITA in the current directory
  ingest                   Capture, extract, review and convert existing documents locally
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
    parser.add_argument("--debug", action="store_true", help="Retain a detailed local execution journal (credentials redacted)")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    ingest_p = subparsers.add_parser("ingest", help="Local staged PDF/DOCX/scan ingestion; no automatic uploads or approval")
    ingest_sub = ingest_p.add_subparsers(dest="ingest_action", required=True)
    capture_p = ingest_sub.add_parser("capture", help="Preserve original bytes in a private content-addressed store")
    capture_p.add_argument("path")
    import_extract_p = ingest_sub.add_parser("extract", help="Extract source-linked fragments; OCR only when explicitly selected")
    import_extract_p.add_argument("document_id")
    import_extract_p.add_argument("--ocr", action="store_true")
    import_extract_p.add_argument("--ocr-language", help="Explicit installed Tesseract languages, e.g. eng+fra")
    import_extract_p.add_argument("--ocr-all", action="store_true", help="OCR all PDF pages, including existing text layers; requires --ocr")
    review_import_p = ingest_sub.add_parser("review", help="Create a blank review template for an extraction revision")
    review_import_p.add_argument("revision")
    review_import_p.add_argument("--output", required=True)
    approve_import_p = ingest_sub.add_parser("approve", help="Validate an explicit complete source-checked human review")
    approve_import_p.add_argument("revision")
    approve_import_p.add_argument("--review", required=True)
    latex_import_p = ingest_sub.add_parser("latex", help="Generate a new editable source from an approved revision only")
    latex_import_p.add_argument("revision", help="Approval revision, not an extraction ID")
    latex_import_p.add_argument("--output", required=True)
    latex_import_p.add_argument("--language", choices=("en", "es", "fr", "ar"), required=True, help="Source language; this stage does not translate")
    show_import_p = ingest_sub.add_parser("show", help="Inspect a stage record without marking downstream stages complete")
    show_import_p.add_argument("revision")
    show_import_p.add_argument("--kind", choices=("documents", "extractions", "approvals", "exports"), default="extractions")
    for import_parser in (capture_p, import_extract_p, review_import_p, approve_import_p, latex_import_p, show_import_p):
        import_parser.add_argument("--json", action="store_true", help="Show the local full record, which may contain private CV text")

    facts_p = subparsers.add_parser("facts", help="Inspect and explicitly decide source-linked Adapt/Cover proposals")
    facts_sub = facts_p.add_subparsers(dest="facts_action", required=True)
    for action in ("capture", "check", "show", "approve", "reject"):
        action_p = facts_sub.add_parser(action)
        action_p.add_argument("step", choices=("adapt", "cover"))
        if action == "check":
            action_p.add_argument("--proposal", required=True, help="Separate project-local proposed .tex file")
        if action in ("approve", "reject"):
            action_p.add_argument("revision", help="Exact revision after reviewing all confirmation items")
        if action == "show":
            action_p.add_argument("--json", action="store_true")

    diagnostics_p = subparsers.add_parser("diagnostics", help="Inspect local execution traces or export a sanitized technical bundle")
    diagnostics_sub = diagnostics_p.add_subparsers(dest="diagnostics_action", required=True)
    diagnostics_list = diagnostics_sub.add_parser("list", help="List trace IDs in this project's diagnostics store")
    diagnostics_list.add_argument("--json", action="store_true")
    diagnostics_inspect = diagnostics_sub.add_parser("inspect", help="Inspect a trace's phases and capture statuses")
    diagnostics_inspect.add_argument("trace_id", nargs="?", default="latest")
    diagnostics_inspect.add_argument("--json", action="store_true")
    diagnostics_export = diagnostics_sub.add_parser("export", help="Create a sanitized technical ZIP; excludes artifact bodies")
    diagnostics_export.add_argument("trace_id")
    diagnostics_export.add_argument("--output", required=True)

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

    providers_p = subparsers.add_parser("providers", help="Discover models or explicitly test generation")
    providers_sub = providers_p.add_subparsers(dest="providers_action", required=True)
    check_p = providers_sub.add_parser("check", help="Model discovery only unless --generate is selected")
    check_p.add_argument("--provider", required=True, help="Exact provider to check; no fallback")
    check_p.add_argument("--model", help="Exact model to check; defaults to the selected provider configuration")
    check_p.add_argument("--generate", action="store_true", help="Send a small synthetic generation (may consume usage)")
    check_p.add_argument("--json", action="store_true", help="Print the machine-readable check result")

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
    for debug_parser in (run_p, extract_p, analyze_p, adapt_p, review_p, cover_p, build_p):
        debug_parser.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                                  help="Retain exact local prompts/responses and full errors; credentials are redacted")
    args = parser.parse_args()
    if args.debug:
        os.environ["VITA_DIAGNOSTIC_CONTENT"] = "local"

    if args.command == "ingest":
        code = ingest.run(args.ingest_action, **{key: getattr(args, key) for key in
            ("path", "document_id", "revision", "output", "review", "ocr", "ocr_language", "ocr_all", "language", "kind") if hasattr(args, key)}, as_json=args.json)
        if code:
            sys.exit(code)

    elif args.command == "facts":
        if facts.run(args.facts_action, args.step, revision=getattr(args, "revision", None),
                     proposal=getattr(args, "proposal", None), as_json=getattr(args, "json", False)) is False:
            sys.exit(1)

    elif args.command == "diagnostics":
        if diagnostics.run(args.diagnostics_action, trace_id=getattr(args, "trace_id", None),
                           output=getattr(args, "output", None), as_json=getattr(args, "json", False)) is False:
            sys.exit(1)

    elif args.command == "init":
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

    elif args.command == "providers":
        if providers.run(provider=args.provider, model=args.model, generate=args.generate, as_json=args.json) is False:
            sys.exit(1)

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
