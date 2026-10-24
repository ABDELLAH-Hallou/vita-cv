# Independent evaluation protocol — version 1

This implements the infrastructure for [issue #44](https://github.com/ABDELLAH-Hallou/vita-cv/issues/44).
It is a **prospective validation program**, not completed validation. No holdout
has been acquired, no qualified human panel has been recruited or verified, no
human annotations/adjudications have been produced, and no agreement results are
claimed by this change. Synthetic unit tests are software tests, not human evidence.
ATS behavior, interview/hiring probability, hiring outcomes, population
representativeness, and hiring success remain **explicitly unvalidated**.

## 1. Scope and preregistration

Evaluate source fidelity, atomic requirement classification/satisfaction, harmful
omissions, unsupported additions, and execution/noncompletion rates. Evaluate
Extract, Analyze, Adapt, Review, and Cover separately. Preserve configuration,
product/prompt/schema revisions and source identities. Host CV match scores are
not the reference labels, semantic accuracy, ATS scores, or hiring probabilities.

The study custodian must approve and externally timestamp the sampling plan,
definitions, configurations, fixed sample size, exclusions, controls, analysis,
and stopping rule **before any holdout output is seen**. Record the private
preregistration reference in `governance.json`; `freeze` then records immutable
input/configuration hashes and an execution timestamp boundary. A local hash is
an audit aid, not proof of an external preregistration or truthful human identity.
Amendments require a new study directory/revision and a disclosed reason. Never
rewrite a registration, erase failed attempts, or choose a stopping point after
viewing desirable results. Protocol v1 has no validated pass threshold.

The machine-readable definitions are in `scripts/evaluation/protocol.json`.
Sampling quotas may be changed **before** freezing, with human approval. Changes
to labels/statistical methods need a new supported protocol version. The initial
draft is not silently treated as human-approved.

## 2. Sampling and private holdout

Preregister a quota sample across:

| Axis | Levels |
| --- | --- |
| Job domain | Software, quota-carrying sales, marketing, operations |
| Target role seniority | Junior, mid, senior |
| Native candidate format | LaTeX, Markdown, DOCX, PDF |

Default targets: one development primary pair and two holdout primary pairs per
cell: **48 development and 96 holdout primary pairs**. These are planned quotas,
not acquired cases, a representative population, or a power calculation.
At least eight holdout primary cases each must cover expired credentials,
ambiguous dates, missing evidence, and genuinely disqualifying conditions; tags
may overlap. Record per-cell counts and deficits. Sparse cells stay visible.

Use one primary CV/JD pair per candidate family and job-posting family within a
split. Near-duplicate CVs, versions of one person, translated copies, related
postings, and template variants must share custodian-assigned group IDs. Keep
candidate, job, and pair families disjoint across development and holdout.
The validator rejects exact content/group leakage and duplicated primary
families; custodians still need to audit semantic near-duplicates and exposure
across past studies. File hashes alone do not detect paraphrased leakage.

Accept only synthetic, appropriately consented, or licensed sources, with a
private rights/consent reference and verified contact redaction. Public visibility
alone is not the acquisition policy. Preserve official names/credentials needed
for factual evaluation while removing personal contact details and unnecessary
document metadata. Never upload the local real-person benchmark corpus to this
repository or CI. Do not rank real applicants or collect hiring outcomes here.

Retain original native files plus human-verified canonical UTF-8 text for
PDF/DOCX. Retain included LaTeX files and explicitly verified knowledge-base
content as separate source identities. Conversion errors and missing material
must be resolved or marked unjudgeable, not attributed to a model. Native-format
quotas do not establish visual/layout or multilingual fidelity (#46).

Development is for calibration, prompt tuning, fixtures, and debugging. Holdout
is sealed under a separate custodian; developers receive only development
packets. If holdout content/results inform tuning, mark that material exposed,
retain the original results, and acquire a fresh untouched holdout for the next
confirmatory evaluation. Never relabel development fixtures as a holdout.

## 3. Controls and execution

For every primary pair preregister:

- **Unchanged Analyze-to-Analyze**: identical captured CV/JD/criteria, same
  configuration/prompt/schema/date, fresh `vita analyze --auto --reassess`.
- **Unchanged Analyze-to-Review**: the same inputs and judge, fresh
  `vita review --auto --reassess`. Report separately from Analyze repeats.
- **Mismatched role**: identical candidate sources with a different-domain JD;
  run Analyze, Adapt, and Cover. A Python CV paired with a sales role is the
  development illustration. Transferable skills remain valid evidence; do not
  assume a true reference score of zero or invent missing qualifications.

Do not Adapt between unchanged controls. Hold canonical JD criteria fixed before
candidate assessment using the existing requirements approval contract. Record
the requirement revision, host assessment provenance and source snapshot. Cached
reuse is useful conformance evidence but **not an independent repeat**. The script
flags missing provenance, reused assessments, and changed source/configuration;
it never attributes unchanged-input score differences to tailoring.

Execute serially in registered case/configuration/task order. Use paired source
bytes and the same adjudication definitions across configurations. Model IDs,
reasoning, temperature (null means omitted/default), extraction setting, date,
product revision and prompt/schema fingerprints must be explicit. Record actual
returned snapshots, attempts, timings, usage when available, and failures.
Unknown usage is null, not zero. Do not silently substitute models/providers.

The offline evaluation tools make **no model calls**. Execute with the standalone
Vita CLI and existing [opt-in benchmark spending policy](BENCHMARKING.md), using
separate explicit authorization and provider limits. That harness's built-in
corpus remains development-only; it must not be described as a holdout runner.
For private holdout projects, retain equivalent CLI/journal/outcome records and
import the declared artifacts. Data binding is checked; externally supplied run
metadata remains a custodian attestation, not independent execution verification.

### Endpoints and factual confirmation

For Adapt/Cover, the content endpoint is the **candidate proposal**, including a
proposal stopped by the factual-change gate. Review the archived proposed source,
not only a subsequently approved/applied CV. This prevents unsafe proposals from
disappearing from fidelity measurements. An inspectable stopped proposal can be
annotated while its CLI execution remains failed. Never auto-approve factual
changes to make a benchmark finish. Record approval/rejection as separate human
workflow decisions; they do not replace independent content annotation.

Other stages use their validated report artifacts. Unavailable, malformed and
unusable reports have no semantic output; retain raw diagnostic files separately
and count the failures. Do not turn missing outputs into zero-quality labels.

## 4. Human panel, independence, and adjudication

Assign **two distinct qualified humans per case**, not two assistant sessions.
Each must have at least three relevant years of domain experience, or a
documented specialist qualification approved by the custodian, and competence
in the source language and native format. Use specialists for quota/attainment,
marketing measures, operations credentials, and technical terminology. Record
pseudonymous person identities, private qualification references, calibration,
conflicts and independence attestations. Software checks the declarations and
duplicate identities; recruitment and verification remain real human work.

Calibrate on development examples only, revise the guide there, then freeze it.
For holdout, reviewers work independently without consulting each other's labels
or seeing provider identity, model name, aggregate match scores as reference
truth, or sampling challenge tags. Use three passes:

1. Classify atomic requirements from the JD only, before candidate evidence is
   disclosed. Keep required/preferred/unclear/conditions distinct.
2. Match locked requirements against candidate sources, with machine predictions
   withheld. Lock those independent reference judgments.
3. Inspect blinded proposals/reports for factuality, additions and omissions.
   Record actual JD-pass/source-pass completion and output-access times.

The custodian controls access. Generated bundles reduce accidental disclosure;
they cannot enforce real-world blinding or establish honest timestamps. Reviewers
must verify the full source inventory, not only curator-selected excerpts. If an
atomic claim/requirement was omitted, request an inventory amendment before
finalizing; make a new hash-bound packet and retain earlier submissions.

Use a **distinct third qualified human adjudicator** for disagreements. Preserve
both original independent submissions and their hashes. The adjudicator inspects
sources, both rationales and exact evidence, records a reasoned final label and
actual completion time, or leaves `cannot_judge`. No silent majority vote,
assistant adjudication, or default agreement. Unresolved disputes stay pending.

See [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md) for labels and source-grounding rules.

## 5. Statistics and claim boundaries

Report per configuration, task, split, control, domain, seniority, native format
and role. Do not pool controls, stages, configurations or development/holdout into
one nominal semantic-accuracy rate.

| Measure | Numerator / denominator |
| --- | --- |
| Execution failure | Failed + unavailable observations / all attempted observations, including unavailable providers |
| Noncompletion | Everything except completed / all planned observations (not-run work shown separately) |
| Human coverage | Fully reviewed, adjudicated available outputs / available endpoint outputs |
| Unit error | Resolved eligible error labels / resolved eligible units, with pending/abstention counts |
| Case semantic error | Fully reviewed available cases with any error / fully reviewed eligible cases |
| Dimension case error | Fully reviewed cases with an error in that dimension / reviewed cases with eligible units in that dimension |

All planned observations stay visible; not-run work is not falsely counted as a
successful or failed provider attempt. An unattempted cell has a null execution
failure rate. Unavailable outputs stay in execution denominators; their content quality is
unmeasured. Stopped but inspectable proposals stay eligible for human fidelity
review. Pending labels, `cannot_judge`, incomplete inventories, and unresolved
adjudications cannot become fully reviewed case scores. Legitimately empty
dimensions require two independent inventory attestations and keep a null unit
rate. Distinct dimensions can refer to the same claim; never sum their rates into
a fabricated composite accuracy percentage. No criterion weighting is invented.

Compute raw **observed agreement and nominal Cohen's kappa** from original paired
human labels, before adjudication, separately by reviewer pair/dimension/domain
and seniority. Include `cannot_judge` as an agreement label and disclose it as an
abstention for semantic scoring. Report pair counts and confusion counts.
Unrated pairs are absent, not agreement; constant marginals make kappa undefined
and therefore null. Do not assign a universal "good enough" threshold or infer
validity from agreement alone. See the [scikit-learn definition](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cohen_kappa_score.html).

Provide **95% Wilson intervals** for primary case-level proportions within each
configuration/task slice. Controls and unit-level rates are descriptive because
units/repeats are dependent. Primary pairs must have distinct candidate/job
families; the intervals remain conditional on this quota sample and its assumed
independence, not a population-coverage guarantee. Zero events do not imply zero
uncertainty; a zero denominator produces null. No interval corrects selection
bias, ambiguous annotation, or a tiny cell. See [NIST's interval guidance](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).

Report limitations, sparse cells, abstentions, failures and human coverage beside
every content result. Claims about proprietary ATS systems or hiring/interview
outcomes need a **separate appropriately consented, preregistered study** with
its own outcome definitions, data and analysis. Passing this program cannot
validate those claims or certify security/fairness.

## 6. Reproducible local workflow

Run these maintainer tools from a source checkout or extracted source distribution
with Python 3.10+.

Use a new ignored private directory. No source or review data is uploaded:

```sh
python -m scripts.evaluation init .vita/evaluation/study-001
python -m scripts.evaluation status --study .vita/evaluation/study-001
```

The generated structure has `development/manifest.json`, a synthetic development
example with controls, **empty** `holdout/manifest.json`, private `sources/`,
`protocol.json`, `governance.json`, `configurations.json`, `results.json`,
`units.json`, `reviewers.json`, and `assignments.json`. Status explicitly reports
sampling and human work pending. It produces no gold labels or agreement values.
Private copies of this protocol and the annotation guide are also captured and
hash-pinned when freezing; distribute those method snapshots to the reviewers.

Populate approved sources and [contract fields](ANNOTATION_GUIDE.md#file-contracts).
The custodian records actual approval in governance, changes protocol status to
`approved_by_custodian`, and pins real configuration revisions. Then:

```sh
python -m scripts.evaluation freeze --study .vita/evaluation/study-001
```

This writes `registration.json` once. Source, protocol, governance or configuration
changes invalidate it. Failed/outstanding quotas remain disclosed; freezing a
development pilot does not mean a complete holdout exists.
Changing either captured method document invalidates the registration too.

After approved execution, collect output files under the study root, fill
`results.json` from actual CLI artifacts/provenance, and create an atomic
source-linked `units.json` inventory without reference labels. Supply verified
reviewers/assignments and prepare **one split at a time**:

```sh
python -m scripts.evaluation packet --study .vita/evaluation/study-001 --split holdout --output .vita/evaluation/study-001/packet-001.json
python -m scripts.evaluation template --study .vita/evaluation/study-001 --packet .vita/evaluation/study-001/packet-001.json --reviewer REVIEWER_ID --output .vita/evaluation/study-001/reviewer-ID.json
```

The template has null labels, false independence attestation, blank rationales,
and null timestamps. It creates separate `.job-pass.json`, `.source-pass.json` and
`.output-pass.json` bundles containing captured source/output text without
provider/configuration IDs. The custodian distributes these in order and gives
each reviewer the original redacted native sources for conversion verification.
Never hand annotators the manager packet containing machine predictions.
Structured routing metadata and host score fields are removed from output views;
view hashes and original hashes are distinct, and original citation spans retain
their original line numbers. Custodians must audit free text for residual identity
cues: automatic field removal cannot guarantee complete blinding.
Blinded bundles retain task, endpoint and the preregistered as-of date so reviewers
can apply the correct Cover omission policy and judge credential expiry without
seeing provider/configuration identity.

After both humans submit, create a blank adjudication form if needed:

```sh
python -m scripts.evaluation adjudication-template --study .vita/evaluation/study-001 --packet .vita/evaluation/study-001/packet-001.json --reviewer ADJUDICATOR_ID --reviews REVIEWER_A.json REVIEWER_B.json --output ADJUDICATION.json
python -m scripts.evaluation score --study .vita/evaluation/study-001 --packet .vita/evaluation/study-001/packet-001.json --reviews REVIEWER_A.json REVIEWER_B.json --adjudications ADJUDICATION.json --output .vita/evaluation/study-001/report-001
```

JSON/Markdown reports record pending work honestly even with no review files.
They include the scoring implementation's source fingerprint, Python version,
protocol version, registration/packet hashes and original submission hashes for
reproduction and longitudinal comparisons.
Add `--require-complete` for a nonzero gate while holdout sampling, execution,
independent human review, inventory checks or adjudication are incomplete. This
gate never validates ATS/hiring claims. Ordinary report generation exits 0,
incomplete strict validation exits 1, invalid/stale contracts exit 2. Files and
report directories cannot be overwritten; revisions get new names. Review and
adjudication files may be edited by their humans until submitted; changed
submissions invalidate adjudications bound to earlier hashes.

CI tests only temporary synthetic data, agreement arithmetic and failure modes.
The distribution includes this protocol and the scripts; it does not include a
real-person holdout, invented expert panel, or measured human findings.
