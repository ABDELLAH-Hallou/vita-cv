"""Plan, import and resume source-identified applications in isolated worktrees."""

import contextlib
import hashlib
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from vita.commands import ai_step
from vita.commands.run import STEPS
from vita.helpers import approval as approval_policy
from vita.helpers import factual_changes, fallback, git, requirements
from vita.helpers.candidate_evidence import capture_candidate_sources
from vita.helpers.config import DEFAULT_CONFIG
from vita.helpers.extensions import merged_role_aliases
from vita.helpers.pipeline_config import load_pipeline_settings
from vita.helpers.registry import ROLE_ALIASES
from vita.integrations import read_export

VERSION = 1
SETTINGS_FILES = ("config.json", "extensions.json", ".env", "cv.yaml", "cv-verified.json",
                  "requirements-state.json")


class BatchError(ValueError):
    """Controlled host messages suitable for the machine-readable report."""


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read(path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}.")
    return value


def _text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _save(path, value):
    temporary = path.with_suffix(".tmp")
    _text(temporary, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def store(root):
    return root / ".vita/imports/jobenu"


def _index(root):
    data = _read(store(root) / "index.json", {"schema_version": VERSION, "applications": {}})
    if data.get("schema_version") != VERSION or not isinstance(data.get("applications"), dict):
        raise ValueError("Invalid Jobenu import index; restore it before importing again.")
    return data


def _slug(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:80].strip("-")


def _role(position, aliases):
    key = position.lower().strip()
    if key in aliases:
        value = _slug(aliases[key])
        if not value:
            raise ValueError("A configured role alias has an empty/invalid branch abbreviation.")
        return value, "alias"
    normalized = " " + _slug(position).replace("-", " ") + " "
    for title in sorted(aliases, key=len, reverse=True):
        phrase = _slug(title).replace("-", " ")
        if phrase and f" {phrase} " in normalized:
            value = _slug(aliases[title])
            if value:
                return value, "title_match"
    return _slug(position) or "role-" + digest(position)[:8], "slug_fallback"


def _project_settings(root):
    config = {**DEFAULT_CONFIG, **_read(root / ".vita/config.json", {})}
    integrations = config.get("integrations", {})
    if not isinstance(integrations, dict) or not isinstance(integrations.get("jobenu", {}), dict):
        raise ValueError("config.integrations.jobenu must be an object.")
    return config, integrations.get("jobenu", {})


def _settings_hash(root):
    if (root / ".vita").is_symlink():
        raise ValueError("Copy linked .vita settings into the project before batch import.")
    files = [root / ".vita" / name for name in SETTINGS_FILES]
    skills = root / ".vita/skills"
    if skills.exists():
        if skills.is_symlink():
            raise ValueError("Copy linked custom skills into the project before batch import.")
        files.extend(p for p in skills.rglob("*") if p.is_file() or p.is_symlink())
    values = {}
    for path in sorted(files):
        if path.is_symlink():
            raise ValueError("Linked local settings/skills are not copied; supply project-local files.")
        if path.is_file():
            if not path.resolve().is_relative_to((root / ".vita").resolve()):
                raise ValueError("A local settings/skill path escapes the project settings folder.")
            values[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest(values)


def job_markdown(app):
    # Candidate/base/export-run provenance belongs in the private index, not
    # the JD. The same job must hash identically across different CV bases.
    metadata = {**app.metadata, "integration": app.source}
    payload = json.dumps(metadata, ensure_ascii=False, indent=2)
    longest = max((len(s) for s in re.findall(r"`+", payload)), default=0)
    fence = "`" * max(3, longest + 1)
    heading = " ".join(f"{app.position} — {app.company}".split())
    return (f"# {heading}\n\n{app.description}\n\n---\n\n"
            "Jobenu source metadata (application context, not evidence of candidate qualifications):\n\n"
            f"{fence}json\n{payload}\n{fence}\n")


@contextlib.contextmanager
def project(path):
    previous = Path.cwd()
    old_root = os.environ.get("VITA_PROJECT_ROOT")
    try:
        os.chdir(path)
        os.environ["VITA_PROJECT_ROOT"] = str(path)
        yield
    finally:
        os.chdir(previous)
        if old_root is None:
            os.environ.pop("VITA_PROJECT_ROOT", None)
        else:
            os.environ["VITA_PROJECT_ROOT"] = old_root


def plan(path, *, base_branch=None, statuses=None, include_demo=False, new_revision=False,
         language=None, provider=None, run=False, approval=None, rerun=False):
    if approval is not None:
        approval_policy.policy(approval)
    result = git.repository_root()
    if not result.ok:
        raise ValueError("Run the importer inside an existing Git CV project.")
    root = Path(result.stdout).resolve()
    source_path = Path(path).resolve()
    with project(root):
        config, preferences = _project_settings(root)
        base = base_branch or preferences.get("base_branch") or config.get("default_base_branch", "master")
        if not isinstance(base, str):
            raise ValueError("The configured base branch must be a branch name string.")
        resolved = git.local_branch_commit(base)
        if not resolved.ok:
            raise ValueError(f"Base branch '{base}' is not an existing local branch. Select one with --base-branch.")
        export = read_export("jobenu", source_path, statuses=statuses, include_demo=include_demo)
        extensions = _read(root / ".vita/extensions.json", {})
        user_aliases = extensions.get("role_aliases", {})
        if not isinstance(user_aliases, dict) or any(not isinstance(v, str) for k, v in user_aliases.items() if not k.startswith("_")):
            raise ValueError("extensions.role_aliases must map role titles to text abbreviations.")
        aliases = merged_role_aliases({**ROLE_ALIASES, "ai engineer": "ai", "artificial intelligence engineer": "ai"})
        index = _index(root)
        registry = _read(root / ".vita/companies.json", {})
        entries, records = [], {}
        stems = {}
        for app in export.applications:
            company = _slug(app.company) or "company-" + digest(app.company)[:8]
            role, resolution = _role(app.position, aliases)
            stem = f"etp-{company}-{role}"
            stems[stem] = stems.get(stem, 0) + 1
            key = digest([app.source, app.id])
            content_hash = digest({"metadata": app.metadata, "description": app.description})
            fingerprint = digest([content_hash, resolved.stdout])
            versions = index["applications"].get(key, {}).get("versions", {})
            if not isinstance(versions, dict):
                raise ValueError("Invalid application versions in import index.")
            known = versions.get(fingerprint)
            changed = any(v["base_commit"] == resolved.stdout and v["content_sha256"] != content_hash
                          for v in versions.values())
            action = "existing" if known else "source_changed" if changed and not new_revision else "create"
            entry = {"application_id": app.id, "key": key, "fingerprint": fingerprint,
                     "content_sha256": content_hash,
                     "company": app.company, "company_slug": company, "position": app.position,
                     "role": role, "role_resolution": resolution, "stem": stem, "action": action}
            if known:
                entry["branch"] = known["branch"]
                entry["base_commit"] = known["base_commit"]
                if known.get("routing_amendments"):
                    entry["routing_amendments_sha256"] = digest(known["routing_amendments"])
            locked = registry.get(company, {}).get("locked", False)
            if locked and not known:
                entry["action"] = "locked"
            entries.append(entry)
            records[key] = app
        for entry in entries:
            if entry["action"] == "existing":
                continue
            branch = entry["stem"]
            if stems[branch] > 1 or git.local_branch_commit(branch).ok or new_revision:
                branch += "-" + digest([entry["key"], entry["fingerprint"]])[:10]
            entry["branch"] = branch
            if git.local_branch_commit(branch).ok and entry["action"] == "create":
                entry["action"] = "branch_conflict"
        selected_language = language or preferences.get("language") or config.get("default_language", "en")
        selected_provider = provider or preferences.get("provider")
        if not isinstance(selected_language, str) or not selected_language.strip():
            raise ValueError("Choose a nonempty language code.")
        if selected_provider is not None and not isinstance(selected_provider, str):
            raise ValueError("The Jobenu provider preference must be text.")
        payload = {"schema_version": VERSION, "source": "jobenu", "project_root": str(root),
                   "source_file": str(source_path), "base_branch": base, "base_commit": resolved.stdout,
                   "language": selected_language, "provider": selected_provider, "run_pipeline": run,
                   "approval": approval, "rerun": rerun, "skipped": export.skipped, "entries": entries}
        payload["approval_policy"] = approval_policy.policy(approval) if approval else None
        payload["approval_warning"] = approval_policy.WARNING if approval == "unattended" else None
        payload["preferences_sha256"] = _settings_hash(root)
        settings = load_pipeline_settings()
        payload["routing_sha256"] = digest({"extract": settings.extraction_enabled,
                                           "routes": {s: r.kwargs() for s, r in settings.routes.items()}})
        payload["fallback_policies"] = fallback.configured()
        payload["plan_id"] = digest(payload)
        return payload, records, export


@contextlib.contextmanager
def locked(root):
    private = root / ".vita/imports"
    private.mkdir(parents=True, exist_ok=True)
    if not (private / ".gitignore").exists():
        _text(private / ".gitignore", "*\n")
    folder = store(root)
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "import.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("A Jobenu import is already running (import.lock). Retry after it finishes; inspect a stale lock after a crash.") from None
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def _preferences(root, workspace):
    target = workspace / ".vita"
    if target.is_symlink() or not target.resolve().is_relative_to(workspace.resolve()):
        raise BatchError("The base branch links .vita outside its worktree; use project-local settings.")
    target.mkdir(exist_ok=True)
    if git.tracked(str(workspace), ".vita/.env"):
        raise BatchError("The base branch tracks .vita/.env. Untrack the credentials file before copying current secrets.")
    ignore = target / ".gitignore"
    if ignore.is_symlink() or not ignore.resolve().is_relative_to(workspace.resolve()):
        raise BatchError("The base branch has a linked settings ignore file outside the worktree.")
    existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if "*" not in existing.splitlines():
        _text(ignore, existing.rstrip() + "\n# Private imported worktree settings and execution artifacts\n*\n")
    config, _ = _project_settings(root)
    for name in SETTINGS_FILES:
        source = root / ".vita" / name
        if source.is_symlink():
            raise ValueError(f"Copy the linked project setting {name} into the project before batch import.")
        if source.is_file():
            if (target / name).is_symlink() or not (target / name).resolve().is_relative_to(workspace.resolve()):
                raise BatchError("A settings destination in the base branch links outside its worktree.")
            shutil.copy2(source, target / name)
    if not (target / "config.json").exists():
        _save(target / "config.json", config)
    skills = root / ".vita/skills"
    if skills.exists():
        if skills.is_symlink() or any(p.is_symlink() or not p.resolve().is_relative_to(skills.resolve()) for p in skills.rglob("*")):
            raise ValueError("Copy linked custom skills into the project before batch import.")
        if (target / "skills").exists():
            for path in [target / "skills", *(target / "skills").rglob("*")]:
                if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
                    raise BatchError("A skill destination in the base branch links outside its worktree.")
        shutil.copytree(skills, target / "skills", dirs_exist_ok=True)


def _registry(root, state):
    path = root / ".vita/companies.json"
    registry = _read(path, {})
    company = registry.setdefault(state["company_slug"], {"branches": [], "roles": [], "locked": False})
    if state["branch"] not in company.setdefault("branches", []):
        company["branches"].append(state["branch"])
    if state["role"] not in company.setdefault("roles", []):
        company["roles"].append(state["role"])
    company.setdefault("branch_bases", {})[state["branch"]] = state["base_branch"]
    company["last_updated"] = datetime.now(timezone.utc).date().isoformat()
    _save(path, registry)


def _git_error(path, operation, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{operation}: exit {result.returncode}\n{result.stderr}\n")


def _owned_workspace(root, state):
    workspace = Path(state["workspace"]).resolve()
    if not workspace.is_relative_to((store(root) / "worktrees").resolve()):
        raise BatchError("Import workspace is outside the managed batch folder.")
    branch = git.worktree_branch(str(workspace))
    if not branch.ok or branch.stdout != state["branch"]:
        raise BatchError("Imported worktree is missing or on a different branch; restore it before resuming.")
    if digest((workspace / "job.md").read_text(encoding="utf-8")) != state["job_sha256"]:
        raise BatchError("Imported job.md changed. Preserve the edit and import an explicit new revision.")
    return workspace


def _pending_decision(state, authorization=None):
    pending = state.get("pending")
    if not pending:
        return True
    report = factual_changes.load(pending["step"])
    if report["revision"] != pending["revision"]:
        raise BatchError("Pending proposal revision changed; use --rerun to explicitly reassess current sources.")
    if report["status"] == "rejected":
        state["status"] = "rejected"
        return False
    if (authorization is not None and report["status"] == "approved"
            and report["application_status"] == "not_applied"):
        report = factual_changes.resume_unattended(pending["step"], authorization) or report
    if report["status"] not in ("approved", "applied") or report["application_status"] != "applied":
        state["status"] = "awaiting_approval"
        return False
    if Path(report["target"]).read_text(encoding="utf-8") != report["document"]:
        raise BatchError("Approved output was edited; use --rerun to reassess current sources.")
    factual_changes.assert_applied_current(report)
    state["completed_steps"].append(pending["step"])
    state.pop("pending")
    return True


def _checkpoint():
    config, _ = _project_settings(Path.cwd())
    snapshot = capture_candidate_sources()
    if not any(s["kind"] == "cv" for s in snapshot["sources"]):
        raise BatchError("The configured CV source is missing in the base branch. Fix tex_entry or choose a different base.")
    cover = Path(config.get("cover_tex_entry", "cover-letter.tex")).resolve()
    if not cover.is_relative_to(Path.cwd().resolve()):
        raise BatchError("Cover target must be inside the imported workspace.")
    settings = load_pipeline_settings()
    effective = {"extract": settings.extraction_enabled,
                 "routes": {step: route.kwargs() for step, route in settings.routes.items()}}
    if policies := fallback.configured():
        effective["fallback"] = policies
    canonical = requirements.approved_revision(Path("job.md").read_text(encoding="utf-8"))
    return {"candidate": snapshot["sha256"], "settings": digest([_settings_hash(Path.cwd()), effective]),
            "requirements_revision": canonical["revision"] if canonical else None,
            "cover": digest(cover.read_text(encoding="utf-8")) if cover.exists() else None}


def execute(state, options, persist):
    """Existing pipeline stages, with durable checkpoints and no approval bypass."""
    workspace = Path(state["workspace"])
    with project(workspace):
        if state.get("job_sha256") and state["job_sha256"] != digest(Path("job.md").read_text(encoding="utf-8")):
            raise BatchError("Job content changed since the captured workflow. Preserve the edit and start a new job revision.")
        selected = approval_policy.policy(options["approval"])
        previous_policy = state.get("approval_policy", approval_policy.policy("auto"))
        if (previous_policy != selected and "unattended" in
                (previous_policy["mode"], selected["mode"]) and not options.get("rerun")
                and (state.get("execution_options") or state.get("authorization"))):
            raise BatchError("Approval policy changed. Preview a new plan and use --rerun for fresh consent.")
        if state["status"] == "complete" and not options.get("rerun"):
            routing = {k: options[k] for k in ("language", "provider")}
            if state.get("checkpoint") != _checkpoint() or state.get("execution_options") != routing:
                raise BatchError("Completed inputs or routing changed. Use --rerun to reassess current sources.")
            return
        if options.get("rerun"):
            state["completed_steps"] = []
            state.pop("pending", None)
            state["status"] = "imported"
            state.pop("checkpoint", None)
            state.pop("execution_options", None)
            state.pop("authorization", None)
        routing = {k: options[k] for k in ("language", "provider")}
        if state.get("execution_options", routing) != routing:
            raise BatchError("Language/provider override changed. Use --rerun for the new routing.")
        state["approval_policy"] = selected
        authorization = None
        if options["approval"] == "unattended":
            authorization = approval_policy.capture("unattended", state.get("authorization"))
            state["authorization"] = authorization
            persist()
            step = state.get("current_step")
            if not state.get("pending") and step in ("adapt", "cover") and Path(f".vita/results/{step}.facts.json").exists():
                report = factual_changes.load(step)
                if (report.get("approval", {}).get("run_id") == authorization["run_id"]
                        and report["status"] == "approved"):
                    state["pending"] = {"step": step, "revision": report["revision"]}
        had_pending = bool(state.get("pending"))
        if not _pending_decision(state, authorization):
            persist()
            return
        if state.get("fallback_overrides") and not had_pending and state.get("checkpoint") != _checkpoint():
            raise BatchError("Amended routing cannot reuse stale inputs/settings. Restore the captured dependencies before resuming.")
        try:
            if authorization is not None:
                from vita.commands.requirements import ensure_unattended
                log = workspace / ".vita/imports/execution.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as handle, contextlib.redirect_stdout(handle), contextlib.redirect_stderr(handle):
                    state["current_step"] = "requirements"
                    persist()
                    with fallback.operation_policy("requirements", state.get("fallback_overrides", {}).get("requirements")):
                        approved = ensure_unattended(authorization)
                    state.pop("current_step", None)
            else:
                approved = requirements.active_requirements(Path("job.md").read_text(encoding="utf-8"))
        except ValueError as exc:
            if not str(exc).startswith("Canonical requirements need approval"):
                raise
            state["status"] = "awaiting_requirements_approval"
            state["pending_requirements"] = "Run vita requirements draft --auto, review it, then vita requirements approve REVISION in this workspace."
            persist()
            return
        state.pop("pending_requirements", None)
        current = _checkpoint()
        previous = state.get("checkpoint")
        if previous and (previous["settings"] != current["settings"]
                         or previous.get("requirements_revision") != current["requirements_revision"]
                         or (not had_pending and previous != current)):
            raise BatchError("CV or saved settings changed since the pipeline checkpoint. Use --rerun to reassess current inputs.")
        routing = {k: options[k] for k in ("language", "provider")}
        if state.get("execution_options", routing) != routing:
            raise BatchError("Language/provider override changed. Use --rerun for the new routing.")
        state["execution_options"] = routing
        state["checkpoint"] = current
        settings = load_pipeline_settings()
        steps = (["extract"] if settings.extraction_enabled and approved is None else []) + STEPS
        state["steps"] = steps
        log = workspace / ".vita/imports/execution.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        state["execution_log"] = str(log)
        for step in steps:
            if step in state["completed_steps"]:
                continue
            state["status"], state["current_step"] = "running", step
            persist()
            with log.open("a", encoding="utf-8") as handle, contextlib.redirect_stdout(handle), contextlib.redirect_stderr(handle):
                kwargs = {"auto": True, "language": options["language"] if step in ("adapt", "cover") else None,
                          "provider": options["provider"] if step != "extract" else None}
                if step in ("adapt", "cover") and options["approval"] == "human":
                    kwargs["approval"] = "human"
                if authorization is not None:
                    kwargs.update(approval="unattended", authorization=authorization)
                prior = fallback.outcome_view(step)
                parent = prior["run_id"] if prior else None
                with fallback.operation_policy(step, state.get("fallback_overrides", {}).get(step), parent):
                    success = ai_step.run(step, **kwargs)
            outcome = fallback.outcome_view(step)
            if outcome:
                state.setdefault("operation_outcomes", {})[step] = outcome
            if success is False:
                state["status"] = "failed"
                if step in ("adapt", "cover") and Path(f".vita/results/{step}.facts.json").exists():
                    report = factual_changes.load(step)
                    if report["status"] == "confirmation_required" and authorization is None:
                        state["pending"] = {"step": step, "revision": report["revision"]}
                        state["status"] = "awaiting_approval"
                    elif report["status"] == "rejected":
                        state["status"] = "rejected"
                    elif report["status"] == "approved" and report["application_status"] != "applied":
                        state["pending"] = {"step": step, "revision": report["revision"]}
                persist()
                return
            state["completed_steps"].append(step)
            state["checkpoint"] = _checkpoint()
            persist()
        state["status"] = "complete"
        state.pop("current_step", None)
        persist()


def apply(planned, applications, export, *, rerun=False):
    root = Path(planned["project_root"])
    if _settings_hash(root) != planned["preferences_sha256"]:
        raise ValueError("Project preferences changed after planning. Preview and approve a new plan.")
    if not git.author_configured():
        raise ValueError("Configure git user.name and user.email before creating import commits.")
    index = _index(root)
    results = []
    for entry in planned["entries"]:
        versions = index["applications"].setdefault(entry["key"], {"versions": {}})["versions"]
        state = versions.get(entry["fingerprint"])
        if state is None:
            workspace = store(root) / "worktrees" / (entry["key"][:16] + "-" + entry["fingerprint"][:12])
            if workspace.exists():
                results.append({**entry, "status": "failed", "error": "Existing unregistered workspace; inspect it before retrying."})
                continue
            workspace.parent.mkdir(parents=True, exist_ok=True)
            added = git.add_worktree(str(workspace), entry["branch"], planned["base_commit"])
            if not added.ok:
                log = store(root) / "git.log"
                _git_error(log, "worktree.add", added)
                results.append({**entry, "status": "failed", "error": "Could not create worktree; inspect the private git.log.", "execution_log": str(log)})
                continue
            app = applications[entry["key"]]
            job = job_markdown(app)
            state = {**entry, "base_branch": planned["base_branch"], "base_commit": planned["base_commit"],
                     "workspace": str(workspace), "job_sha256": digest(job), "status": "preparing",
                     "completed_steps": [], "exported_at": export.exported_at, "import_ready": False,
                     "initial_job_sha256": digest((workspace / "job.md").read_text(encoding="utf-8"))
                     if (workspace / "job.md").exists() else None}
            versions[entry["fingerprint"]] = state
            _save(store(root) / "index.json", index)
        def persist():
            _save(store(root) / "index.json", index)
        state["action"] = entry["action"]
        try:
            if not state["import_ready"]:
                workspace = Path(state["workspace"])
                _preferences(root, workspace)
                app = applications[entry["key"]]
                current = digest((workspace / "job.md").read_text(encoding="utf-8")) if (workspace / "job.md").exists() else None
                if current not in (state["initial_job_sha256"], state["job_sha256"]):
                    raise BatchError("job.md was edited during a stopped import; preserve the edit before retrying.")
                if (workspace / "job.md").is_symlink() or not (workspace / "job.md").resolve().is_relative_to(workspace.resolve()):
                    raise BatchError("The base branch links job.md outside its worktree; use a local job.md file.")
                _text(workspace / "job.md", job_markdown(app))
                committed = git.commit_paths(str(workspace), "chore: import Jobenu application", ["job.md"])
                if not committed.ok:
                    log = workspace / ".vita/imports/git.log"
                    _git_error(log, "import.commit", committed)
                    state["execution_log"] = str(log)
                    raise BatchError("Import commit failed. Inspect the private Git log in the retained worktree before retrying.")
                state["status"] = "imported"
                state["import_ready"] = True
                persist()
            _owned_workspace(root, state)
            _registry(root, state)
            if planned["run_pipeline"]:
                execute(state, {**planned, "rerun": rerun}, persist)
            state.pop("error", None)
        except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
            state["status"] = "failed"
            # Provider/context errors may contain source text. Detailed stage
            # output remains in the private worktree log/diagnostics.
            state["error"] = str(exc) if isinstance(exc, BatchError) else f"{type(exc).__name__}: inspect the worktree, execution log and pending contracts before retrying."
        persist()
        results.append(dict(state))
    return {**planned, "results": results}
