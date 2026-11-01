# Source-linked factual changes

Adapt and Cover use the host-generated `factual-changes/1` contract. An AI response
is a **proposal**, not an authorization to change candidate facts. Existing CVs,
included files, knowledge approvals, job hashes, and assessment evidence contracts
retain their existing meaning. No provider is called by `vita facts`.

## Safety boundary

The host does not know whether `Sen` means September, what `TTR` stands for, or
which currency `1M` uses. It cannot establish that OOP experience proves Object
Oriented Design, that an expired/in-progress credential is current, or that an
official name's translation is accurate. Overlapping `Present` dates are preserved.
JD terminology is never candidate evidence. Keep official names in the original
language; a translated gloss may accompany them, subject to confirmation.

The default conservative `auto` policy automatically applies an identical source
document (allowing outer whitespace changes). Other edits require confirmation,
including plausible rewordings, ordinary translations, omissions, and a newly
written cover letter. It intentionally favors false positives over silently
accepting unsupported specificity. It does **not** claim to determine semantic
equivalence, real-world truth, or a hallucination rate. Formatting inside TeX can
change meaning, so even internal whitespace edits are reviewed. Model assertions
such as “approved” or “wording only” never authorize application.

## Automatic execution and decisions

`vita adapt --auto` and `vita cover --auto` capture sources before generation,
then save a recoverable proposal. Unresolved edits return a nonzero exit code;
`vita run --auto` stops before later stages. The existing document stays intact.

```sh
vita facts show adapt
vita facts show adapt --json
# Review every item, its original text, proposed text, and source references.
vita facts approve adapt fc-<full-revision-hash>
# Or preserve the original and reject the entire proposal:
vita facts reject adapt fc-<full-revision-hash>
```

Approval is an explicit human assertion about **all** edits in that exact revision.
This human command must not be invoked by an assistant claiming review that did
not occur. The separate, explicitly selected [`unattended` policy](UNATTENDED_APPROVAL.md)
authorizes host approval without human review and records `unattended_run_policy`
provenance. It can apply inaccurate wording; unverified changes remain unverified.
Rejected revisions cannot be
approved; regenerate a new proposal instead. Approval requires unchanged CV,
included files, verified knowledge/approval, job content, configured target, and
previous target content. A failed document write after approval leaves
`application_status=not_applied`; repeat the exact approval to retry the write.

Review, Cover, and Build reject pending Adapt proposals. Cover builds also reject
pending Cover proposals. Rejected proposals permit use of the preserved original;
copying a rejected/unresolved proposal into a target cannot be laundered by
recapturing it. Restore the original sources before continuing. These are local
workflow integrity checks, not a security boundary against someone deliberately
editing/deleting the contract store.

## Generated-prompt execution

Generated prompts require the same host gate. At execution time (particularly
after an earlier pipeline stage), capture first, generate to a separate file,
then submit that file:

```sh
vita facts capture cover
# Assistant writes proposed-letter.tex, preserving cover-letter.tex.
vita facts check cover --proposal proposed-letter.tex
vita facts show cover --json
```

A stale capture cannot be used after overwriting the original. Stop on a failed
check; do not execute downstream tasks or call `approve` automatically. External
assistants must obey these instructions; Vita cannot intercept arbitrary writes
performed outside its CLI. Host checks do enforce the boundary when called.

## Contract for consumers

Active business artifacts are `.vita/results/{adapt,cover}.facts.json` and the
corresponding `.facts.md`. Revisions are retained under
`.vita/factual-changes/<step>/fc-<hash>.json`; manual captures use
`.vita/factual-changes/<step>.capture.json`. These artifacts include CV content
and must be treated as private candidate data, not diagnostic exports.
The strict JSON Schema is exported as
`vita.helpers.factual_changes.FACTUAL_CHANGE_SCHEMA`; loading also reconstructs
the host diff and checks snapshot/content/revision integrity.

| Field | Meaning |
|---|---|
| `contract_version` | `factual-changes/1` |
| `revision` | SHA-256 identity of immutable context, proposal, facts, and changes |
| `candidate_sources` | Existing v1 snapshot: main CV, supported includes, explicitly verified knowledge spans, content hashes and source IDs |
| `source_facts` | Stable `fact-` IDs referencing exact captured lines via `source_id`, 1-based inclusive spans, and quotations; these are source text units, not an ontology or truth assertions |
| `job_sha256`, `target_before` | Staleness guards; the original target is recoverable |
| `document`, `document_sha256` | Complete proposed target and its identity |
| `changes` | Host diff operations with stable IDs, original/proposed text, source fact IDs, output spans, kind, reason and verification |
| `status` | `ready`, `confirmation_required`, `applied`, `approved`, or `rejected` |
| `application_status` | `not_applied` or `applied`, separate from the approval decision |

Change `kind=wording` identifies whitespace edits; `semantic_or_factual` means
meaning is unverified, not that the edit has been proven false. `verification`
is `host_verified` only for outer whitespace, otherwise `confirmation_required`.
An insertion may have no source fact IDs: that is explicitly unsupported, never
implicitly verified. Deletions have `output_span=null`; other spans are 1-based
inclusive proposal lines. References establish text presence only. Proper-name
changes without obvious dates/acronyms/metrics use the generic semantic reason.
Reason codes are advisory classifications; **all** unverified edits are blocked,
so an unknown acronym or a different language cannot evade the gate.
After approval/rejection, each change retains its original host `verification`
finding. The top-level `status` records the explicit decision for every item;
human approval does not turn an unverified interpretation into host-proven truth.

Existing Markdown reports remain readable. A legacy report without this contract
has **not-recorded** factual verification; its absence is not proof of verified
preservation. The new gate applies to new Adapt/Cover executions. It does not
retroactively certify older documents or change assessment scoring.
