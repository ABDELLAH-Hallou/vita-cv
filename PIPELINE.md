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

## Candidate evidence provenance

Analyze and Review capture the configured `tex_entry` and the supported literal
project-local `\input{file}` / `\include{file}` graph before contacting the model.
Extensionless includes resolve to `.tex` from the project working directory;
cycles are visited once, commented/dynamic includes and paths outside the project
are excluded. Missing or unsupported sources cannot supply verified evidence.
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

There are at most **three provider attempts per structured step**, including any
schema-negotiation rejection. Malformed JSON, schema violations, and invalid job
or review criteria can trigger a new generation from the original evidence and
contract. VITA does not patch candidate facts or accept a partial assessment.
The selected provider, model, and configured reasoning effort stay fixed across
attempts. Codex settings not overridden by VITA remain inherited from the CLI.

An endpoint explicitly rejecting the structured-output feature (or an older
Codex CLI rejecting `--output-schema`) can fall back to prompt-based JSON with
the same host validation. Other adapters use this validated prompt mode directly.
Set `"structured_output": "off"` in that provider's `.vita/extensions.json`
configuration to select it explicitly. Authentication, quota, transport errors,
refusals, incomplete responses, and invalid native schemas fail promptly; they
are not repaired by changing models or by format retries. Transient-error backoff
is outside this feature's scope.

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
