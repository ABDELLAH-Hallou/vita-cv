# Restricted agent execution and evaluation

This opt-in experiment has **not demonstrated a real model speed or accuracy
improvement**. Baseline remains the default. Authorized live timings and independent
semantic evaluation are required before recommending adoption.

Prepared plans are in `scripts/benchmark/plans/`; the implementation's offline
findings and measurement limits are recorded in
[the experiment report](benchmarks/agent-execution/REPORT.md).

## Baseline paths

| Path | Current behavior | Change |
| --- | --- | --- |
| Direct API | One HTTP adapter attempt; Vita owns shared transport/format retries, schemas, evidence, scoring and saving | No new provider or reduced reasoning |
| Codex CLI | `codex exec`, read-only sandbox, configured model/reasoning, schema and final-message files | Optional checked tool restrictions, ephemeral execution and JSONL observations |
| External-assistant prompts | Assistant executes host capture/generation/validation workflow | Adapt/Cover embed CV/includes, facts, skills and available prior artifacts, separated from host operations |
| Other adapters | OpenAI-compatible vendors, Gemini/Google and Anthropic HTTP API | No Claude CLI or Antigravity adapter exists or is claimed |

Time can include process startup, configuration/capability checks, context and
skill preparation, inference, tool activity, retries, validation, saving, human
approval waits and PDF building. Existing diagnostic spans and operation records
measure host phases. CLI process time includes startup, inference, internal retries
and tools together; it is **not an exact startup/inference decomposition**.

## Configuration and rollback

In `.vita/extensions.json`, retain your selected model and reasoning:

```json
{
  "llm_providers": {
    "codex": {
      "model": "YOUR_EXACT_MODEL_ID",
      "reasoning_effort": "high",
      "execution_mode": "restricted",
      "agent_timeout_seconds": 600,
      "max_input_bytes": 2000000
    }
  }
}
```

`VITA_AGENT_EXECUTION=restricted` in the process/project `.env` overrides the
provider setting for Codex. Diagnostics record process/project/extensions/default
origin. A global override leaves HTTP adapters as `direct_api`; an unsupported
provider's own restricted configuration is rejected.

Return to baseline with `VITA_AGENT_EXECUTION=baseline`, or remove the environment
override and set/remove `execution_mode` to select `baseline`. Uninstrumented
baseline retains the existing generation command, tool policy and final-message
handling. Recognized reasoning streams are suppressed from logs.
`agent_telemetry: true` optionally adds JSONL, reasoning-display suppression and
version observation to baseline, without restricting tools or changing reasoning.
The comparison uses this **instrumented baseline**, including its observation cost.

Restricted mode requires an explicit model and reasoning effort. It never lowers
reasoning, chooses a fallback provider/model, changes the shared host retry budget,
or silently falls back to baseline. Per-stage routing still applies. Assessment
provenance/reuse keys include execution settings, so changed configurations cannot
reuse incompatible assessments.

## Enforced controls and limitations

Checked against installed `codex-cli 0.163.0-alpha.10.2` local help/configuration
on 2026-10-25 and current official documentation:

- The existing read-only sandbox stays enabled. `features.shell_tool=false`
  removes command tools; read-only alone would not do this.
- `web_search="disabled"` disables native web search.
- `features.multi_agent=false` disables collaboration tools.
- `features.plugins=false` disables optional plugin tools.
- Configured MCP servers are enumerated and disabled for this invocation, then a
  second local listing verifies them disabled. Empty `mcp_servers={}` does **not**
  clear inherited servers. Type-preserving inert transport overrides satisfy
  bootstrap parsing without copying real URLs, commands or credentials into argv.
- `--ephemeral` and `history.persistence="none"` avoid normal Codex session/history
  persistence for this invocation. Vita's local diagnostics still apply; this is
  not a provider zero-retention guarantee.
- `--json` provides observations. `--output-last-message` remains the sole final
  answer source; intermediate messages/tool output cannot replace it.

Six local capability checks precede the first attempt; only the same frozen
operation/retry session reuses them. Unsupported controls, unrecognized server
identities/transports, managed-policy conflicts or unverifiable restrictions stop
with an explicit configuration failure. Observed shell/MCP/web/subagent activity
contradicting the restrictions rejects the output. Update the CLI/configuration
or explicitly choose baseline; do not change agent configuration during a run.

**Limitations:** other built-in tools, including planning/image tools, may remain.
Instructions ask not to use them; that is not universal tool denial. User/project
instructions, hooks and managed security policies remain in force. No ignore-config,
ignore-rules or approval/sandbox bypass is used. These are invocation controls,
not a security certification against all future versions, concurrent configuration
changes or malicious integrations. One CLI invocation may contain multiple model
requests. Headless/read-only/restricted is **not a raw model API**. Internal CLI
model retries are not claimed to equal Vita's shared attempt budget.

Official references: [configuration controls](https://learn.chatgpt.com/docs/config-file/config-reference)
and [non-interactive execution/JSONL](https://learn.chatgpt.com/docs/non-interactive-mode).

## Inputs and correctness

Restricted Adapt/Cover receive supported literal `\input{...}`/`\include{...}`
sources, captured source identities and approved knowledge spans, job context and
canonical criteria, available prior reports, skills, date/language instructions
and full-document constraints. Prior reports are **not candidate evidence**;
missing optional reports are explicitly unavailable. Missing/external sources,
unbraced/dynamic includes and include cycles stop before generation. Binary
graphics are not interpreted/OCRed into factual evidence; image-dependent facts
need an explicit verified text source.

Analyze/Review preserve their shared scoring judge and evidence contract without
injecting prior scores. Extraction/requirements remain JD-only. The byte guard
rejects oversized complete prompts instead of shortening history. It is a host
bound, not a tokenizer or a guarantee that an arbitrary model context fits.
Provider input/output-limit responses remain actionable failures; no output or
reasoning budget is silently reduced.

Existing schema, canonical-criteria, source/evidence, assessment reuse, LaTeX and
factual-change checks still apply. Unresolved/rejected proposals cannot overwrite
originals or reach downstream steps. **A blocked proposal can contain a factual
error**: inspect its full retained `*.facts.json` document. A stop is not an
accuracy result.

Manual prompts separate host recapture/validation/staging/saving from generation.
Host operations may use necessary tools. Runtime restrictions are not claimed
for arbitrary external assistants. Runtime recapture still guards stale embedded
snapshots.

## Observability

Existing journals and outcome attempt records include requested/effective settings
and origin, CLI version, exact requested model/reasoning, effective prompt hash,
source/schema provenance, capability/process durations, host phase times and retry
categories. JSONL observations allowlist turns, tool types, explicit denials and
available input/output/cached/reasoning tokens. Item IDs avoid double-counting
start/completion events.

Unreported internal model calls, token usage, costs and denials are **null**, not
zero. Completed turns are not model calls. Discovery/version checks are not
successful generation/access checks. An explicit model argument is not a reported
backend snapshot ID; that can remain unknown.

Raw instrumented JSONL/reasoning/tool payloads are not persisted. Final user-facing
output and allowlisted technical observations use existing diagnostic credential
redaction/retention. Usage is provider-reported, not an audited invoice.

## Reproducible development comparison

Preparation/reporting extend `scripts.benchmark`; execution and spending stay in
its existing runner/worker/ledger:

```console
python -m scripts.benchmark.execution_comparison plan --model fixture/custom-agent-v1 --reasoning high --repeats 2 --output fixture-plan.json
python -m scripts.benchmark --plan fixture-plan.json --output .vita/agent-fixtures
python -m scripts.benchmark.execution_comparison report .vita/agent-fixtures
```

Ten development scenarios cover short/long/multifile CVs, relevant/mismatched
roles, missing evidence, ambiguous dates/acronyms/currency, expired/in-progress
credentials, Spanish/French/Arabic, noisy JDs, malformed output and context limits.
Input snapshots are hashed/frozen before edits. Two fresh A/B repetitions make
40 cases. Unchanged Analyze-to-Analyze, Analyze-to-Review and cached reuse controls
remain separate; cache hits are not independent generations.

A is instrumented baseline; B restricts tools with the **same exact model,
reasoning and shared attempt budget**. Optional `--lower-reasoning low` adds C as
a separate contrast and must be lower. Full plans reject mismatched A/B settings.
Runs are serial in listed order. `--reverse` registers B/A order with a different
plan/hash requiring separate live authorization. Different models are never
treated as equivalent. No direct API reference is included without confirmed
access to a genuinely comparable model/configuration.

Fixture transports block network access. Positive software cases may use labelled
synthetic-only factual decisions. Missing-evidence and ambiguous-fact controls
stop for approval and preserve originals; the latter intentionally proposes an
unsupported TTR expansion for gate testing. **Live runs never auto-approve facts.**
Fixture PDF markers test handoff, not rendering. Use `--real-pdf` with installed
LaTeX tools for real compilation; Arabic requires Unicode engine/fonts. Failed or
unsupported builds are not passed layouts.

Reports show per-model/configuration/stage counts and denominators, first-attempt
contract validity, retries, terminal categories, validated-output and all-terminal
timings, workflow duration, available usage and unknowns. Approval stops stay in
reliability/terminal results but not accepted-output timings. Human waiting and
correction time remain unmeasured. Source-reference validity is separate from
semantic accuracy. Fixture reliability includes deliberate negative controls;
it is not real provider uptime.

Median/p95 include sample counts (nearest-rank p95). Paired speed changes condition
on both arms completing; read all-attempt terminal results too. Independent-family
bootstrap support preserves dependent repetitions. Current variants share one
synthetic candidate/job family: its interval is unestimable and remains null;
different variants/repeats are not invented independent families. Raw repeated-case
rates do not receive naive independent-binomial intervals. Small pilots and zero observed
errors do not establish equivalence. Semantic fidelity, harmful omissions,
unsupported additions, requirement judgments, translation, layout, blinded
preference and correction time need review. No fabricated composite accuracy or
CV match-score proxy is used.

## Live authorization and decision

Prepare a plan without executing it:

```console
python -m scripts.benchmark.execution_comparison plan --live --model YOUR_EXACT_MODEL_ID --reasoning high --repeats 2 --output live-plan.json
python -m scripts.benchmark --mode live --plan live-plan.json --plan-hash
```

The `.proposal.json` sidecar records hash, thresholds and request bound. Forty
cases have at most **960 host generation dispatches**, including retries if every
workflow/control finishes. Internal Codex model requests, tokens and billing have
no trustworthy pre-run bound here: the ledger caps CLI invocations, **not internal
billable calls or currency**. Use account/provider spending limits and explicitly
approve that limitation. Access, expected usage and cost are unverified.
Malformed output is injected only in fixtures; the live case observes natural
structured-output validity without forcing a provider failure.

Follow [BENCHMARKING.md](BENCHMARKING.md) exactly: explicit spending approval and a
separate plan-bound authorization artifact with billing acknowledgment, approved
`max_requests` and future timezone-aware expiry. Prepared plans are not
authorization. Resume only after real revision-bound human factual decisions;
keep waiting time separate. The ledger spans stages, failures, retries and resumes.

Proposed margins, **pending user/custodian decision before live comparison**:
20% minimum paired median speed improvement; zero allowed regression in each
semantic quality dimension; no critical factual errors; at least 95% completion;
100% build success for delivered documents. These are engineering proposals, not
approved tolerances or measured findings.

Use [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md), [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md)
and `scripts.evaluation`: independent holdout separate from development fixtures,
two independently assigned qualified human reviewers, adjudication and agreement
measurement. Packets must include frozen sources, outputs and stopped proposals.
No reviewers, qualifications, labels, adjudications or agreement results are
invented here. Model judging cannot replace required humans.

Until authorized live evidence and independent annotations exist, the decision
is **inconclusive: retain baseline and gather more evidence**. ATS/hiring claims
remain unvalidated.
