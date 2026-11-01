# Jobenu batch imports

Import a local Jobenu export into one CV branch/worktree per application.
The first adapter accepts `{ "exportedAt": "...", "applications": [...] }`.
No Jobenu API connection, URL fetching, application submission or push is performed.

## Preview and import

Run from your **personal CV Git project**, not the Vita source repository. The
selected local base must contain the committed CV you want to tailor. Configure
Git `user.name` and `user.email` for the local import commits.

```powershell
# Read-only: branch names, source IDs, base commit, role resolution and plan ID.
vita import jobenu applications.json --base-branch gen-ml --dry-run --json

# Create branches and job.md without calling AI providers.
vita import jobenu applications.json --base-branch gen-ml --approval auto

# Create branches and run the saved AI configuration.
vita import jobenu applications.json --base-branch gen-ml --run --approval auto

# Human mode: confirm the batch plan; review document proposals before application.
vita import jobenu applications.json --base-branch gen-ml --run --approval human
```

`--approval` is required for writes. `--dry-run` makes no project changes or
model calls and does not require an approval mode. Default filters select `SAVED`,
non-demo records. Repeat `--status` to include specific statuses, or use
`--status ALL`. `--include-demo` explicitly includes demos. Empty filtered batches
do nothing. Malformed/duplicate IDs or missing company/title/description fail
before branching. Limits: 10 MiB and 1,000 applications per export.

## Base and naming preferences

Base precedence: `--base-branch`, Jobenu preference, project
`default_base_branch`, then `master`. Missing bases are errors; Vita does not
silently create a base from the current checkout.

Example `.vita/config.json` additions (keep your other settings):

```json
{
  "default_base_branch": "master",
  "default_language": "en",
  "integrations": {
    "jobenu": {"base_branch": "gen-ml", "language": "fr"}
  }
}
```

Names follow `etp-company-role`, e.g. `etp-acme-ml`. Company names become Git-safe
slugs. Existing role aliases win; recognized phrases handle qualifiers such as
“Machine Learning Engineer, Foundational AI”. Unknown titles get a slug and
`role_resolution: slug_fallback` in the preview. To choose an abbreviation, add
the **full title** to `.vita/extensions.json`:

```json
{"role_aliases": {"RESPONSABLE DATA, IA & FACTORY H/F": "data-ai"}}
```

Distinct postings with the same company/role or a taken branch name receive a
deterministic identity suffix. No existing branch is overwritten. Locked companies
cannot acquire new imported branches.

## Files, isolation and settings

Every application starts from the **same pinned base commit**, in a separate
worktree under `.vita/imports/jobenu/worktrees/`. The parent checkout and dirty
CV files remain untouched. Commit parent CV edits to the base first if they should
be included: uncommitted parent CV text is not copied into the worktrees.

Each branch gets an import commit containing **only `job.md`**. Descriptions retain
their original wording; JSON-fenced metadata preserves Jobenu IDs, URL, status,
location, compensation, work mode, dates, notes and other export fields. Imported
text is job context, not executable instructions or candidate evidence. Base/export
provenance lives in the private index rather than the JD, so the same job hashes
identically across different CV bases.

New worktrees snapshot the current project's config, extensions, `.env`, custom
skills, knowledge base and knowledge-verification manifest. Prior assessments,
prompts, factual proposals and diagnostics are not copied. A canonical-requirements
opt-in marker is preserved: a new JD cannot silently downgrade the project to legacy
scoring. Linked settings/skills must be copied into the project before import.
Credentials stay local and are never staged by import commits.

`--run` calls the existing optional Extract → Analyze → Adapt → Review → Cover
stages. Per-stage models, custom IDs, reasoning settings, skills and retry policies
remain in the existing provider layer. `--provider` overrides non-extraction stages;
extraction keeps its own route. Saved Jobenu `language`/`provider` preferences may
also be set in the integration config. Explicit command flags win. Resuming preserves
job-specific worktree preferences rather than overwriting them with parent settings.

Generated changes/results remain in that worktree. `complete` means AI stages
completed, not PDF compilation, commits, pushes or submissions. In the returned
workspace, run `vita build both` for the normal PDF handoff and review before using
`vita save`.

## Approval and resume

Modes control Vita host approval, not the AI CLI's sandbox permissions:

- **auto:** accepts the plan and permits existing host-verified changes. It does
  **not** approve unsupported factual or semantic interpretations.
- **human:** confirms the plan and stages every Adapt/Cover proposal for explicit,
  revision-bound approval, including unchanged/host-verifiable proposals.
- **unattended:** explicitly authorizes host approval of valid exact-revision
  proposals and canonical requirements for this run, including unverified changes.
  It can introduce inaccurate wording into the local CV. Verification labels stay
  unchanged. See [Unattended approval](UNATTENDED_APPROVAL.md) for commands,
  provenance, checkpoint compatibility, warnings and Vita Tree's JSON contract.

Pending results contain the workspace, step and exact proposal revision. In that
workspace, inspect and decide:

```powershell
vita facts show adapt --json
vita facts approve adapt fc-EXACT_REVISION
# Or: vita facts reject adapt fc-EXACT_REVISION
```

Rerun the import command to continue after approval. Completed stages are skipped.
Changing to `auto` never approves a pending proposal. Rejections stop that
application; other applications continue independently.

Opted-in canonical projects pause with `awaiting_requirements_approval` for a new
JD. In its workspace run `vita requirements draft --auto`, inspect
`vita requirements show`, and approve the exact revision. The shared requirements
store reuses an approved identical JD across CV bases. Human and auto modes do not
grant requirement approval. Unattended generates/validates and policy-approves the
exact canonical revision automatically.

Reimports of unchanged records/base commits are idempotent. Changed records need
`--new-revision`, which creates separate branches and preserves old work. A new base
commit creates a new variant. Editing imported `job.md` blocks reuse until the source
is reconciled. Use `--rerun --run` to explicitly reassess current worktree inputs;
CV/settings/routing changes cannot silently reuse stale pipeline checkpoints.

## Vita Tree and noninteractive clients

Use `--json` for a single machine-readable envelope. Select a base visually, then
preview with the **same run, approval and routing flags** intended for execution:

```powershell
vita import jobenu applications.json --base-branch gen-ml --run --approval human --dry-run --json
vita import jobenu applications.json --base-branch gen-ml --run --approval human --approve-plan --plan-id PLAN_ID --json
```

Plans expose schema version, plan ID, base/commit, source IDs, roles, branch names
and create/existing/conflict actions. IDs bind the source, base, preferences and
current import state. Re-preview on changes. `--approve-plan` confirms only the
batch plan. In noninteractive human mode without it, exit 2 returns
`awaiting_plan_approval` without writes.

Execution results add workspace paths, status, completed steps, private execution
log and pending revisions. This implements Vita CV's integration contract; the
actual visual batch selector belongs in Vita Tree and is not part of this repository.

Exit **0**: planned/imported/completed/empty. Exit **1**: invalid/conflicting/failed/
rejected. Exit **2**: waiting for plan, document or canonical-criteria approval.
Inspect per-entry results: execution is not all-or-nothing once creation starts.
State and `last-batch.json` are private under `.vita/imports/jobenu/`. A lock prevents
concurrent importers. After a crash inspect a stale `import.lock` before removing it.
Worktrees containing user work are never automatically deleted. Resume from the
owning parent project.
