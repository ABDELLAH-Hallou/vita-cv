# Standalone conformance and opt-in provider benchmarks

The opt-in [restricted agent experiment](AGENT_EXECUTION.md) adds paired Codex
baseline/restricted plans, separate optional lower-reasoning comparisons, complete
snapshots and structured observations using this same runner, spending ledger and
factual gates. Fixture success does not measure real model speed or accuracy.
Prepared live plans are not spending authorization; CLI invocation caps do not
bound internal model requests or billing.

The separate [multilingual document suite](MULTILINGUAL_VALIDATION.md) covers
synthetic English/Spanish/French/Arabic source units, long included history,
context-limit controls and Unicode PDF geometry. It does not make live provider,
semantic translation or RTL reading-order claims; independent review is pending.

Issue [#45](https://github.com/ABDELLAH-Hallou/vita-cv/issues/45) separates
adapter availability, CLI correctness, and content quality. The harness never
claims provider parity from fixture success or host-calculated CV coverage scores.

From a source checkout or extracted source distribution (Python 3.10+):

```sh
python -m scripts.benchmark --output .vita/benchmarks/fixtures-001
```

Use a **new output directory** for each experiment. `--case openai-extract-true`
selects one fixture case; repeat `--case` for several. `--timeout 600` sets the
per-command limit. `--plan-hash` prints a configuration hash without execution.

## Network-free fixture CI

The default matrix covers OpenAI, OpenRouter, Groq, Mistral, DeepSeek, xAI,
Together, Perplexity, Cohere, Anthropic, Gemini, the Google alias, and Codex CLI.
Every adapter gets extraction enabled/disabled and explicit custom model IDs.
OpenAI/OpenRouter/Codex get low and high reasoning; unsupported reasoning settings
are rejected. No discovery or supposedly equivalent model substitution occurs.

Each command runs the real CLI entry point in a fresh subprocess. Fixtures replace
HTTP/Codex transport responses, not orchestration, prompts, validation, scoring,
caching, request construction, or retries. Socket connections are blocked and
inherited API credentials removed. A missed mock fails instead of reaching a model.

Each successful case executes `vita run --auto` through Extract (when enabled),
Analyze, Adapt, Review, and Cover; then `vita build both`. It separately generates
all five standalone manual prompts and the `vita run` prompt sequence. Unchanged
controls execute initial Analyze, fresh Analyze with `--reassess`, fresh Review
with `--reassess`, and cached Review. These three comparisons have separate records;
cache reuse is not an independent generation. A synthetic Adapt actually changes
the CV, so its Review tests changed-source provenance separately.

Synthetic Adapt/Cover proposals receive **explicit fixture-only decisions through
the product's factual-change contract**, recorded as `synthetic_fixture_only`.
Live runs never auto-approve proposals.

Failure cases inject malformed JSON, 503, 429, 401, invalid models, exhaustion,
and transport-plus-format recovery under one attempt budget. Assertions cover
first failures/recovery, exit statuses, routing, provenance, prompt/output paths,
reasoning, extraction toggles, cache controls, and PDF handoff. Expected failures
pass *conformance* while remaining failures in the fixture *reliability* denominator.

Default fixture PDFs are synthetic handoff markers, **not rendered documents**.
For real PDFs, install `latexmk` and minimal LaTeX, then run:

```sh
python -m scripts.benchmark --case openai-extract-true --real-pdf --output .vita/benchmarks/pdf-001
```

CI has a separate required credential-free conformance job and a real LaTeX
handoff on Python 3.12. No CI workflow runs live providers. Only synthetic fixture
artifacts are uploaded; unit tests remain separate.

## Frozen corpus, ordering, and judging

`scripts/benchmark/corpus/manifest.json` pins all input bytes by SHA-256. Changes
require reviewed fixture revisions/checksums. The fictional JD includes a
title/body role conflict, navigation/application-form noise, and headquarters
footer location distinct from job location. These are **proposed coverage fixtures,
not previously observed extraction failures**.

All providers receive identical source bytes and oracle. Unchanged controls share
one source-reviewed, approved synthetic canonical requirement set, independent of
candidate/provider. This is a fixed test contract, not automatic approval of an
LLM's requirements proposal. Full workflows independently exercise raw/TOON input;
controls use canonical criteria to hold identities, weights and denominators fixed.

Runs are serial, concurrency 1, in listed plan order. Each case runs workflow,
manual checks, then unchanged controls. The manifest records order. For order
effects, use a separately authorized reversed plan. Do not describe this fixed
ordering/small synthetic corpus as an unbiased quality study. Prompt date context
is recorded in assessment provenance for longitudinal comparisons.

`adjudication-template.json` supplies the frozen rubric and immutable output
references. Use the same human judge/instructions across paired configurations,
blind provider identities where practical, and record judge identity, decisions,
and supporting quotations in a separate review artifact. **Content quality stays
unmeasured until adjudicated.** Unavailable providers are N/A for quality and remain
in reliability denominators. Host assessment scores are not provider quality scores.
Cross-stage inconsistencies must not be called isolated same-prompt randomness.

For the independent human validation program, use
[EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) and
[ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md). `python -m scripts.evaluation` creates
the private split structure, freezes preregistrations, prepares blank review
packets, and scores supplied independent human annotations. The conformance
corpus is development-only and must never become the independent holdout.

## Opt-in live runs and spending

Implementing/testing the harness does not authorize any live spending. A subscription
does not authorize APIs. Credentials must already be in the calling environment;
personal projects' `.env` files are not copied. Never put credentials in plans.

Copy `scripts/benchmark/live-plan.example.json`, choose accessible model IDs and
supported reasoning, and include matching extraction settings across providers
(both settings as separate cases when authorized). Obtain its exact hash:

```sh
python -m scripts.benchmark --mode live --plan live-plan.json --plan-hash
```

After **explicit spending approval**, create a separate authorization JSON:

```json
{
  "plan_sha256": "PASTE_EXACT_PLAN_HASH",
  "acknowledge_api_billing": true,
  "max_requests": 24,
  "expires_at": "REPLACE_WITH_APPROVED_TIMEZONE_AWARE_ISO_TIMESTAMP"
}
```

```sh
python -m scripts.benchmark --mode live --plan live-plan.json --authorization authorization.json --output .vita/benchmarks/live-001
```

The exact ordered plan, request cap, billing acknowledgment, and future expiration
are required before subprocess execution. Every HTTP dispatch/Codex generation,
including failures, reserves a request under a cross-process lock **before sending**.
The persisted ledger spans stages, retries, cases, and resumptions. Transport and
format recovery share the product's three-attempt operation budget. A missing
credential or discovery response is not a successful generation check.

Each invocation freezes the allowlisted authorization fields in the run's
`authorizations/` directory before dispatch. Explicitly renewed authorizations on
resume are retained as separate snapshots; the existing request count carries over.

This is a **request cap, not a currency cap or audited billing meter**. Use provider
spending limits too. Timeouts do not prove that an accepted request stopped being
processed/billed. Separate runs require separately authorized request budgets.

Live factual changes may stop for confirmation. The harness retains the revision
and exits nonzero. In that case's `workflow` directory, inspect `vita facts show adapt`
(or `cover`) and, only after a human decision, `vita facts approve STEP REVISION`.
Then resume using the same plan, authorization path, source version and settings:

```sh
python -m scripts.benchmark --mode live --plan live-plan.json --authorization authorization.json --resume .vita/benchmarks/live-001
```

Resume continues Review/Cover/build without regenerating an approved Adapt. A
second Cover confirmation may require another decision/resume. Rejected/unapplied
proposals stay blocked. Provider failures stop downstream commands and preserve
their original attempts. Resume supports deliberate confirmation stops; use a new
experiment after abrupt harness interruption or an ordinary failed run.

## Recorded results and limits

`summary.json`/`summary.md` retain planned-case reliability denominators, unavailable
and not-yet-run cases, per-provider counts, first-attempt/recovery totals, and
separate unchanged controls. Fixture reliability includes injected failures and
does **not** measure real provider uptime.

`manifest.json` records exact configuration/plan, corpus, Git revision when
available, Vita/Python/platform versions, host/adapter/prompt/skill source hashes,
ordering and limits. Per-command folders preserve exit status (null for timeout),
timing, stdout/stderr, frozen output paths/hashes, assessment provenance,
outcomes/attempt categories, and actual transport metadata. Project execution
journals retain prompts, responses, and detailed failures under the existing
diagnostics/redaction/retention policy.

`transport.json` records wire model IDs, reasoning, sampling temperature (null
means omitted/provider default, not zero), schema hashes, accessible returned
model/snapshot IDs, timing/status, and available provider-reported token usage.
Codex CLI's final-message interface lacks stable usage/snapshot metadata, so it
remains unknown. Unknown usage is null, not zero. Reported tokens/cost are not
independently measured billing. Model discovery never counts as generation success.

Live artifacts remain private/local; review/redact before sharing. The harness
never uploads live results. Mocks prove protocol/orchestration contracts, **not
real-model quality, factuality, translation completeness, or availability**.

Harness exit statuses: 0 for passing fixture conformance/all completed live cases;
1 for conformance failure or failed/unavailable/confirmation-blocked live cases;
2 for configuration or execution/storage errors. Underlying CLI exit statuses are
recorded independently.
