# Multilingual and long-document validation — version 1

This is the reproducible **synthetic development conformance infrastructure** for
[issue #46](https://github.com/ABDELLAH-Hallou/vita-cv/issues/46). It is not a
completed linguistic evaluation. No independent Spanish, French, English or Arabic
review, semantic-equivalence finding, or RTL reading-order judgment is claimed.
The previously acquired real Spanish CV is not imported or described as tested.
ATS behavior and hiring outcomes remain **unvalidated**.

## Fixture provenance and coverage

`scripts/multilingual/locales.json` contains repository-authored synthetic drafts
in English, Spanish, French and Arabic. They are deliberately **not independent
reference translations**. Fictional names/employers and `example.invalid` URLs
are test material; no real-person source, contact information, acquired CV or
private holdout is packaged. These development fixtures must never be relabeled
as the independent [evaluation holdout](EVALUATION_PROTOCOL.md).

`fixtures.materialize()` deterministically creates UTF-8 LaTeX projects and a
versioned source/unit manifest. Each includes:

- Profile, experience, education, publications/articles, skills, awards,
  volunteering, a custom section, headings and nested macro arguments.
- Mixed-script personal names, `José Núñez`, official campaign `Lumière 2030`,
  `Certificado Delta`, OOP, undefined TTR, ambiguous `Sen 2017`, URLs and keys.
- A 40% cost reduction, 250 ms latency, and 125000 with **unspecified currency**.
  Team ownership, an expired qualification and an in-progress/unawarded degree
  remain explicit in every draft. Fluent wording cannot establish these facts.
- One-, three- and eight-page source projects. The latter two use recursive,
  literal `\input` files. Eight pages contain 43 historical entries; the last
  pages are meaningful history, not blank page-count padding.

All 16 source/target combinations across three lengths create **48 cases**,
including 12 same-language identity controls. Page counts are controlled fixture
expectations, not a claim that arbitrary native templates will fit the same text.
Each output is a deterministic draft transport, **not an AI model's translation**.
The runner exercises manual prompt generation and automatic Adapt, complete source
capture, proposal staging and normal factual confirmation. It never approves an
edit on behalf of a human. It checks that held changes leave sources unchanged.

## Run it

From a source checkout or extracted source distribution, with Python 3.10+:

```console
python -m scripts.multilingual --output .vita/multilingual/run-001
python -m scripts.multilingual --case fr-ar-8 --output .vita/multilingual/fr-ar-001
python -m scripts.multilingual --real-pdf --output .vita/multilingual/pdf-001
```

These commands make **no provider requests** and incur no model spending. They
refuse to overwrite an existing output directory. Exit 0 means the selected
mechanical conformance checks passed; 1 means a conformance/render check failed
or requested rendering was unavailable; 2 means invalid inputs or execution setup.
Exit 0 never means that translation, naturalness or RTL reading order is validated.

Outputs retain projects, manifests, generated prompts, held proposals, normal
project diagnostics, `report.json` and readable `report.md`. Reports record
fixture/scorer hashes, product/Python versions, routes, attempts and timings.
The mock route is not evidence of provider access, quality, usage or reliability.

To check a separately collected synthetic proposal against its original fixture:

```console
python -m scripts.multilingual --check-project PATH_TO_PROPOSAL_PROJECT --source-manifest PATH_TO_ORIGINAL_SOURCE/fixture.json --target-language ar --output .vita/multilingual/external-001
```

Retain the original source project beside its manifest; stale hashes fail. This
accepts the explicit synthetic LaTeX macro contract, not arbitrary CVs or PDFs.
Do not feed real-person material into a public CI artifact upload. Live model
execution requires separate explicit spending authorization and the existing
[benchmark policy](BENCHMARKING.md); this runner has no live mode.

## What is actually checked

`\CVHeading{ID}{text}` and `\CVText{ID}{text}` identify observable source units.
Balanced arguments and literal includes are read recursively. Both preserved
multifile outputs and flattened entry files can be inspected. Comments cannot
satisfy an omitted unit. Missing, repeated, dynamic, cyclic or out-of-project
includes fail explicitly rather than disappearing from coverage.

The checks detect:

- Missing/duplicate/unexpected unit identities, including education and oldest
  history; unbalanced macro arguments and missing document boundaries.
- Exact protected facts missing from **their own unit**, changed numeric values,
  untranslated source strings (where source and target drafts differ), and
  unanchored content that may be an unsupported addition.
- Differences from the target draft, including possible scope, credential-status,
  currency and acronym reinterpretations. A different valid phrasing can trigger
  this alarm: it is `review_required`, **not an automatic semantic error label**.
- Fictional-employer, changed-name/metric/unit/date, omission, added-number,
  truncation and incomplete-translation negative controls in regression tests.

The macro contract is an observable fixture boundary, not a general TeX parser,
semantic entailment engine or defense against adversarial macros. IDs alone do
not prove correct prose, absence of a hidden claim, truthful scope or visual
presence. A model that rewrites the fixture contract needs review rather than an
automatic success. Qualification status, idiom, official-name acceptability,
omission justification and factual equivalence need competent humans.

### Context and output limits

Twelve deterministic controls exercise input-context rejection, output-length
termination and a truncated standalone document for **each source language**.
The original sources and oldest included history must reach the call intact and
remain unchanged after refusal. Non-transient limits stop after one attempt;
they cannot trigger a smaller CV, another model, or a format-repair budget.

The existing provider-error v1 categories remain stable. Explicit limit signals
add optional `limit_kind: input_context | output_length`; no raw provider body or
candidate content is put in this field. Unknown bad requests remain ordinary
`invalid_request`. Provider-specific tokenizers, undocumented limits and untested
models remain unmeasured. Test thresholds/signals are fixtures, not real model
capacity measurements. A failed renderer must not trigger history shortening.

## Engine, font and rendering contract

`vita build` supports an explicit project setting:

```json
{"latex_engine": "xelatex"}
```

`pdflatex` remains the default; `xelatex` and `lualatex` select latexmk's matching
engine flag. Unknown engines fail. A fontspec/polyglossia source with pdfLaTeX
fails early with an actionable configuration message. Compiler failures point to
engine, package and font installation and the output log. Sources are not rewritten.

The real fixture matrix uses **XeLaTeX, polyglossia, DejaVu Serif and Amiri**.
Polyglossia supports Unicode engines and requires suitable script fonts; consult
the [package documentation](https://ctan.org/pkg/polyglossia) and
[latexmk documentation](https://ctan.org/pkg/latexmk).

On Ubuntu CI, install `latexmk texlive-xetex texlive-lang-arabic
texlive-lang-french texlive-lang-spanish fonts-hosny-amiri fonts-dejavu-core
poppler-utils fontconfig`. The runner checks exact font family matches rather
than accepting fontconfig's silent fallback. Missing tools/packages/fonts are
reported as unavailable/unsupported with an action. Windows without fontconfig
has an **unavailable automated font preflight**, not a passed font test; normal
Vita builds can still use an explicitly configured installed Unicode engine.

Each distinct target language/length is compiled once: **12 unique target
renderings**, reused by reference across source-language combinations. They are
not counted as 48 independent rendering attempts. Every page is rasterized and
retained, including the last history page. TeX logs flag missing glyphs and
overfull boxes; Poppler word boxes flag empty pages, out-of-page text and
unexpected page counts. PDF geometry extraction is not a semantic or visual
oracle. It does not reliably detect all overlaps, incorrect shaping, bidi order,
incorrect diacritics, clipped decorations or inaccessible logical text order.

| Combination | Evidence boundary |
| --- | --- |
| Synthetic LaTeX to LaTeX, four languages, 1/3/8 pages | Automated structural/factual alarms and full prompt capture |
| These fixtures with XeLaTeX and named fonts to PDF | CI compile, geometry alarms and raster artifacts; independent visual/linguistic review pending |
| LuaLaTeX | Engine-selection regression only; multilingual PDF fidelity unmeasured |
| pdfLaTeX with fontspec/polyglossia/these Arabic fixtures | Explicitly incompatible; choose/install a Unicode engine |
| Arbitrary fonts, engines, macros or native templates | Not established by this fixture suite |
| PDF/DOCX/scans/OCR as inputs | Unmeasured here; coordinate reviewed ingestion with [#43](https://github.com/ABDELLAH-Hallou/vita-cv/issues/43) |
| Native-template rendering/editor compatibility | Coordinate [Vita Tree #45](https://github.com/ABDELLAH-Hallou/vita-tree/issues/45); no UI claim here |

CI separates this offline suite from live providers and preserves synthetic
sources, compiler evidence and page images for 14 days. Compilation alone never
counts as correct translation, even if every mechanical alarm is clear.

## Denominators and honest pending results

Reports separate language/length strata and retain all selected cases. Structural
alarm proportions use inspected synthetic outputs as their denominator. Missing
units are omission alarms; unknown/unanchored content is an addition alarm,
not a human-adjudicated unsupported-fact rate. Target-draft equality is a
mechanical reference, not translation accuracy. Human semantic accuracy is null.

Rendering nonpass counts include unavailable and unsupported combinations in the
unique planned rendering denominator. Individual compile/layout/unavailable
counts remain visible; no renderings requested means denominator 0 and null rate.
The limit controls deliberately fail execution and pass conformance only when
that safe failure is observed. Their expected execution-failure rate is **not a
live provider reliability estimate**. Live provider failure/quality denominators
remain unavailable because no providers are executed here.

## Independent language review remains required

Before making semantic claims, preregister a separate, unexposed language holdout
using the [independent evaluation protocol](EVALUATION_PROTOCOL.md) and
[annotation guide](ANNOTATION_GUIDE.md). Do not tune on reviewed holdout results.
Extend the versioned review definitions prospectively for translation/RTL; do
not silently alter the existing protocol's label vocabulary.

Assign at least **two independent qualified human reviewers per language pair**,
competent in both languages, CV terminology and relevant qualifications. Arabic
reviewers must be fluent in Arabic and competent in Arabic typography/RTL.
Record real qualification checks, independence and conflicts privately. Synthetic
drafts or assistant judgments cannot substitute for those reviewers.

Review source and target side by side, unit by unit, including every heading,
macro argument, qualification, publication, custom section, included file and
oldest history. Independently label semantic equivalence, residual untranslated
prose, harmful omissions, unsupported specificity and factual scope. Preserve
ambiguous dates/acronyms, unspecified currency, expired/in-progress status and
official names unless authoritative source evidence supports a change.

Inspect **every rendered page**, actual mixed-direction names, metrics, dates,
punctuation, links, Arabic shaping and logical versus visual reading order.
Compare source text, PDF extraction and raster images; one cannot replace the
others. Retain unjudgeable cases and conversion/engine limitations explicitly.

Use a distinct qualified human adjudicator for disagreements; preserve original
independent labels. Report observed agreement and appropriate pre-adjudication
agreement statistics with denominators/abstentions, then adjudicated error rates
by language, length and format. Follow the uncertainty/claim boundaries of #44.
Until that work exists, report **linguistic review unavailable**, semantic quality
**unmeasured**, and RTL reading order **unreviewed**. Do not invent reviewer
identities, annotations, agreement values or quality percentages.

Source hashes in this tool fingerprint captured UTF-8 text after universal-newline
normalization; comparison whitespace/NFC normalization is separate. PDF hashes
fingerprint actual bytes. This is a fixture contract, not the canonical evidence
contract's file-identity replacement.
