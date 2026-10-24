# Annotation guide — vita-independent-evaluation/1

**Human work remains pending.** Examples describe decision rules; they are not
annotations or observed evaluation results. Two independently assigned, qualified
humans must produce the labels. An assistant may help with file formatting but
must not impersonate a reviewer, invent qualification attestations, fill gold
labels, adjudicate, or report fabricated agreement.

## Before reviewing

Read the [protocol](EVALUATION_PROTOCOL.md), qualify/calibrate on development data,
declare conflicts, and receive only your JD-only `.job-pass.json` bundle first.
Classify requirements before candidate evidence is disclosed. Then receive the
blinded `.source-pass.json` bundle to judge candidate coverage. Verify
canonical text against redacted native documents, including included files and
verified knowledge-base sources. Record actual JD/source-pass completion times before
opening the output-pass bundle. Do not consult other reviewers. Do not infer
reference truth from a host match score, previous evaluation, or provider name.

Check the complete inventory. Split compound requirements into source-linked
atomic concepts; merge duplicate references to the same capability. Preserve
ambiguity and conditions. Units have stable concept IDs within each output and
dimension; duplicated concepts cannot inflate that dimension's denominator.
If a unit or source is missing, ask the custodian for a new packet revision.
Never silently amend a submitted packet or force a label to fit a broken inventory.

## What counts as evidence

Use only captured, hash-bound candidate/JD sources and supported included files
or explicitly verified knowledge-base content. Cite `asset:ID`, one-based line
start/end and an exact quotation. A substring within that span is allowed;
out-of-bounds spans, stale source hashes and invented quotations are rejected.
Output references use `document: "output"`. For each label, list all captured
eligible text asset IDs in `checked_sources` (JD-only for Extract); checking only a favorable excerpt cannot
support an absence claim.

`evidence_kind` is `direct`, `inference`, or `none`. A source file's presence,
matching keyword, job title, degree, or adjacent skill is not proof of full
criterion satisfaction. `matched` requires sufficient direct candidate evidence
and a candidate-source citation; quoting the JD alone cannot establish it.
Semantic sufficiency is the human's responsibility; a valid quotation does not
make a judgment correct automatically.

For absent evidence, use `none`, record the sources checked and explain the
limit. "Not documented" does not mean the candidate lacks the skill. An explicit
contradiction differs from missing evidence. Inference must remain qualified and
cannot supply unsupported dates, units, employers, credentials or achievements.

## Label definitions

| Dimension | Labels / decision rule |
| --- | --- |
| `fidelity` | `supported`: factual meaning grounded in sources; `ambiguity_preserved`: source uncertainty retained; `contradicted`: conflicts with source; `unsupported_specificity`: adds unsupported precision/meaning; `cannot_judge`: sources/conversion/context insufficient |
| `requirement_classification` | `required`: explicit mandatory condition/capability wording; `preferred`: explicit advantage/nice-to-have; `unclear`: modality genuinely ambiguous/conflicting; `employment_condition`: eligibility/location/schedule/work-authorization condition kept separate; `not_requirement`: navigation, application form, corporate footer or unrelated text; `cannot_judge` |
| `requirement_satisfaction` | `matched`: full direct documented coverage of the atomic capability; `partial`: some direct coverage or limited, explicitly qualified inference; `missing`: no supporting evidence in captured sources; `not_assessable`: criterion not a candidate capability or cannot be meaningfully scored against this CV; `cannot_judge`: ambiguous or inadequate material prevents a reference decision |
| `omission` | `retained`: relevant source meaning remains, including faithful paraphrase; `justified`: omission allowed by the frozen task/relevance rules; `harmful`: removed or weakened material needed for truthful understanding or declared requirements; `cannot_judge` |
| `addition` | `supported`: output claim grounded in captured material; `unsupported`: introduces an employer, skill, scope, credential, result or eligibility claim without support; `cannot_judge` |

Requirement labels are reference judgments **made before seeing machine
predictions**. Scripts derive predictions from hash-bound output JSON pointers;
curators do not type a desired prediction into an annotation. Requirement
classification describes capability modality or routing to a separate employment
condition/non-requirement category. It does not erase a condition's own required
modality in the canonical contract. Classification and satisfaction have separate confusion counts. Employment
conditions must never be added as weighted capabilities. Review explicit claims
about eligibility/conditions as source-fidelity units and document their relevance;
missing eligibility evidence alone is not a genuine disqualification.

For fidelity, `supported`, `ambiguity_preserved` are eligible non-errors;
`contradicted`, `unsupported_specificity` are errors. For omissions, only `harmful`
is an error. For additions, only `unsupported` is an error. Requirement errors are
machine/reference label mismatches. `cannot_judge` is an agreement category but
an abstention for accuracy denominators. Do not use it merely to avoid a difficult
decision; give a reason. Separate metrics are not an invented composite score.

## Boundary cases

- **Expired/in-progress credentials:** preserve status and dates. Historical
  certification is not a current active credential; ongoing study is not an
  awarded degree. Judge coverage as of the preregistered date.
- **Ambiguous dates:** preserve "Sen 2017" or mark uncertainty; do not silently
  choose September or infer an exact duration. Overlapping roles do not prove
  uninterrupted full-time experience.
- **Acronyms and terminology:** undefined TTR stays undefined unless a captured
  source resolves it. OOP does not automatically establish Object Oriented Design.
- **Metrics:** preserve a documented 40% cost reduction and its scope. Unspecified
  currency is not USD/EUR by assumption. Percentage points are not percentages;
  team impact is not automatically individual ownership.
- **Proper names and translations:** preserve official employers, institutions,
  degrees and citation identities unless an authoritative source supports a
  translated official name. Fluent translation can still add false specificity.
- **Genuine disqualifying conditions:** require an explicit JD condition and
  explicit contradictory candidate evidence; distinguish these from unknown work
  authorization, missing availability, or an absent credential mention.
- **Mismatched roles:** legitimate transferable Python/data/reporting skills can
  match parts of sales/marketing/operations work. They do not establish quota
  ownership, closed-won revenue, campaign accountability or operational licenses.
- **Omissions:** Adapt should preserve source scope, qualifications, limitations
  and relevant requirements. Cover is selective, not a complete CV transcript:
  omitting an irrelevant publication can be justified, but concealing expiry
  while claiming current certification is harmful. Record this task distinction.
- **Fictional employer:** a generated employer with no captured support is an
  unsupported addition, even if a real employer elsewhere in the CV is cited.
- **Stopped proposals:** label the archived Adapt/Cover proposal even if host
  safeguards refused to apply it. Record the execution failure separately;
  host rejection does not erase a model's unsupported claim.

## Inventory, independence, and disagreement

For every available output/dimension, explicitly attest `complete` after checking
all eligible atomic units. `empty` is valid only when there are no eligible units,
with a rationale. Do not manufacture a no-error unit to force a zero rate. Until
both independent inventory checks and all required labels are resolved, the case
is unmeasured. Missing/unavailable outputs receive no content labels.

Each label needs a rationale, evidence kind, verifiable references where
applicable, and complete source-check IDs. Supported/contradictory/retained claims
need input citations. An unsupported claim may have no corroborating input quote;
cite its output span and explain which sources were checked. Exact source/output
anchors in the unit inventory remain available to adjudication.

Submit independently. The distinct qualified adjudicator receives both immutable
submissions, resolves only genuine disagreements, cites evidence and records
actual completion time. A blank adjudication remains pending. Keep `cannot_judge`
if uncertainty cannot honestly be resolved. Original labels still determine
agreement; adjudicated labels determine semantic error counts. Do not edit
independent labels to improve agreement after seeing the other reviewer.

## File contracts

All JSON contracts use `schema_version: 1`. Paths for captured files are relative
to the study root (artifacts) or split root (source assets). Source files are
immutable once frozen. SHA-256 means actual file-byte hash; JSON packet and
registration hashes use sorted canonical UTF-8 JSON. Dates/times are actual
timezone-aware ISO timestamps. Do not put credentials or contact details in files.

### Dataset manifest

Each split's `manifest.json` has `cases: []`. Each case has:

- `id`, `split`, `domain`, `seniority`, `native_format`, `language`, `role`;
- `candidate_group`, `job_group`, `family_id` for leakage/independence controls;
- `control`: `primary`, `unchanged_analyze`, `unchanged_review`, `mismatched_role`;
  `paired_case_id`: null for primary, otherwise the primary ID in the same split;
- `origin`: `synthetic`, `consented`, or `licensed`; `rights_approved`,
  `rights_reference`, `contact_redaction_verified`; sampling `challenges: []`;
- `tasks`: all five ordered tasks for primary; Analyze/Review respectively for
  unchanged controls; at least Analyze, Adapt, Cover for mismatched-role controls;
- `assets`: objects with `id`, `role` (`cv`, `job`, `included`, `knowledge`,
  `native`), `path`, `sha256`, `is_text`. Exactly one canonical CV and JD text
  asset are required. Native PDF/DOCX files accompany the canonical CV text;
  the latter needs `derived_from: NATIVE_ID`, `conversion_verified: true`.
  Knowledge assets need `verified: true`, `verification_reference`.

Use the generated development manifest as an **unannotated structural example**.
Its rights flags describe repository-owned fictional inputs, not a real human review.

### Configurations and governance

`configurations.json` contains `configurations: []`. Each configuration has exactly
`id`, `provider`, `model`, `product_revision` (Git SHA or SHA-256 of the product
source snapshot), `prompt_revision` and `schema_revision` (SHA-256 fingerprints),
`extraction_enabled` (boolean), `reasoning_effort` (string/null), `temperature`
(number/null), `as_of_date` (ISO date). Pin actual values, not placeholders or
guesses; keep returned snapshot/usage information in execution metadata.

`governance.json` has `custodian_id`, `protocol_approved_at`, private
`registration_reference`, `sampling_plan_approved`, `predeclared_analysis_approved`,
and `holdout_tuning_forbidden`. Approvals start false/null. Only the human
custodian records actual approval; also set protocol status `approved_by_custodian`.

### Observations and annotation units

`registration.json` lists every planned observation ID, case/configuration/task,
and endpoint target. `results.json` has `observations: []`, with each supplied row:

- `id` matching the registration; optional repeated identity fields must match;
- `status`: `completed`, `failed`, `unavailable`, `not_run`;
- `started_at`, `finished_at`, actual `attempts`, `exit_status` (null for timeout),
  `usage` (available usage object/null), `failure_category` (null on success);
- `provenance`: the registered configuration fields except `id`, copied from
  actual run records; retain returned snapshot, route, source/criteria hashes,
  reasoning, output mode and detailed attempts as additional metadata;
- `input_assets`: `{ASSET_ID: SHA256}` binding to the frozen reference sources.
  These define annotation truth; retain actual stage-input snapshots separately
  when adaptation changes the runtime CV. A sidecar is not proof that a provider
  consumed the right inputs; compare captured runtime provenance too;
- `artifact`: `{path, sha256}` for a usable endpoint, null for unavailable/not-run
  outputs. Failed Adapt/Cover may retain an inspectable candidate proposal;
  unusable failed structured reports have null artifacts. Successful rows require
  exit 0 and an artifact. Omitted observations become `not_run`, not successes.

Execution must start after registration. Existing pre-registration benchmark
outputs cannot be relabeled as a prospective holdout. Retain originals and new
measurements as distinct studies. Copy **actual** artifacts and host provenance;
never fill inferred usage, a guessed model snapshot, or a desired score.

`units.json` has `units: []`. Every atomic unit has `id`, `observation_id`,
`dimension`, `concept_id`, a neutral `question`, `source_refs: []`, `output_ref`
(object/null), `prediction_pointer` and `prediction_mode` (both null except for
requirement dimensions). A reference is:

```json
{"document": "asset:cv", "line_start": 4, "line_end": 4, "quote": "EXACT CAPTURED TEXT"}
```

Fidelity/addition units need exact output anchors. Requirements/omissions need
source anchors; requirement units must anchor the JD. Requirement predictions use
an output JSON pointer with mode `value` (e.g. `/metrics/criteria/0/status`), or
mode `requirement_bucket` for an extracted `/jobs/0/requirements/must_have/0`
or `nice_to_have` entry. The script derives `required`/`preferred` from that
container. For canonical criterion objects use mode `requirement_handling` with
the criterion object pointer: an explicit condition category/kind or the
`employment_conditions` container maps to `employment_condition`; other criteria
use their explicit required/preferred/unclear classification. This avoids
mistaking a required employment condition for a weighted capability. Reuse the approved JD concept IDs, assess each atomic capability once,
and retain conditions separately. Inventories/anchors are not human gold labels.

### Humans, assignments and submissions

`reviewers.json` has `reviewers: []`. Each entry contains `id`, distinct private
`person_key`, `kind: "human"`, `identity_verified_by_custodian`, `independent`,
`conflict_of_interest`, `calibration_completed`, private `qualification_reference`,
`relevant_years`, `specialist_qualification_approved`, `domains`, `languages`,
`native_formats`. Do not mark these true without the underlying human work.

`assignments.json` has `assignments: []`; entries contain `case_id`, exactly two
distinct `reviewer_ids`, and a different qualified `adjudicator_id` (null while
recruitment is pending). Packets freeze this roster/assignment snapshot. Complete
it before distributing forms; changes require a new packet.

Generated reviewer files have `packet_sha256`, `reviewer_id`, `independent`, actual
`job_pass_completed_at`/`source_pass_completed_at`/`outputs_opened_at`, `inventory` entries with
`observation_id`, `dimension`, `status`, `rationale`, and `annotations` entries
with `unit_id`, `label`, `rationale`, `evidence_kind`, `refs`, `checked_sources`.
Null labels/statuses are pending, not agreement or accuracy observations.

Generated adjudications have `packet_sha256`, `adjudicator_id`, the original
`review_sha256` mapping, actual `completed_at`,
`reviewed_original_submissions`, and `decisions` using the same annotation fields.
Only actual disagreements may receive decisions; null decisions stay pending.

The tools reject stale hashes, escaping paths, wrong split/observation identities,
duplicate concepts, unverified sources/people declarations, invalid citations,
changed configurations and mismatched adjudication provenance. They cannot prove
human honesty, domain expertise, legal rights, blinding, semantic completeness,
or representativeness. Those remain explicitly assigned human responsibilities.
