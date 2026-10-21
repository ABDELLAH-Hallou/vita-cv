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
