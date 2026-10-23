# Job extraction and comparable evaluations

`vita run --auto` executes optional extraction, analysis, CV adaptation, review,
and cover letter construction. Each task uses its existing bundled and custom
skills. Extraction only receives the job description. Later tasks receive the
CV and the selected job context. All generated metadata and reports go into
`.vita/results/`; document sources and PDF build destinations retain their
existing configuration.

## Configuration

Put these settings in **`.vita/.env`**, alongside API keys, or export them in
the process environment. Process values take precedence. Inline comments and
single/double quoted values are supported; shell interpolation is not performed.
`vita init` creates `.vita/.env.example`; `vita sync --auto` adds missing files
and task skill folders without replacing existing settings.

```env
ENABLE_JD_EXTRACTION=true
EXTRACTION_PROVIDER=gemini
EXTRACTION_MODEL=gemini-2.5-flash
ANALYSIS_PROVIDER=openai
ANALYSIS_MODEL=gpt-4o

GEMINI_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key
OPENROUTER_API_KEY=your_openrouter_key

# Optional independent routes:
# ADAPT_PROVIDER=openrouter
# ADAPT_MODEL=openai/gpt-4o
# REVIEW_PROVIDER=openai
# REVIEW_MODEL=gpt-4o
# COVER_PROVIDER=gemini
# COVER_MODEL=gemini-2.5-flash
```

The safe default is `ENABLE_JD_EXTRACTION=false`: upgrading does not add an API
call or require a Gemini key. With extraction enabled, its default route is
`gemini` / `gemini-2.5-flash`. Unset analysis, adaptation, and cover routes use
the existing first provider in `.vita/extensions.json` and its model. Review
inherits `ANALYSIS_*`, unless explicitly configured. Selecting another review
provider uses that provider's model default instead of an analysis model from
a different vendor. Models are passed through, so new compatible model IDs do
not need a registry update.

`--provider` overrides the selected task's provider. A model explicitly tied
to a different stage provider is discarded for that override. For `vita run`,
this flag applies to downstream tasks; extraction keeps its independent route.
Use `vita extract --auto --provider <name>` to override extraction itself.
OpenAI and OpenRouter use their Chat Completions endpoints through the existing
`generate(system_prompt, user_prompt, provider=None, model=None)` interface.
Gemini, Codex CLI, and other existing adapters remain available.

## Extraction and cache behavior

```sh
vita extract --auto        # Force a fresh extraction, even when toggle is off
vita analyze --auto        # Extract if enabled and no valid cache exists
vita run --auto            # Refresh extraction first when enabled
vita build both            # Compile the resulting CV and cover letter
```

The cache records a SHA-256 fingerprint of the decoded `job.md` text. A valid,
matching `job.json` is reused, even when extraction is disabled. Otherwise,
disabled extraction passes raw JD text to downstream tasks. Enabled extraction
must succeed before those tasks run. Missing, malformed, or stale metadata is
never silently used for another job.

`job.json` is authoritative: VITA regenerates `job.toon` from validated JSON
when it is missing or changed. Downstream prompts receive this TOON directly,
without also including a duplicate raw JD. Edit `job.json` to correct an
extraction while preserving its schema and source fingerprint, or force a new
extraction. An altered context invalidates old analysis/review comparisons.
Add task-specific guidance in `.vita/skills/extract/*.md` if needed.

Manual commands omit `--auto` and make no model calls. `vita run` generates
ordered task prompts, including extraction when enabled. Execute them in order;
each evaluator prompt describes the validation and rendering helpers to use.
Stage provider routing applies to automatic execution; manual prompts run in
the assistant the user chooses.

## Versioned artifacts

| Artifact | Contents |
|---|---|
| `job.json` | Validated extraction envelope |
| `job.toon` | Deterministic TOON representation of that envelope |
| `analysis.json`, `review.json` | Identical evaluation schema |
| `analysis.md`, `review.md` | Reports rendered from validated JSON |
| `analyze.md` | Compatibility copy of `analysis.md` |
| `delta.json`, `delta.md` | Comparable changes after a matching review |

The machine-readable contracts are `JOB_SCHEMA` and `EVALUATION_SCHEMA` in
`vita.helpers.structured`. Both use `schema_version: 1`. Unknown fields,
duplicate JSON keys, non-finite numbers, and invalid scores are rejected before
replacing successful reports. Each artifact is written through a temporary
file and replaced atomically; the group of files is not a database transaction.

The job envelope contains `source_sha256` and a `jobs` array. Every job has
`id`, `title`, `company`, `location`, `date_posted`, `hard_skills`, `soft_skills`,
`requirements` (`must_have` and `nice_to_have` arrays), `responsibilities`, and
`summary`. Unknown metadata is null; unspecified lists are empty. Multiple
`# Job N` sections retain ordered IDs `job-1`, `job-2`, etc.

TOON encoding follows the [official format specification](https://toonformat.dev/reference/spec)
for the job contract's nested objects, primitive arrays, and object lists. The
helper is deliberately scoped to this schema rather than being a general TOON
library. Token savings depend on the data and tokenizer.

Both evaluations contain:

- `overall_score`: number from 0 to 100.
- `category_scores`: `hard_skills`, `soft_skills`, `experience`,
  `responsibilities`, and `keywords`, each from 0 to 100.
- Host-rendered `executive_summary`, qualitative `qualitative_summary`,
  `strengths`, `gaps`, and `recommendations`.
- Host-rendered `comparison`: `status`, `baseline_overall_score`, and
  `overall_delta` (percentage points).
- `metrics.criteria`: objects with stable `id`, `job_id`, `category`,
  `criterion`, `importance`, `status`, `evidence`, and `feedback`.
- `metrics.matched_count`, `partial_count`, `missing_count`, and `total_count`.
- Host-generated `metadata`: job, context, and criteria fingerprints plus
  `rubric_version`.

Markdown reports include an executive summary, scoring table, strengths,
gaps, actionable feedback, and criterion-level evidence.

## Scoring and deltas

### Approved canonical requirements

To compare CVs on a common scale, freeze JD requirements before evaluating any
candidate. This workflow uses only `job.md`, independently of `main.tex` or
`.vita/cv.yaml`:

```sh
vita requirements draft --auto
vita requirements show
vita requirements approve FULL_REVISION_ID
vita analyze --auto
vita review --auto
```

`draft --auto` uses the extraction-stage provider/model and bounded structured-output
validation. `draft` without `--auto` generates a JD-only prompt. To compile a
proposal produced by an external agent or edited during review, use
`vita requirements draft --input proposal.json`. Show accepts an optional revision
ID to inspect earlier versions. It reports approval status separately from the
immutable revision document. Draft generation never approves anything. Review
the atomicity, deduplication keys, source references, and classifications, then
approve that exact full revision ID. Drafting a replacement for an already
approved JD leaves the previous approval active until the replacement is approved.

Revisions use schema version 1 and content-addressed immutable IDs. Each capability
has a stable concept ID/key, criterion text, category, `required`/`preferred`/`unclear`
classification, importance, weight, ambiguity explanation, and exact quoted source
references with job IDs and original 1-based line ranges. IDs derive from job ID
and normalized concept key, so they do not depend on a candidate or evidence status.
Changing text, classifications, references, or job content changes the revision ID.

Required capabilities weigh 2, preferred capabilities 1, and unclear capabilities 0.
Explicit preferences such as “6sense is a significant plus” remain preferred.
“Must-Have or Strong Plus” sections remain unclear unless an item explicitly resolves
its importance. Unclear items stay in the assessment for clarification rather than
becoming confirmed capability penalties. Alternatives retain their meaning; independent
requirements should be atomic. Employment conditions (including conditional home-office
logistics) are kept in a separate, unscored list. Source quotes and ranges are validated.

The compiler merges repeated normalized concepts/text across skill, keyword, and
responsibility labels within each job. There are no separately weighted keyword-only
criteria. Semantic grouping still requires review: extraction cannot prove that
differently worded concepts are equivalent. Approval freezes the reviewed result.
Analyze and Review must return exactly that taxonomy; the host supplies weights,
classifications, source references, and denominators, rejecting changed or extra criteria.
Reports include `metadata.requirements_revision`, `metrics.weighted_available`,
`weighted_earned`, `category_denominators`, and separate `employment_conditions`.
A revision with only unclear capabilities has denominator 0 and is shown as unscored.

Approved requirements override optional job-metadata extraction. The pipeline reuses
them without regenerating metadata or canonical criteria. Thus changing extraction
wording, CV content, or candidate branch cannot change the scoring denominator.
Context and criteria fingerprints include the approved revision. A changed job creates
a pending source revision on the next preparation and stops assessment until new
requirements are drafted and approved. Changing the approved revision also invalidates
dependent baselines. Prior revisions and reports remain intact for history; they are
not silently accepted as current assessments.

The default store is `<git-common-dir>/vita/requirements`, shared by branches and Git
worktrees. Non-Git projects use `.vita/requirements`. To share between separate projects
or repositories, set an absolute `VITA_REQUIREMENTS_DIR` in the environment or `.vita/.env`.
Alternatively, transport an approved revision explicitly:

```sh
vita requirements export approved-job.json
# In another project containing the identical job.md:
vita requirements import approved-job.json
```

Import is an explicit reuse/approval action for that exported revision; hashes, source
references, classifications, and the current job content are checked before activation.
The export includes the JD, not candidate data. Local `.vita/requirements-state.json`
tracks the project binding/latest draft. Back up/export approvals when moving projects;
the default shared Git store is not part of ordinary tracked source files.

Integration helpers live in `vita.helpers.requirements`: `compile_revision`,
`save_revision`, `approve_revision`, `approved_revision`, and `active_requirements`,
with public `PROPOSAL_SCHEMA`/`REVISION_SCHEMA`. An approval action belongs to the user
or authorized UI, never the extraction model. Existing `job.json`/TOON and version-1
assessment files remain readable. Projects with no approval or canonical-project
binding keep the legacy flow; its CV-derived taxonomies are not a common candidate
ranking scale. Once opted in, an unapproved or changed JD cannot silently fall back
to that legacy flow.

VITA computes scores and counts from criterion statuses instead of trusting
model arithmetic. Must-have criteria weigh 2; nice-to-have criteria weigh 1.
Matched earns full credit, partial earns half, and missing earns zero. Overall
and category scores are weighted earned credit divided by available credit,
multiplied by 100 and rounded to two decimals. A category without criteria is
stored as zero and displayed as N/A. Repeated keywords earn no extra credit.

JSON, the Markdown executive summary, and scoring/comparison tables use the
same calculated record. All displayed scores and changes use two decimal places;
deltas subtract the already rounded before/after scores. The executive summary
contains the host's overall documented-coverage score and baseline statement.
Model commentary is requested as qualitative prose, stored separately in
`qualitative_summary`, and displayed under **Qualitative commentary**. Assessment
score and baseline-comparison clauses are removed from model narrative fields;
candidate achievement percentages such as a 40% cost reduction are retained.
Criteria wording and quoted source evidence are preserved.

For a review, `comparison.status` is `available` only when the host validates a
matching initial assessment and calculates a comparable delta. Otherwise it is
`unavailable`, with null baseline score/delta. Initial assessments use
`not_applicable`. These fields describe the baseline at assessment time, not a
later filesystem lookup. Model-authored availability claims cannot set them.
When calling `finalize` directly for a review without a baseline, pass
`step="review"`; without an explicit step the helper retains its initial-analysis
default. The CLI and generated instructions pass the appropriate step.

Older schema-version-1 reports remain accepted: the new fields are optional on
input. Loading a legacy baseline or rendering an old report recalculates its
scores and normalizes commentary in memory, leaving the saved source unchanged.
If a legacy report did not record baseline availability, its rendered summary
says so (`not_recorded`) rather than trusting a model's claim. Legacy reports
with valid provenance still work as baselines for new comparisons.

Review reuses exactly the initial criterion IDs, job IDs, categories, wording,
and importance. A response that adds, removes, or changes those criteria fails
validation. Models still make subjective judgments about evidence; scores
measure documented coverage and are not calibrated hiring probabilities. Extraction
can omit or misinterpret a requirement, so inspect its output for important
applications.

`vita.helpers.evaluation.compute_delta(before, after)` accepts parsed evaluation
objects and returns overall/category before, after, and signed delta values,
plus criterion status changes. It rejects different jobs, contexts, criteria,
or rubric versions. Positive and negative changes are both supported. For
example, a partial-to-matched change on the only criterion yields 50 → 100,
a delta of +50 points. Review without a matching baseline still produces its
report but cannot produce a comparable delta. A successful new analysis or
unrelated review removes stale delta files.

The provider request formats follow the official
[OpenAI Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
and [OpenRouter Chat Completions API](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion).

## Shared scoring assessment and unchanged-input controls

Analyze and Review now use one `assess.md` prompt and one
`assessment-judge.md` skill, with the same JSON assessment and evidence contract.
The judge sees current captured sources, JD context, and locked criteria. It does
not receive the stage name, previous score/statuses, or review writing advice.
For approved canonical requirements, identical inputs produce identical judge
payloads across both stages. The host still verifies the approved revision,
criteria/weights, job hashes, evidence quotations, and calculated scores.

Customize the scoring judge in `.vita/skills/assess/`. Existing Analyze/Review
writing skills and task prompts are used only for optional, separate commentary:

```sh
vita analyze --auto
vita review --auto                 # reuse a valid identical-input assessment
vita review --auto --reassess      # explicitly request a fresh judgment
vita review --auto --qualitative   # additional writing audit, separate from scoring
```

`--qualitative` is also available on Analyze. It writes
`<stage>-qualitative.json` and `<stage>-qualitative.md`, linked to the assessment
execution and source/job hashes, with its own provider/model, reasoning and
prompt provenance. It cannot change criterion judgments or host scores.
Assessment/baseline comparison claims are removed from this commentary while
achievement metrics remain. It is still model writing advice, not verified fact.

Each automatic assessment records `metadata.assessment`: contract version,
candidate-graph and CV/include fingerprints, raw job/context/criteria hashes,
approved revision, requested and reported provider/model/reasoning, effective
configuration fingerprint, date context, judge/system/prompt hashes, host and
generation schema hashes, and host-code fingerprint. The cache `key` covers
these input descriptors. Model aliases and provider defaults describe the
configured request; they do not identify immutable server weights or guarantee
determinism. `metadata.assessment_execution` records a unique execution ID,
generated/reused/reassessment mode, reuse origin, UTC timestamp, final attempt
count, actual final user-prompt hash (including schema/retry instructions), and
output mode. Credentials and the private resolved provider session are never
serialized into these fields.

The exact-input cache lives in `.vita/results/assessments/<key>.json`. A valid
identical initial assessment takes precedence over a later forced reassessment.
Reuse makes no scoring provider call and records a successful outcome with zero
attempts and a cache origin. Before reuse, the host validates the envelope checksum,
complete input descriptor, current sources, current job/revision, taxonomy, and
source-bound evidence. Stale captures, unverifiable matched/partial evidence,
corrupt entries, and changed inputs cannot supply cached judgments. Missing
criteria can be reused without an invented evidence claim. Cache files are local
candidate artifacts and should be handled like the CV; they are not signed audit
records against a malicious local editor.

Legacy reports remain readable and comparable under the existing job/taxonomy
guards. They cannot seed exact-input reuse without the new provenance and verified
sources. Before a legacy taxonomy is locked, its first generation has no fixed
criteria input and is not cacheable. Once locked, subsequent assessments use it
explicitly; prefer the independently approved canonical requirement set for
cross-candidate and cross-stage controls. Unreported custom-adapter routing,
external-assistant execution, and inherited Codex model/reasoning disable reuse.
Configure explicit model and reasoning settings to make Codex reuse eligible.

`assessment_comparison` in reports and deltas separates CV/include edits from
knowledge/approval changes, configuration changes, unchanged-input reuse, and
fresh reassessment. Unknown/stale provenance is labelled as such. An unchanged
CV's score difference is never presented as a tailoring improvement. Even with
actual source edits, a delta compares recorded judgments and is not causal proof
that tailoring helped. Delta reports include evidence/citation changes as well
as criterion status changes. Changes to model, reasoning, judge, schema, host
code, date context, job context, or sources invalidate exact-input reuse.

Generated prompts include the same shared judge payload and separate host saving
instructions. Recapture sources and prepare the current job/request at execution
time, especially after adaptation or deferred extraction. A chosen external
assistant is not automatically the configured API provider: its runtime identity
is explicitly unreported and cannot be cached as a verified API execution. Public
integration helpers are `prepare_assessment`, `new_execution`, `finalize`,
`save_evaluation`, and `run_assessment`; never serialize `request.session`.

The [issue #36 benchmark control](https://github.com/ABDELLAH-Hallou/vita-cv/issues/36)
observed cross-stage inconsistency with different Analyze/Review prompts. It did
not isolate same-prompt stochastic variation or estimate its frequency. Every
automated quality/regression and installed-wheel run includes paired unchanged
controls using the shared judge; the installed control also records
`unchanged-control.json`. Future/live quality benchmarks must include an unchanged
Analyze/Review pair alongside edited-CV cases, retain source/configuration/prompt
provenance, and report cache reuse separately from forced reassessment. Mocked
controls test pipeline behavior and attribution, not live-model reliability.

## Candidate evidence provenance

Analyze and Review capture the configured `tex_entry` and the supported literal
project-local `\input{file}` / `\include{file}` graph before contacting the model.
Extensionless includes resolve to `.tex` from the project working directory;
cycles are visited once, commented/dynamic includes and paths outside the project
are excluded. Including `job.md`, generated `.vita/results/`, skills, or prompt
files does not make them eligible candidate evidence. Including `.vita/cv.yaml`
does not bypass knowledge approval. Missing or unsupported sources cannot supply verified evidence.
The existing job-hash, context-hash, approved requirement revision, and locked
taxonomy checks still apply.

Each captured source has a `src-…` identity covering its relative path, kind,
text SHA-256, and any approved knowledge spans. `metadata.candidate_snapshot`
stores the captured text and identities with an integrity hash, so reports can
be inspected offline. It contains candidate content; handle it like the CV.
Text is UTF-8 with universal newlines normalized to LF. Lines are 1-based and
inclusive, including blank and comment lines. The snapshot proves local text
support, not authorship, factual truth, or real-world employment.

Provider criteria return `evidence_kind` (`direct`, `inference`, or `none`) and
`evidence_refs`. A reference has `source_id`, `quote`, `line_start`, and `line_end`.
Either supply both line numbers or set both to `null` for quotation-only lookup.
The quote must occur exactly within the cited span or eligible source text.
`evidence` must equal the referenced quotes joined with a newline; explanatory
or inferred prose belongs in `feedback`. This prevents replacing evidence with
an invented employer while retaining unrelated, otherwise valid references.
Missing criteria use empty evidence/references and `evidence_kind: "none"`.

The host always replaces `evidence_verification` with a status and actionable
reason. Unknown IDs, unsupported text, stale sources/approvals, invalid spans,
and quotes outside approved knowledge spans are explicitly **unverified**.
Changes anywhere in the captured candidate graph during generation invalidate
that capture; rerun with current sources. Supported quotes are **verified**;
empty missing-evidence claims are **not_applicable**. Old reports without a
snapshot are **not_recorded**, explicitly described as unverified. Input fields
remain optional for backward compatibility; missing citations in new reports
are unverified. Native generation schemas require all evidence fields.

Verification and semantic adjudication are separate. Finding a quote never
promotes a partial criterion to matched. Inference receives at most partial
credit, even if the model requests matched. Direct but incomplete evidence must
remain partial; scope, duration, proficiency, and compound requirements still
need model/user judgment. Unverified judgments retain their model-assigned
statuses and calculated scores for compatibility, with a host warning in JSON,
Markdown, and the executive summary. They are not certified coverage. Check the
criterion verification status before treating a score as source-backed.

Review captures the updated CV and uses its current source IDs. An initial
assessment's older snapshot is valid historical evidence, not proof about the
current CV. Delta comparison ignores differences in candidate snapshots while
continuing to require identical job, context, rubric, and criterion provenance.
Rendering a historical report rechecks its embedded hashes and quotations; it
does not silently rebind them to files currently on disk.

### Verified knowledge-base spans

`.vita/cv.yaml` is eligible assessment evidence only for explicitly user-verified
line ranges. Mere file presence, YAML keys named `verified`, and previous AI
reports do not confer verification. Record approval in `.vita/cv-verified.json`:

```json
{
  "schema_version": 1,
  "source_sha256": "<SHA-256 of normalized UTF-8 cv.yaml text>",
  "verified_spans": [{"line_start": 3, "line_end": 5}]
}
```

After reviewing those lines, an authorized caller can write this approval with
`vita.helpers.structured.write_artifact` and `json_text`; compute the hash using
`vita.helpers.candidate_evidence.digest(Path(".vita/cv.yaml").read_text(encoding="utf-8"))`.
Do not approve content automatically from a model assertion. Invalid/missing
approvals or a changed knowledge file exclude it until explicitly reapproved.
Only quotations wholly inside an approved range can verify. Adapt/Cover retain
their existing knowledge context behavior; this approval governs assessment
evidence, not edits to the CV.

For direct integrations, capture with
`capture_candidate_sources(configured_entry)`, pass the snapshot as `sources=`
to both `evaluation_instruction` and `finalize`, then use `save_evaluation`.
Generated prompts embed the same contract and instruct the executing agent to
recapture current sources before finalizing if files changed. Standalone
`finalize` without `sources=` captures current configured sources at call time;
pass the original snapshot to detect changes during a provider call.

Regression and installed-wheel checks replay issue #42's fictional-employer
mutation beside legitimate, included-file, verified-knowledge, and stale-source
controls. These synthetic checks verify provenance handling, not model honesty
or factual/semantic accuracy on real candidate documents.

## Structured output and format recovery

Automatic `extract`, `analyze`, and `review` request schema-constrained output
through Codex `--output-schema`, OpenAI/OpenRouter `response_format`, or Gemini
`responseMimeType`/`responseJsonSchema`. OpenRouter requests endpoints that support
the supplied parameters. The generation schema uses a conservative JSON Schema
subset; the host still enforces the full schema, finite score ranges, unique IDs,
job provenance, evidence requirements, and locked review criteria. Evaluation
metadata is excluded from model output and supplied by the host. Extraction must
return the source fingerprint supplied in its prompt; a mismatch is rejected.

By default there are at most **three adapter calls per operation**, including
transient failures, schema-negotiation rejection and format recovery. Malformed JSON, schema violations, and invalid job
or review criteria can trigger a new generation from the original evidence and
contract. VITA does not patch candidate facts or accept a partial assessment.
The selected provider, model, and configured reasoning effort stay fixed across
attempts. Codex settings not overridden by VITA remain inherited from the CLI.

An endpoint explicitly rejecting the structured-output feature (or an older
Codex CLI rejecting `--output-schema`) can fall back to prompt-based JSON with
the same host validation. Other adapters use this validated prompt mode directly.
Set `"structured_output": "off"` in that provider's `.vita/extensions.json`
configuration to select it explicitly. Authentication, exhausted billing quota,
invalid models, refusals, incomplete responses and invalid native schemas fail
promptly. Transient overload, rate limits, timeouts and connection failures can
retry under the same operation budget. No failure selects another provider or model.

Each execution records `.vita/results/attempts/<step>-<run_id>.json` and updates
`.vita/results/<step>.outcome.json`. Read `status` (`running`, `success`, `failed`)
before consuming existing reports: a failed rerun preserves previous successful
artifacts. Each attempt records its number, response category, output mode, route,
and response hash/length when text was returned; JSON syntax failures include a
line/column/offset. Host validation failures include a safe constraint description.
The final record includes `recovered` on success, or an
`error.code` and actionable `error.action` on failure. Failure codes include
`structured_output_invalid`, `provider_error`, and `artifact_error`; the CLI exits
nonzero. Provider HTTP status is recorded when available. Raw model responses,
CV text, prompts, credentials, and provider error bodies are not stored in these
records. Keep per-run records when reporting a failure; each rerun has a new ID.

Generated-prompt mode does not call providers or run this retry loop. Its prompts
retain the host-validation instructions for the agent executing them. Tests and
the installed-wheel smoke check replay issue #37's constructed malformed JSON
fixture and recover successfully. The original live S01 response was not retained,
so this is a deterministic regression replay, not a rerun of that exact response
or evidence of live-model factual accuracy.

Protocol references: [Codex schema output](https://learn.chatgpt.com/docs/non-interactive-mode),
[OpenAI structured output](https://developers.openai.com/api/docs/guides/structured-outputs),
[OpenRouter structured output](https://openrouter.ai/docs/guides/features/structured-outputs),
and [Gemini generation configuration](https://ai.google.dev/api/generate-content#v1beta.GenerationConfig).

## Provider failures and bounded backoff

Automatic extraction, canonical-requirement drafting, Analyze, Review, Adapt,
Cover and optional qualitative calls use the same operation runner. Each
operation has its own run ID and capped budget. Qualitative commentary is a
separate requested operation. `llm.generate` is a single adapter attempt; direct
integrations should use `run_structured` or `run_text` from
`vita.helpers.structured_output` rather than adding another retry loop.

The default exponential delays are 1 and 2 seconds. Configure them in `.vita/.env`
or process environment:

```env
VITA_PROVIDER_MAX_ATTEMPTS=3          # 1..5, including the first call
VITA_PROVIDER_RETRY_BASE_SECONDS=1   # finite, 0..maximum delay
VITA_PROVIDER_RETRY_MAX_SECONDS=30   # finite, 0..30
```

Invalid retry settings fail before a provider call. `Retry-After` supports both
integer seconds and HTTP dates, as defined in
[HTTP semantics](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after).
When present, wait at least that long and at least the configured backoff. If
the requested wait exceeds the delay cap, stop with
`retry_stopped: "retry_after_exceeds_delay_cap"`; retrying early would violate
the requested wait. Exhaustion makes no additional call or sleep. Delayed
transport responses and timeouts can already have consumed usage; retries are
not a guarantee of exactly-once provider execution.

Provider failures retain `error.code: "provider_error"` for existing consumers.
Their versioned fields are defined by
`vita.helpers.provider_errors.PROVIDER_ERROR_SCHEMA`. For example:

```json
{
  "schema_version": 1,
  "code": "provider_error",
  "category": "overloaded",
  "provider": "gemini",
  "model": "configured-model-id",
  "step": "extract",
  "status": 503,
  "retryable": true,
  "attempts": 3,
  "max_attempts": 3,
  "exhausted": true,
  "retry_after_seconds": null,
  "action": "The provider is temporarily overloaded. Retry this step later."
}
```

`status` is the HTTP status or `null` for failures without one. Safe identifiers
are strings or `null` when unavailable or unsafe. `attempts` counts adapter
invocations, including format attempts; an early configuration failure can have
zero calls. The outer outcome also records `attempt_count`. Each failed provider
attempt carries its own error object; transient attempts that recover remain
in the trace while the final outcome has `error: null` and `recovered: true`.
`retryable` classifies the failure; it does not promise another automatic call
after exhaustion or a delay-cap stop.

Categories distinguish `overloaded` (503/529), `rate_limit` (429),
`server_error` (500/502), `timeout` and `connection` from `authentication` (401),
`permission` (403), `invalid_model`, `quota_exceeded`, `invalid_request`,
`not_found`, `configuration`, `unsupported_schema`, `refusal`,
`incomplete_response`, `empty_response` and unclassified `provider_error`.
Only recognized transient categories retry. Invalid-model classification uses
explicit provider markers; a generic 404 remains `not_found`. CLI stderr has
no stable structured envelope, so only explicit recognized status/model markers
are classified. Raw bodies, URLs, exception text, credentials and CLI stderr are
never copied to public errors. Internal resolution snapshots contain credentials
and must never be serialized.

### Discovery versus generation checks

```sh
vita providers check --provider gemini --model exact-model-id --json
vita providers check --provider gemini --model exact-model-id --generate --json
```

The first command reads one catalog page and reports `check: "discovery"` and
`generation_verified: false`. A listed model does not prove that generation is
allowed or available. Catalogs may be partial, and Codex catalog discovery is
unavailable; absence never automatically diagnoses an invalid model. The second
command explicitly sends a short synthetic generation, warns that it may consume
usage, and sets `generation_verified: true` only after a nonempty generation
succeeds. It sends no CV or JD. A successful check measures connectivity and
generation access at that moment, not content quality or later availability.

Checks save `.vita/results/provider-discovery.json` or `provider-check.json`,
with separate operation traces. `--json` prints one JSON result to stdout and
routes usage notices/provider progress to stderr. Failures exit nonzero. Both
checks preserve the exact selected route and use the same capped retry policy.
Deterministic regression and installed-wheel fixtures exercise these paths with
stubbed HTTP and sleeps; no live-availability claim follows from those tests.
