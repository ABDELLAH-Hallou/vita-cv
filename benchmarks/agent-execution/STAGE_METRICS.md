# Agent execution comparison

Decision: **inconclusive — retain baseline; gather more evidence**.

Mode: fixture; development only. Planned 40, attempted 40, not run 0.

Fixture timings measure software mechanics, not real model latency, accuracy, OCR, translation or hiring outcomes.

Validated timing means existing host gates, not independent semantic correctness. Positive fixtures use explicitly synthetic approvals; human waiting is unmeasured.

| Configuration / stage | Fresh operations | First-attempt contract validity | Validated n | Median validated seconds | p95 |
| --- | ---: | --- | ---: | ---: | ---: |
| fixture/custom-agent-v1 / high / baseline / adapt | 18 | 18/18 | 14 | 2.310 | 2.765 |
| fixture/custom-agent-v1 / high / baseline / analyze | 18 | 18/18 | 18 | 0.887 | 1.363 |
| fixture/custom-agent-v1 / high / baseline / cover | 14 | 14/14 | 14 | 3.695 | 4.552 |
| fixture/custom-agent-v1 / high / baseline / extract | 18 | 16/18 | 18 | 0.596 | 1.752 |
| fixture/custom-agent-v1 / high / baseline / review | 14 | 14/14 | 14 | 1.707 | 2.820 |
| fixture/custom-agent-v1 / high / restricted / adapt | 18 | 18/18 | 14 | 2.252 | 3.637 |
| fixture/custom-agent-v1 / high / restricted / analyze | 18 | 18/18 | 18 | 0.963 | 1.441 |
| fixture/custom-agent-v1 / high / restricted / cover | 14 | 14/14 | 14 | 4.344 | 5.333 |
| fixture/custom-agent-v1 / high / restricted / extract | 18 | 16/18 | 18 | 0.585 | 1.252 |
| fixture/custom-agent-v1 / high / restricted / review | 14 | 14/14 | 14 | 1.770 | 3.010 |

JSON contains terminal outcomes, paired timing counts, retries, effective settings, usage where observable, and all retained proposals including stopped Adapt/Cover output. Variants share one synthetic source family; independent-family uncertainty intervals are not estimable.

Semantic accuracy, harmful omissions, unsupported additions, translation fidelity, human correction time and blinded preference are unmeasured. Source-reference validity and successful compilation are separate technical checks, not semantic correctness.

Proposed thresholds require a user decision before live comparisons. CLI invocations are capped by the existing authorization ledger; internal model requests and cost are not bounded by that invocation cap. Unknown telemetry is null, never zero.
