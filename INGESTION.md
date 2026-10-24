# Importing existing CV documents

`vita ingest` is an optional, local, explicitly staged path from an existing
document to **reviewed transcription in editable LaTeX**. It does not reconstruct
the original design, translate, infer employment history, or call an AI provider.
The existing workflow using a `.tex` source and `tex_entry` remains supported
without running ingestion.

## Stages and their boundaries

| Stage | Command | What completes | What still needs work |
| --- | --- | --- | --- |
| Capture | `vita ingest capture old-cv.pdf` | Byte-for-byte private original, SHA-256 document identity | Extraction and all review |
| Extract | `vita ingest extract DOCUMENT_ID` | Versioned source-linked text fragments and tool artifacts | Source comparison, reading order, role/date associations, OCR corrections |
| Review | `vita ingest review EXTRACTION_REV --output .vita/ingestion/review.json` | A **blank** editable review form | Every review decision; this command approves nothing |
| Approve | `vita ingest approve EXTRACTION_REV --review .vita/ingestion/review.json` | Validation and sealing of an explicit reviewer attestation | Conversion, compilation, visual/language verification |
| Convert | `vita ingest latex APPROVAL_REV --output imported.tex --language fr` | A new generic LaTeX file, change ledger and source map | Activation, compilation, layout and linguistic review |
| Build | Existing `vita build` | A separate PDF compilation, if successful | Source fidelity, reading order and linguistic correctness still require review |

Use the **full** `doc-…` document identity and 64-character revision IDs printed
by each command. They are not interchangeable. An extraction can finish with
`state: review_required` and `stages.extract: partial`: an image, empty page or
unsupported embedded object still needs explicit handling. No LaTeX is generated
by capture, extraction, review-template creation, or approval.

Records use contract version `ingestion/1`. They describe the stage snapshot
when created, not a mutable global progress indicator. A capture record continues
to show extraction as not started after a later extraction exists. Inspect that
later revision instead:

```console
vita ingest show DOCUMENT_ID --kind documents
vita ingest show EXTRACTION_REV --kind extractions
vita ingest show APPROVAL_REV --kind approvals --json
vita ingest show EXPORT_REV --kind exports --json
```

Default command output contains stage identities, counts, paths and safe errors.
`--json` on capture, extract or show explicitly prints full local records, which
can contain private CV text. Do not paste them into public bug reports unredacted.
Exit codes are `0` for the requested operation completed, `1` for a blocked or
invalid operation, `2` for invalid command syntax, and `3` for an extraction that
returned reviewable but incomplete fragments. Exit `0` does **not** mean approved,
compiled, factually correct or ready to submit.

## Supported inputs and local dependencies

| Input | Extraction | Limits and uncertainty |
| --- | --- | --- |
| Text PDF | Local Poppler `pdfinfo` and `pdftotext -bbox-layout` | Page/block/line/word coordinates; spaces and line breaks reconstructed from the text layer, not recovered authoring paragraphs |
| Scanned/image-only PDF | Explicit local Tesseract OCR, with Poppler `pdftoppm` rasterization | No automatic OCR, inferred language or automatic approval; empty pages remain explicit placeholders |
| DOCX | Standard-library ZIP/XML reading; no Office or Python package dependency | Main document, headers, footers, footnotes, endnotes, comments, table/text-box paragraphs and external relationship targets; actual rendered page numbers unavailable |
| PNG/JPEG | Explicit Tesseract OCR, or a visual placeholder for source-checked manual transcription | One source image/page; structural image checks and pixel limits; OCR requires the local image decoder to accept the content |

Install local executables yourself and make them available on `PATH`. Nothing
downloads OCR models or sends documents to external conversion services. For
example, on Debian/Ubuntu, the optional PDF/OCR tools and these language packs are:

```console
sudo apt-get install poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-spa tesseract-ocr-ara
```

On other systems install corresponding Poppler and Tesseract packages locally.
Check `tesseract --list-langs` before choosing languages. OCR is explicit:

```console
vita ingest extract DOCUMENT_ID --ocr --ocr-language eng+fra
```

For PDFs this OCRs only pages without extracted text. An incorrect/incomplete
existing text layer requires an explicit override:

```console
vita ingest extract DOCUMENT_ID --ocr --ocr-language ara --ocr-all
```

`--ocr-all` requires `--ocr`. Original PDF bytes and the original extracted text
artifact remain retained even when the new revision uses OCR for those pages.
Each extraction records requested languages, invocation counts, available tool
versions and raw local tool outputs. Tesseract uses page segmentation mode 3 and
TSV output. Its word scores are **uncalibrated confidence values**, not accuracy
probabilities. Values below 80 are flagged; every OCR fragment still requires
review, including high-confidence results. No `4O%` to `40%` correction is guessed.
PDF/DOCX text does not acquire fabricated OCR confidence.

DOCX image OCR is not implemented. Export an image-based DOCX to a new PDF locally
and capture it as a new source, or explicitly transcribe its visual placeholders
while viewing the original. Drawings/images, fields, tracked changes, hidden
text, multiple columns and unsupported `altChunk` content are flagged for review;
their visual appearance or field evaluation is not reconstructed. XML text can
include deleted/comment/header material that should be explicitly omitted rather
than silently lost. Hyperlink targets are retained as source text, never fetched.
DOCX page hints from explicit/cached breaks are **not rendered pagination**.

Legacy `.doc`, `.docm`, TIFF, HTML, encrypted/password-protected PDFs and encrypted
Office containers are unsupported. Export an unlocked supported copy locally;
do not put passwords in command arguments. Capture can preserve an unsupported
file, but its extraction stays blocked. Corrupt documents and missing tools
produce actionable blocked records, not empty successful CVs. A valid extension
or ZIP signature alone does not establish a valid Office document.

## Reviewing wording, facts and associations

After extraction, open the private `review.md` path printed by the CLI alongside
the captured original. The original is stored as `original.bin`; its original
basename and format are in `document.json`. Use a local viewer that can open it,
or copy it to a separate local viewing location with the original extension.
Do not edit the captured copy. Inspect the actual pages/document, not only the
extracted text.

Then create the review form and fill it deliberately. For **each** paragraph or
visual fragment:

- Keep `id`, `source_ref` and `original_text` unchanged. They bind the decision to
  a specific captured source and extraction revision.
- Set `source_checked` to `true` only after comparing with the original.
- Set `decision` to `keep`, `correct` or `omit`, and explain it in `rationale`.
  `keep` requires `approved_text` to equal the exact nonempty extracted wording.
  `omit` requires `approved_text: null` and an explicit explanation. Omitting
  the entire document is rejected.
- For a correction, provide `approved_text` and
  `factual_change_confirmed: true` only when confirmed against the source.
  Transcribing an empty visual placeholder also requires
  `manual_transcription: true`. Ingestion does not independently verify what a
  reviewer types.
- Set `association: "preserve_unassigned"` to keep unresolved role/date
  relationships unassigned, or use a source-checked group ID such as
  `"group:employment_1"`. Record the reason. A group records a review decision;
  it does not invent a job title, rewrite a date, or automatically merge text.

At the top of the form, identify the reviewer, set `original_viewed` and
`reading_order_checked` to `true` only after those checks, and explain every
entry in `issue_resolutions`. Reorder the `order` array to the verified reading
order. It must contain every paragraph ID exactly once, including omissions.
No blank/pending form, unchecked fragment, unresolved association or unconfirmed
correction can pass approval. There is no `--yes` or automatic approval mode.

PDF blocks and OCR segments are layout fragments, not semantic claims. Columns
can detach dates from roles and are flagged using geometry, but the detector is
not a complete layout recognizer. **All** fragments require association and
reading-order review even when no column flag appears. Preserve uncertainty
such as `Sen 2017`, undefined `TTR`, unspecified currency, OOP versus Object
Oriented Design, expired/in-progress qualifications, metrics, units and official
names. Do not expand or normalize them into unsupported facts. The ingestion
stage does not tailor the CV or resolve these ambiguities automatically.

Approval means `approved_attested`, explicitly a reviewer attestation rather
than independent semantic verification. Review JSON is a local trust boundary;
software cannot establish that a person truly inspected the source. Automated
tests use clearly labelled synthetic attestations solely to exercise the gate.

## Editable output and provenance

Choose `--language en`, `es`, `fr` or `ar` for the **source language**, not a
translation request. Conversion preserves approved wording in a generic single
column XeLaTeX template with DejaVu Serif and Amiri. Arabic runs and Latin
names/dates are isolated for direction handling. CJK/Korean content is blocked
with an unsupported-font message rather than discarded. Other untested scripts
or font/engine combinations require a suitable template and independent checks.
The template escapes LaTeX metacharacters, renders tabs as spacing, preserves
explicit line breaks, and does not execute source text as LaTeX commands.

After conversion, inspect `imported.tex`, then deliberately configure the project
to use it (for example in `.vita/config.json`):

```json
{
  "tex_entry": "imported.tex",
  "latex_engine": "xelatex"
}
```

Install XeLaTeX, `latexmk`, the required Polyglossia language packages and the
named fonts before `vita build`. Retain any other existing project settings.
Ingestion never changes `tex_entry`, overwrites an existing `.tex`, activates a
new CV, or compiles it automatically. Direct `.tex` projects need none of these
import stages. Generic conversion does not promise original-layout replication.

Private exports contain a source map linking generated LaTeX line spans and
approved text hashes to document/paragraph identities and page/part references.
A change ledger records corrections, omissions, original/approved wording,
reviewed associations and textual diffs. Extraction artifacts retain word
positions, raw TSV/XHTML/tool logs and hashes. Source identities identify bytes,
not whether a CV claim is true or a qualification valid.

Original, extraction and approval bindings are rechecked before reuse. Changed
source bytes/artifacts invalidate their descendants; capture/extract/review a
new revision instead. Editing the generated LaTeX is expected, but `show` then
reports `edited_source_map_no_longer_exact`; the old map cannot certify later
edits. An export record starts `latex: prepared`. Only successful exclusive
publication with a completion receipt yields `generated`. Failed publication
does not claim a completed LaTeX stage. Compilation remains `not_run`, layout
review `pending`, and linguistic review `unavailable` in ingestion records.

## Privacy and resource limits

Originals and intermediate content are inside `.vita/ingestion/`, protected by a
nested `.gitignore`. Ingestion refuses to proceed when private artifacts are
already tracked in Git. This prevents normal `vita save`/`git add` from silently
staging imported originals; it is not encryption, access control, or protection
against a deliberate force-add. Review forms should also stay in this ignored
folder. An explicitly generated `.tex` outside that folder is ordinary project
content: inspect it before committing, sharing or running a later AI command.
No ingestion command calls a provider, follows document links, pushes Git, or
uploads source content. CI uploads **synthetic test fixtures only**.

Current conservative limits are 20 MiB per captured input, 30 PDF pages,
25 million pixels per image/rasterized page, 64 MiB expanded XML/ZIP and tool
artifact limits, 500 ZIP entries, compression ratio at most 300, 2 million
extracted characters and 20,000 fragments. Local extraction commands have a
60-second timeout. These checks are not an operating-system resource sandbox;
tool output size is checked after execution. Keep local tools patched and
process untrusted files in an appropriate environment. No history or pages are
silently removed to meet a cap. Reduce/convert the source explicitly or use the
direct-LaTeX workflow; a limit failure leaves the original intact.

## Reproducible checks and remaining review

Run the unit regressions without OCR, a provider or Office:

```console
python -m pytest tests/test_ingestion.py
```

For real PDF/OCR integration, install the tools above, `qpdf` (encrypted negative
control only), and the Unicode LaTeX/font dependencies described in
[MULTILINGUAL_VALIDATION.md](MULTILINGUAL_VALIDATION.md). Use new output directories:

```console
python -m scripts.multilingual --real-pdf --output .vita/multilingual-fixtures
python -m scripts.ingestion_smoke --pdf-corpus .vita/multilingual-fixtures --output .vita/ingestion-fixtures
```

CI checks synthetic English, Spanish, French and Arabic DOCX, real text PDFs,
columns, eight-page history, explicit OCR of image-only PDFs, encrypted/corrupt
and oversized inputs, blocked unreviewed conversion and Unicode compilation.
Unit controls additionally exercise ZIP/XML bounds, image structure, OCR
confidence/wording, source tampering, review changes, omissions, Git privacy and
atomic output publication. Missing integration tools are reported unavailable
and fail that integration run, not counted as passed.

Real independent source, OCR, linguistic and RTL reading-order reviews remain
pending. Compilation and nonempty OCR output do not establish correct wording,
reading order, factual fidelity or layout. The integration report leaves OCR
accuracy and semantic fidelity unmeasured; simulated software attestations are
not human annotations. ATS compatibility and hiring outcomes are unvalidated.

Reference documentation:
[Tesseract installation](https://tesseract-ocr.github.io/tessdoc/Installation.html),
[Tesseract CLI and TSV](https://github.com/tesseract-ocr/tessdoc/blob/main/Command-Line-Usage.md),
[WordprocessingML paragraphs](https://learn.microsoft.com/en-us/office/open-xml/word/working-with-paragraphs).
