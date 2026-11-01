# Optional provider/model fallback

Fallback is **disabled by default**. One configured backup may replace a failed
provider generation within the same operation. The structured operation runner
owns this decision; an adapter still makes exactly one request to its frozen route.
No successful earlier pipeline stage needs to restart when a configured backup
is selected. Fallback does not approve CV changes or guarantee output accuracy.

## Keep the primary and add Codex as backup

For future runs, add only these settings to the project's local `.vita/.env`
before starting the batch. Keep its existing provider/model entries and all
existing extraction overrides. Do not replace its Codex registry model with the
backup model: the backup has an independent exact model assignment.

```env
VITA_FALLBACK_ENABLED=true
VITA_FALLBACK_PROVIDER=codex
VITA_FALLBACK_MODEL=gpt-6.1-sol
# Optional; omit to inherit existing Codex reasoning configuration.
VITA_FALLBACK_REASONING_EFFORT=high
```

Codex uses Vita CV's existing local Codex CLI login/authentication and read-only
generation sandbox. **No `CODEX_API_KEY` is required.** Installing/authenticating
Codex is still necessary. The exact model ID is passed to Codex; model access and
availability were not verified through a live request during development.

Run normally, keeping the chosen approval policy:

```sh
vita run --auto --approval unattended --language en --json
vita import jobenu applications.json --base-branch master --run --approval unattended --json
```

`human`, `auto`, and `unattended` retain their different approval meanings.
Fallback never turns pending/rejected factual changes into approved changes.
In particular, `auto` may still pause at Adapt/Cover after successful generation.

Settings follow existing `.env` conventions: process environment wins over the
project file for the same variable. Stage-specific `EXTRACTION_`, `ANALYSIS_`,
`ADAPT_`, `REVIEW_`, and `COVER_FALLBACK_*` values override `VITA_FALLBACK_*`.
Review inherits unspecified `ANALYSIS_FALLBACK_*` values before global defaults;
requirements drafting uses the extraction policy. Additional qualitative tasks
use their parent stage's policy. For example:

```env
# Only Cover uses a backup, with global fallback still off.
VITA_FALLBACK_ENABLED=false
COVER_FALLBACK_ENABLED=true
COVER_FALLBACK_PROVIDER=codex
COVER_FALLBACK_MODEL=gpt-6.1-sol
COVER_FALLBACK_REASONING_EFFORT=high
```

The host supports reasoning overrides for Codex, OpenAI, and OpenRouter. The
accepted host values are `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`,
and `ultra`; actual support depends on the selected model/endpoint. An unset
override inherits the backup provider's existing settings, never the primary's
credentials or vendor-specific options. Unsupported provider/settings combinations
and incomplete/duplicate routes fail validation before generation. Validation
does not test availability, account access, installed CLI authentication, or model
quality. Explicit generation checks remain exact:

```sh
vita providers check --provider codex --model gpt-6.1-sol --generate --json
```

That command may consume usage and cannot fall back to another model/provider.
Discovery alone is not a successful generation check.

## Eligible errors and budget

The default categories are `overloaded`, `rate_limit`, `server_error`, `timeout`,
and `connection`. The first eligible provider failure selects the backup when
there is budget left. Once switched, the operation never returns to the primary
or selects another backup. Successful primary calls never generate on the backup.

You may explicitly opt into `authentication`, `permission`, `invalid_model`, or
`quota_exceeded` as well. Billing/payment-required HTTP 402 and quota/billing
limits in HTTP 429 use `quota_exceeded`; ordinary 429 uses `rate_limit`.
For example, retaining a primary whose model access fails requires an explicit
choice to include `invalid_model`:

```env
VITA_FALLBACK_CATEGORIES=overloaded,rate_limit,server_error,timeout,connection,invalid_model
```

The category list replaces its inherited list. Invalid configuration, missing
credentials/CLI, refusal, generic/unclassified provider errors, malformed JSON,
schema/host validation errors, invalid TeX, source conflicts, approval gates,
rejections, and persistence failures **cannot** trigger fallback. Format/schema
recovery can retry the current route within its existing budget.

`VITA_PROVIDER_MAX_ATTEMPTS` remains the shared total budget (default 3, range
1–5) for primary calls, backup calls, transport retries, schema negotiation and
format recovery combined. It is not multiplied per provider. A budget of 1 leaves
no opportunity to use a backup. Provider `Retry-After` and existing capped backoff
apply to same-provider retries, including a same-provider model switch. A different
provider may be selected immediately. A Retry-After beyond the cap stops a
same-provider retry/switch. An explicit new invocation has a new bounded budget.

## Add a backup to an existing failed run

Editing `.env` on a stopped workflow can invalidate its captured settings and
consent. Instead, use an exact-plan amendment scoped to **that failed step**.
Run this in the returned Jobenu worktree, or the standalone durable workflow
project, after the failing process has stopped:

```sh
vita fallback amend cover --provider codex --model gpt-6.1-sol --reasoning-effort high --dry-run --json
vita fallback amend cover --provider codex --model gpt-6.1-sol --reasoning-effort high --apply --plan-id EXACT_PLAN_ID --json
```

Use the actual failed step name. If its category needs explicit opt-in, repeat
`--categories` in both commands. The preview exposes preserved and invalidated
step names, the unchanged checkpoint, the old/new policy, and the previous
operation ID. Applying stores an append-only amendment and a step override;
it does not rewrite the old checkpoint hashes or change primary settings.
Completed earlier stages remain valid only with their captured dependencies.

Then repeat the Jobenu import command, or:

```sh
vita run --auto --approval unattended --language en --resume --json
```

Repeat the original language/provider override and approval mode. A Jobenu plan
must be refreshed after amendment; its fingerprint includes the amendment history.
No whole-pipeline `--rerun` is needed merely to add/change this failed-step backup.
Jobenu worktrees retain their copied configuration; changing the parent's config
does not silently replace settings in an existing worktree. Amend that worktree.

An amendment is allowed only for the current failed provider step with an eligible
failure and valid captured inputs/job/criteria/settings. Pending/rejected or
approved-but-unapplied drafts need their existing factual decision/recovery flow.
Stale/missing checkpoints or missing job provenance cannot authorize reuse. This
includes legacy non-durable runs without a checkpoint: they cannot safely acquire
invented recovery history. Legacy 2.14.0 Jobenu/durable checkpoints with valid
captures can be amended without migrating or overwriting their hashes.

Amendments affect that workflow, not future unrelated runs. A fresh start gets new
run provenance and archives the prior standalone workflow. A resume retains the
approval run and records new operation/attempt lineage. Successful Adapt is never
re-generated merely to retry Cover; Cover checks the matching applied Adapt source.
Atomic writes, recoverable drafts, immutable requirements, and rejection history
keep their existing meaning. A failed publication retries its approved draft,
not another provider generation.

## Vita Tree contract and follow-up

Tree support is **not automatic**. Its agent must add the configuration controls,
query `vita fallback capabilities --json`, and implement preview/apply in the
failed worktree. The capability response has `schema_version=1` and
`version=provider-fallback/1`; it lists default/allowed categories, one-backup limit,
the shared budget, and amendment command. `vita approval-policies --json` also
includes this under `provider_fallback`.

Operation `STEP.outcome.json` retains schema version 1 with additive fields:
`routing.version`, `routing.policy`, `routing.requested`, `routing.chain`,
`routing.effective`, and `parent_run_id`. Each attempt records `attempt_id`,
`parent_attempt_id`, `kind` (`initial`, `retry`, or `fallback`), `route_index`,
requested/effective route, and `fallback_reason`. Provider error contracts retain
sanitized category/status/retryability and bounded attempt counts. Attempt IDs
correlate with diagnostic journals. Raw provider responses and credentials never
belong in these fields.

Standalone `--json` host outcomes expose a sanitized `operation` subset; full
workflow and Jobenu results expose `operation_outcomes` by step. No new operation
is represented as a fresh successful provider call when preparation failed.
Legacy attempts with no kind/identity remain explicitly unreported. Assessments
retain primary requested and actual effective model/reasoning provenance, with
`assessment_execution.operation_run_id` linking their operation. A backup result
is never mislabeled/reused as a primary-model cache hit.

Tree must keep retries and fallback distinct, display requested versus effective
routes, preserve approval statuses, and use exit codes/JSON status rather than
parsing stdout. It must not edit hashes, force `--rerun`, silently enable fallback,
or treat a generation-check failure as permission to test another model.

Tests use deterministic synthetic sources and fake providers. No live AI requests,
real CV edits, or model-quality/availability claims are part of this verification.
