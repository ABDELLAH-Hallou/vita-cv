# Restricted agent execution: engineering evaluation

Decision: **inconclusive — retain baseline and gather more evidence**. No live model latency or semantic accuracy improvement has been demonstrated.

## What was tested

The frozen CI fixture run attempted all 40 development cases: 10 scenarios, two fresh repetitions, A/B using the same exact fixture model and high reasoning. A is the instrumented baseline; B uses restricted controls and complete generation inputs. C/lower reasoning, live providers and a direct API reference were not run. All variants share one synthetic candidate/job family, not independent holdout cases.

- **40/40 conformance checks passed**: 28 workflows completed, 8 deliberately stopped for factual confirmation, and 4 deliberately exceeded the host input-context guard. These raw dispositions remain in reliability/terminal counts; they are not real provider uptime.
- **8/8 stopped workflows preserved original CV bytes.** Retained ambiguity proposals contain the intentionally unsupported expansion from undefined TTR to Time to Resolution. A blocked proposal can still be wrong; no factual/semantic accuracy credit is awarded for the stop itself.
- Four malformed-output cases recovered in two attempts under the unchanged shared three-attempt budget.
- Unchanged controls: 28 fresh Analyze-to-Analyze, 28 fresh Analyze-to-Review, and 28 cached reuse controls. Cached results are not new generations.
- 252 mocked host transport dispatches, including failures, repairs and controls. Internal model calls, real token use and cost remain unmeasured; fixture usage/event streams are scripted.
- Mechanical evidence observations: 284 verified source references and 4 no-evidence/not-applicable observations, including repeated report copies. **This is not semantic accuracy.**
- A restricted workflow compiled actual CV and cover-letter PDFs locally; CI also passed actual baseline/restricted build handoffs. The 28 full-matrix fixture build markers demonstrate handoff only, not rendered layout or translation correctness.

## Measured timing findings

For the 14 complete paired repetitions, restricted fixture workflow/build time was **6.3% longer at the median**. Across all 20 attempted pairs, median terminal time was 4.9% longer. These are **software-fixture host timings**, excluding harness artifact copying, manual/control commands and human waits; they do not measure Codex startup, real inference, natural tool use or real model speed. No speed benefit is claimed.

[Per-stage median/p95, sample counts and validity](STAGE_METRICS.md) and [machine results](offline-results.json) retain the counts and timing scopes. Validated-output timing uses successful outer host step spans, including preparation, validation and synchronous document gates; nonempty model text is not substituted for a validated document. Unknown/unfinished timing remains null. Existing public diagnostic spans supply nested host phases; those durations overlap and are not summed as independent time. Resume records deduplicate generation IDs.

Only one independent source family is present, so a meaningful independent-family uncertainty interval is not estimable. Repeated variants do not create independent sample size. Successful-output pairing conditions on both arms completing; all-attempt terminal outcomes remain separately visible.

## Provenance and development history

Frozen fixture plan: `1b9c5c4e469fad9d960c259a02330170c65ee4da28ccf02658ed646b79a4061c`. Feature head: `dc4a9ece655d7be63d754d71df25266f01276bef`; CI checkout: `db2e31302347da5a40d181a6bd736baddb54ec85`. Execution source fingerprints, analysis source fingerprint and detailed report hash are retained in the machine results. Later timeout/privacy and reporting hardening is tested separately without claiming a new model-speed measurement.

[Successful run and complete raw artifacts](https://github.com/ABDELLAH-Hallou/vita-cv/actions/runs/40146308700), artifact `agent-execution-comparison` (14-day CI retention). Local copy: `.vita/agent-ci-complete`. Reproduce with the frozen fixture plan through `python -m scripts.benchmark`, then `python -m scripts.benchmark.execution_comparison report RUN_DIRECTORY`.

An earlier full development run found four Arabic cache-control failures: a fixture's hard-coded source span became stale when the preamble changed. The host marked it unverified and withheld reuse. The fixture now derives the correct captured line; regression coverage and the corrected full run pass. The failed run remains recorded ([run 40145588446](https://github.com/ABDELLAH-Hallou/vita-cv/actions/runs/40145588446)). An incomplete Windows dry run was stopped for execution overhead and retained locally; its partial timings were not used for findings.

## What remains unmeasured

Real latency/reliability, factual-error documents, unsupported additions/contradictions, harmful omissions, semantic requirement judgments, translation fidelity, independently reviewed usability/layout, human correction time and blinded preferences. No independent reviewers, qualifications, annotations, adjudications or agreement scores have been invented. Source-reference checks and compilation do not establish semantic correctness. ATS and hiring outcomes remain unvalidated.

## Prepared live plan and pending decisions

The proposed A/B plan uses the existing configured identifiers **gpt-6.1-sol / high** in both arms. Forty cases, serial registered order, two repetitions; optional C and reversed order require separate plans. Plan hash: `f591b4bb5f97e89b12f1b8f370ac397acbb7c4d8f1e269a445bdb6856b528596`.

At most **960 host generation dispatches including retries** if all workflows/controls finish. Internal CLI model requests, tokens and billing are not bounded or reliably estimated by that invocation cap. Model access is unverified; the local CLI capability probe is not a generation check. No live spending authorization artifact is created and no live generations were executed.

Proposed margins require a user/custodian decision before live comparison: 20% median paired time reduction; no regression in each semantic dimension; no critical factual errors; at least 95% supported-input primary completion; 100% delivered build success and independently reviewed usability; no critical layout defects, increase in correction time or decline in blinded relevance/clarity/usefulness. Deliberate invalid-input controls must stop safely and remain separately reported. The practical rating rubric requires an approved protocol supplement. These are targets, not accepted losses or measured findings.

Use [the exact authorization procedure](../../BENCHMARKING.md), [configuration/rollback](../../AGENT_EXECUTION.md), and the independent evaluation/annotation protocol with two independently assigned qualified human reviewers, adjudication and agreement. Until that evidence exists, keep `VITA_AGENT_EXECUTION=baseline` (or the default baseline setting).
