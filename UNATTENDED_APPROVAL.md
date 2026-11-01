# Explicit unattended approval

`unattended` accepts AI proposals without human review and can publish inaccurate
wording into the **local CV and cover letter**. It does not guarantee factual
correctness. It does not push, submit applications, or publish a release.

## Choose the policy explicitly

| `--approval` | What authorizes applying a proposal |
| --- | --- |
| `human` | Explicit review and an exact-revision human decision, even for unchanged text |
| `auto` | Existing host verification policy; unverified changes still require confirmation |
| `unattended` | The user's explicit policy for this run; valid unverified proposals are automatically approved |

Existing defaults and `auto` are unchanged. Settings files, environment variables,
previous runs, and model statements such as “already approved” cannot select
unattended mode. It requires the explicit argument/API parameter on every start
and resume. `--auto` selects provider execution; `--approval` selects consent.
They are separate controls. Provider CLI sandbox flags are unchanged.

```sh
vita run --auto --approval unattended --language en
vita run --auto --approval unattended --language en --resume
vita adapt --auto --approval unattended --language fr --json
vita cover --auto --approval unattended --language fr --json
vita analyze --auto --approval unattended --json
vita review --auto --approval unattended --json
vita requirements draft --auto --approval unattended
vita requirements draft --input proposal.json --approval unattended
```

Unattended execution creates canonical JD-only requirements if needed, validates
the definition, and approves its exact immutable revision. Existing approved
identical requirements can be reused, including across CV worktrees. This is
independent of the optional metadata extraction toggle; a canonical revision
supplies the criteria directly. Ordinary legacy projects still use their existing
extraction/approval behavior. No candidate CV is supplied to requirement drafting.

Adapt and Cover retain their host-generated factual-change proposals, original
source snapshots, change classifications, uncertainty, and immutable content IDs.
The host approves the exact validated proposal under the captured policy, then
applies it with the existing atomic artifact writer. **Unverified text remains
unverified**. Cover captures the applied Adapt result and stops if that result
has since been edited. Review runs on the applied CV.

Human CLI approval is still `vita facts approve STEP FULL_REVISION`; rejection
is `vita facts reject STEP FULL_REVISION`. These commands record explicit human
review, while unattended execution uses a separate host API with policy provenance.
An explicit rejection is preserved, including when a retry adds canonical context
to an otherwise identical proposal from the same sources.

Generated prompts do not carry future unattended consent. Combining an AI prompt
command's `--approval unattended` with no `--auto` fails. `vita facts check`
supports `--approval human` or `auto`; deferred agents cannot auto-approve via a
saved prompt. Human generated prompts include the human check flag.

## Checkpoints, retries, and failures

Unattended `vita run` saves `.vita/workflow.json`; `--resume` reuses validated
completed stages and exact pending approved drafts. Repeat the language/provider
overrides and policy. Run and consent timestamp stay the same on resume; each
invocation gets a new attempt ID. A fresh run archives the previous workflow in
`.vita/workflows/`. Inspect incomplete workflows before starting fresh: an approved
but unapplied draft from another run is not silently adopted by the new run.

Jobenu uses its existing private per-application index and independent worktrees:

```sh
vita import jobenu applications.json --base-branch gen-ml --run --approval unattended --dry-run --json
vita import jobenu applications.json --base-branch gen-ml --run --approval unattended --plan-id PLAN_ID --json
```

Preview and execute with identical file, base, routing and policy flags. A policy
change changes the plan ID. Crossing into or out of unattended mode after execution
has started requires a fresh preview/consent and `--rerun --run`; prior stage
checkpoints are discarded. Historical rejections remain enforced. Existing human
to auto switching retains its conservative behavior and never approves a pending
interpretation. Repeating an unattended import resumes with the same explicit
policy; completed compatible jobs are skipped. No export preference can enable it.

Invalid JSON/schema, missing source artifacts, stale source/job/criteria/settings
captures, changed routing, concurrent source edits, rejected revisions, unsupported
configuration and failed publication still stop execution. Validated proposals
are saved before publication. A failed atomic replacement leaves an approved,
unapplied draft; the same authorized workflow can retry that exact revision without
another model generation. A publication interrupted before its final status write
is reconciled only against the approved content and captured dependencies.

Unattended proposals also receive non-expanding checks for balanced TeX groups,
environment nesting, and literal local include availability. These checks do not
prove that arbitrary TeX will compile: undefined commands, packages, engines and
fonts still need the existing explicit `vita build both` handoff. No generated TeX
is executed during approval. Existing compilation and filesystem protections are
unchanged. Compilation success is not factual verification.

## Machine-readable contract for Vita Tree

Discover support with `vita approval-policies --json` (schema version 1).
`policy_version` is `approval-policy/1`; `modes[]` exposes `id` and `description`,
and `generated_prompt_consent` is false. Display unattended as a distinct explicit
choice with the warning, not as another name for `auto`.

Jobenu `--json` plans and results include:

* `approval`: the selected CLI mode (legacy field).
* `approval_policy`: `{ "version": "approval-policy/1", "mode": "unattended" }`.
* `approval_warning`: the warning text, or null outside unattended mode.
* `plan_id`: binds the policy along with existing source/base/settings/routing state.
* `results[].approval_policy`, `results[].authorization`: captured execution policy
  and lineage for that application's run, when pipeline execution began.
* Existing `status`, `workspace`, `completed_steps`, `checkpoint`, `pending`, and
  `execution_log` fields retain their meaning. `pending` on a failed unattended
  run can identify an approved but unapplied draft after a technical write failure;
  it is not a request to approve unchecked content. Inspect the factual contract.

Jobenu exit codes remain 0 for success, 1 for failures/rejections, and 2 for approval
gates in the conservative modes. An unattended technical failure is exit 1.
Other applications continue independently. No approval pause is expected for a
valid unattended proposal; a rejected revision remains a rejection.

Standalone AI commands and `run` accept `--json`: stdout is one host outcome with
`schema_version`, `step`, `status`, `exit_code`, `approval_policy`, `authorization`,
and `warning`. Failures include a safe `action`. The outcome is also stored at
`.vita/results/STEP.execution.json`. Standalone outcomes use exit 0 or 1; use
Jobenu's richer per-application statuses for batch progress. Existing provider
attempt/error records at `STEP.outcome.json` are preserved separately.

Approval records in `adapt.facts.json` / `cover.facts.json` have an optional
`approval` object with:

```json
{
  "policy": {"version": "approval-policy/1", "mode": "unattended"},
  "revision": "fc-EXACT_CONTENT_HASH",
  "source": "unattended_run_policy",
  "run_id": "32-lowercase-hex-characters",
  "attempt_id": "32-lowercase-hex-characters",
  "authorized_at": "ISO-8601 timestamp with timezone",
  "timestamp": "ISO-8601 timestamp with timezone",
  "scope_sha256": "hash of project/job/settings/routing scope"
}
```

Human decisions use `source=explicit_human_review` and `policy.mode=human`.
The captured `authorization` has `policy`, `run_id`, `attempt_id`, `authorized_at`,
`attempt_at`, and `scope_sha256`; it contains no secrets or source bodies. Only
host code creates these records. They are local audit records, not signatures or
a security boundary against deliberate local-store tampering.

Canonical approval provenance uses the same decision object inside the approved
record in the shared requirements store. Historical decision records are retained
under `decisions/REVISION/ATTEMPT.json` in the respective contract store. Factual
Markdown displays approval provenance and unverified changes. Legacy contracts
without the optional approval field remain readable; missing provenance is not
presented as human review or as new unattended consent.

## Validation limits

Regression tests use synthetic CVs and mocked providers, including formatting,
translation, dates, metrics, semantic changes, exact-revision rejection, source
edits, malformed output, technical persistence failures, multiple applications,
policy changes and resume lineage. They test authorization and publication
behavior. They do not establish model accuracy, factual correctness, translation
quality, or human review of the generated CV.
