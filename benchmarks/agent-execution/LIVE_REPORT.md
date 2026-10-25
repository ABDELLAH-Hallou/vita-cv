# Real CV pilot: before and after

**Keep the existing default. The new path made fewer tool calls and produced more edits, but this small test did not show a speed improvement or establish better finished documents.**

Two public English CVs, two real employer job posts, two fresh repeats and both paths gave 16 main runs. Both paths requested `gpt-6.1-sol` with high reasoning, identical frozen CV/job files and job criteria, serial execution, and the same three-attempt ceiling. Which path ran first alternated. This is development data, not holdout evaluation.

| Main result | Existing path | Restricted path |
| --- | ---: | ---: |
| Runs | 8 | 8 |
| Analyze passed host checks | 5 | 6 |
| Complete CV proposals awaiting factual review | 3 | 6 |
| Body changed beyond whitespace, among those proposals | 0/3 | 6/6 |
| Adapt returned a stop message instead of a CV | 2 | 0 |
| CLI failed before returning an assessment | 3 | 2 |
| Accepted adapted CVs / finished workflows | 0 / 0 | 0 / 0 |
| Observed shell calls | 24 | 0 |

The five unavailable calls remain in the counts; their content quality is unmeasured. Their saved error categories do not identify the underlying provider/CLI cause. These are not confirmed rate-limit or model-quality failures.

Analyze succeeded in both paths for five matching pairs. **The new path was slower in four; the median paired increase was 21.0%.** The five changes were −25.8%, +9.0%, +21.0%, +46.1% and +21.6% (negative means faster). Successful Analyze median/p95 was 108.4/111.8 seconds for the existing path (n=5), and 106.8/150.3 seconds for the new path (n=6). The overall medians use different successful cases. The 21% result compares the same five cases. Times include host preparation and validation; no exact startup/inference split is available.

There is no time-to-accepted-CV or complete-workflow speed result. The machine report retains time until every terminal outcome, including fast failures; stopping sooner is not finishing a CV sooner. A nonempty Adapt response can pass the text contract while failing LaTeX validation. Approval stops are not accepted documents or provider crashes.

The existing agent sometimes tried to run `vita facts capture` itself and stopped when that host command failed. Restricted generation avoided this failure in the main sample. It produced actual body changes more often, but relevance and accuracy still require review. The body check compares literal LaTeX between document delimiters after removing whitespace, with comments retained.

All nine complete Adapt proposals stopped at the factual-change gate. That gate requests confirmation even for changed formatting it cannot verify. Some flags concern inlined LaTeX and copied copyright dates. These stops do not establish that the model invented facts. No candidate-fact change was automatically approved, and no held rewrite was used downstream.

## Separate original-CV controls

All eight fresh Extract calls succeeded. All 48 manual commands generated prompts without AI calls. There were 24 distinct fresh scoring assessments: eight first Analyze, eight repeated Analyze and eight fresh Review. All eight Analyze/Analyze pairs and eight Analyze/Review pairs kept the same score, source, job criteria and scoring prompt. All eight cached Reviews reused an existing assessment with no generation. These are unchanged-CV controls, never tailoring gains. Extract prompt hashes were identical across candidates for each job and execution path; manual Extract prompts also matched across paths. The four existing-path Cover attempts failed to return an accepted letter; the four new-path attempts produced complete letter proposals held for factual review. No letter was approved and no standalone PDF pair was delivered. Original CV/include/job files remained unchanged in all eight control projects.

These controls use fresh original CV copies, not blocked Adapt output. They cannot be counted as completing the main tailoring workflow. Host sleep interrupted some control commands, including a multi-hour gap and a timed-out/retried Review call. Their raw timings are retained locally and are not pooled into the main speed comparison.

## Checks and limits

All candidate source files in all 16 main copies remained unchanged. Job criterion identities, weights, revisions and denominators matched across CVs and paths; employment conditions were separate and unscored. The fixed job-only contract was prepared by the operator, not independently annotated by humans. Approved job criteria make Vita skip optional extraction in the main matrix; fresh Extract is a separate test.

The 11 saved Analyze assessments had 86 verified evidence-reference observations and 75 no-evidence/not-applicable observations. These are mechanical source checks, not correct semantic judgments. Both untouched original CVs compiled (one and two pages); no generated CV/letter PDF pair was delivered. Compilation would not establish accuracy or usable layout.

CLI usage was available for 10/13 existing-path and 12/14 restricted-path main invocations. Unknown usage, internal model-call counts, denied-call counts and monetary cost remain unknown. Reported input/cached/output/reasoning tokens are retained separately; fewer tools do not establish a cost saving. Resource use per accepted adapted output is undefined because none was accepted.

The sample contains two English CVs and two shared jobs, with dependent repeats. A reliable independent-sample interval is not available. Long-document and multilingual live performance, factual-error rates, harmful omissions, translation quality, correction time, blinded preferences and independent layout usability remain unmeasured. No independent qualified reviewers, annotations, adjudications or agreement scores were invented. ATS and hiring outcomes remain unvalidated.

## Reproduction

Frozen source: `0ff91ddfe64540f1d23a6b3217926fadf1abdfa0`; plan: `b8e4545d6858a0f6d105d6ca65b782736117806fc5d5b739003c59219eb87cbb`. Source version 2.12.0 was imported from the checkout; editable distribution metadata says 2.11.0. This tests the source commit, not a published wheel. Windows 11, Python 3.12.4, `codex-cli 0.163.0-alpha.10.2`, MiKTeX 24.4, Biber 2.20. The CLI received the exact selected model; it did not report a separate backend-model identifier.

Sources: [DevOps/SRE CV](https://github.com/edunham/resume) at `c660d10682888a3ab45562cbf77f47fcd6e2fe79`; [HPC/software CV](https://github.com/gajanan-choudhary/CV-Resume) at `4a80cba160ca6e326b71d684f5eaa1862bb806d0` (the author's existing two-page version); [BlueMatrix job](https://jobs.lever.co/BlueMatrix/1d1e0ec9-2c36-409b-aae2-30678a654e0f); [NVIDIA Warp job](https://jobs.nvidia.com/careers/job/893396960998). These are pinned public snapshots, not a claim about the individuals' current circumstances or job eligibility.

Exact input bundles, prompts, outputs, protected diagnostics, commands, controls and approvals remain local under `.vita/real-world-pilot/`. [The public machine report](live-results.json) contains only aggregate metrics and fingerprints. The public-input bundle and authorization procedure are documented in [BENCHMARKING.md](../../BENCHMARKING.md).

Three retained setup/default phases used 16 reserved attempts: an incorrect preferred/required setup label (3); both unapproved-job workflows failing after successful Extract (8); and a harness PATH mistake affecting baseline host commands (5). They are excluded from the corrected paired timing comparison and included in spending. Both the setup label and PATH were corrected before freezing the final matrix. The default unapproved path exposes a real approval-precondition/format-retry problem and remains reported as failed controls.

The approved ceiling was 384 CLI generation attempts. **84 were reserved**: 16 in retained setup/default phases, 27 in the primary matrix and 41 in independent controls, including the interrupted/timed-out Review attempt and its retry. Internal CLI model requests and monetary cost remain unknown. Reserved calls count even when backend acceptance is unknown; this CLI-attempt cap is not a bound on internal requests or dollars.

Of the 68 primary/standalone calls, 67 had retained argv artifacts confirming the selected model and high-reasoning flags. One Cover trace emitted an explicit diagnostics-save warning and has no argv artifact; its transport model and configured reasoning are recorded, but independent argv coverage is unavailable for that call. The cause of the capture failure is not established.

The next investigations are the host/generation instruction boundary (`vita/helpers/factual_changes.py:469`, `vita/commands/ai_step.py:148`), confirmation classification (`vita/helpers/factual_changes.py:244`), and the unapproved-criteria rejection (`vita/helpers/evaluation.py:183`). The experiment did not change these rules while running.

All CI and CodeQL checks passed on the frozen source. [The earlier fixture report](REPORT.md) remains separate; its timings are not real model timings. Keep the baseline default, or set `VITA_AGENT_EXECUTION=baseline`, until there is evidence to justify a different default.
