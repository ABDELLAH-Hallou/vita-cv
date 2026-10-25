# Restricted agent execution experiment

Status: implementation and focused offline contracts verified; full paired fixture run pending.

- Current decision: **inconclusive; retain baseline and gather more evidence**.
- Live generations: **not run; no spending authorization supplied**.
- Human source/semantic/translation review, correction time, preferences and agreement: **unmeasured/pending**.
- Local capability proof: `cli-capability-proof.json`. These are local checks, not a generation/access test.
- Existing contract regression subset: 223 tests passed. Final agent/benchmark subset: 61 passed.
- One complete restricted standalone fixture workflow passed. Negative controls preserved original CVs and retained confirmation-required proposals; malformed recovery passed.
- Full 40-case paired fixture findings will be recorded after the frozen run completes. Fixture timings are not real model latency or semantic quality.

The proposed live plan uses the existing local CLI configuration identifiers, `gpt-6.1-sol` with `high` reasoning, identically for A/B. It contains 10 development scenarios, two repetitions, 40 cases and at most 960 host generation dispatches including retries. Model access, internal CLI model-call counts, tokens and cost are unverified. CLI invocation caps do not cap internal requests or billing.

Live plan SHA-256: `f591b4bb5f97e89b12f1b8f370ac397acbb7c4d8f1e269a445bdb6856b528596`.

No authorization artifact is created. Proposed speed/quality margins require a user/custodian decision before live comparison. See [execution configuration and protocol](../../AGENT_EXECUTION.md), the prepared plans in `scripts/benchmark/plans`, and the existing independent evaluation protocol. All scenario variants share one synthetic family; they do not supply independent-family uncertainty evidence.
