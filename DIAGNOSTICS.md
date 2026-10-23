# Execution journals and diagnostics

Use `vita extract --auto --debug` (or `run`, `analyze`, `adapt`, `review`,
`cover`, or `build` with `--debug`) to retain a detailed **local developer
journal** for that command. This overrides an existing `off` setting for that
invocation without editing project configuration. Inspect it with:

```sh
vita diagnostics inspect
vita diagnostics inspect latest --json
vita diagnostics inspect TRACE_ID
```

`inspect` defaults to the last-started trace, recorded in
`.vita/logs/traces/latest.json`. Concurrent runs have independent trace/process
directories; inspect the explicit trace printed on failure when several runs
overlap. An outcome's `run_id` is recorded as `outcome_run_id` in the execution
journal and technical events, so it can also be searched across trace folders.

New projects and runs with no content setting default to
`VITA_DIAGNOSTIC_CONTENT=local`. Existing explicit `off`/`sanitized` settings
remain effective unless `--debug` is supplied. Modes:

| Mode | Local contents |
|---|---|
| `local` | Full visible prompts, requests, responses, errors, runtime and configuration decisions, with credentials redacted |
| `off` | Technical metadata only; candidate content is excluded |
| `sanitized` | Technical metadata plus structure-only response diagnostics |

The developer journal belongs to the **CV application project**, not the Python
installation directory or a temporary integration staging directory. It contains
candidate data and is private local working material. The support export remains
sanitized regardless of the capture mode.

## Developer journal

Each process writes `journal/<process-id>/` within its trace:

```text
execution.log                         readable chronological journal
events.jsonl                          equivalent structured records (journal_version=1)
runtime.json                          Vita/Python version, executable, package path, cwd, argv
configuration.json                    configuration decisions, candidates, origins and overrides
index.json                            artifact paths, step/attempt IDs, sizes, truncation flags
steps/<step-id>/attempts/<attempt-id>/
  system-prompt.txt                   actual system text
  user-prompt.txt                     actual user text, including schema/format-retry additions
  http-request.json                   endpoint, method, headers, body and timeout
  http-response.json                  status, response headers, provider request ID
  http-response-body.txt              decoded HTTP success body
  provider-error-body.txt             decoded HTTP error body
  model-output.txt                    extracted model output, including malformed JSON
  exception-<id>.txt                  full traceback, exception message and chained causes
  cli-request.json / cli-result.json  argv/stdin, schema, exit code, stdout and stderr
  build-request.json / build-result.json
  generated-prompt.txt                generated external-assistant instructions only
```

Initial preparation uses the `preflight` attempt directory. Runtime/configuration
files are process-level; all actual generation attempts retain separate prompts
and outputs. Artifact-save events in `execution.log` link to the index paths.
The readable journal includes UTC timestamps, severity, step/attempt correlation,
module/function/file/line, parameters, phase durations and retry decisions.
Full exceptions include dependency frames and source lines, without dumping
frame locals or the entire process environment. Configuration records include
project settings, selected skill paths, routing variables and their origins;
credential records include presence/source only. Arbitrary objects are identified
by type rather than serialized through potentially sensitive `repr()` methods.

For example, extraction can select `gemini-2.5-flash` even when the provider entry
in `.vita/extensions.json` selects another model. `configuration.stage_route`
identifies `built_in_extraction_default` when `EXTRACTION_MODEL` is unset.
`configuration.provider_route` records both the extensions model and the effective
model and explains that the explicitly supplied stage model has precedence.
`configuration.environment` distinguishes process overrides from `.vita/.env`.
This change makes that decision observable; it does not change routing defaults,
model precedence, provider calls, retry budgets, assessment results or approval
requirements. HTTP error classification still uses the first 8 KiB as before;
the local journal captures up to 2 MiB of the error body and states when the read
limit is reached. Retry records include scheduled and measured delays.

Visible prompt/output text is preserved, including invalid JSON, except where
credential redaction or provider-internal reasoning suppression is necessary.
Known credentials and their URL-encoded forms, authorization/cookie headers,
credential fields and common inline credential patterns are removed before
writing. Structured provider-internal thought/reasoning fields are omitted;
configured reasoning **effort** is retained. Redacted JSON may be reformatted.
This is secret redaction, **not anonymization**: CVs, job descriptions, writing
skills and provider error prose remain in local mode. Protect the project and
do not share/commit the journal directory. Export a technical support bundle
instead. Locals, arbitrary environment dumps, credentials and hidden model
reasoning are not required to diagnose a provider request.

Generated-prompt mode records the actual generated instructions and explicitly
states that no external generation/response was observed. It cannot capture an
assistant's later execution outside Vita. A cache reuse records zero provider
calls and does not fabricate new request/response artifacts. Historical discarded
prompts/responses cannot be reconstructed.

Local artifacts have a 2 MiB limit; truncation is explicit in both the file and
`index.json`, including original redacted size. Each process has a 32 MiB budget,
and the combined trace store has a 256 MiB cap. Limits apply to diagnostics only;
business output is never truncated by logging. Retention, permissions, process
isolation and failure behavior below apply to both lanes. Logging failures can
leave an incomplete journal, emit a warning, and never trigger an extra provider
call or change the business result.

## Sanitized technical contract v1

Vita CV records local execution diagnostics for automatic and generated-prompt
AI workflows, independently of validated CV/job/assessment outputs and the
existing `.vita/results/<step>.outcome.json` contract. The diagnostic layer makes
no generation calls, adds no retries, changes no route, and never makes an
invalid assessment acceptable. Version 1 consumers must ignore optional future
fields and reject unsupported major schema versions. Existing outcome consumers
can continue unchanged.
Legacy attempt/outcome `detail` strings are also restricted to safe schema
constraints or a fixed host-validation explanation. Arbitrary exception prose
is not copied into those existing files or repair prompts; their fields and
retry behavior remain compatible.

## Ownership and correlation

The application project owns `.vita/logs/traces/<trace-id>/`. Diagnostics are not
placed in a temporary Codex response directory. Project discovery walks from the
initial working directory to the nearest `.vita` directory; integrations with a
staging directory should always set the absolute project root explicitly.

```text
manifest.json                         atomic, trace-level contract/product data
process-<process-instance-id>.json     atomic, independent process completion
events-<process-instance-id>-N.jsonl   bounded per-process event stream
artifacts/<process-id>-<id>.json       bounded, sanitized diagnostic artifacts
journal/<process-id>/                 private developer files, excluded from exports
```

`trace_id` is 32 lowercase hexadecimal characters. `workflow_id` identifies one
local execution; `step_id`, `span_id`, `parent_span_id`, and `attempt_id` identify
its steps, nested phases and provider attempts. Parent spans can originate in
Tree. A format retry is an additional attempt inside the same step/run budget;
an independent execution gets a new workflow/process identity. The event details
include `outcome_run_id` to correlate the existing outcome record without adding
required fields to that contract. Cache reuse is explicitly an event with zero
provider calls. A new UUID process instance is used even when the OS reuses a PID.

Events have `schema_version`, correlation IDs, `sequence`, UTC `timestamp`, typed
`event`, `phase`, `status`, and allowlisted `details`. Event types are `span_start`,
`span_end`, `attempt`, `retry`, `route`, `capture`, `error`, and `cache`. Phases cover
`workflow`, `step`, `configuration`, `context`, `prompt`, `provider_request`,
`decoding`, `validation`, and `persistence`. Durations use a monotonic clock;
retry events record measured delay, not just the planned wait.

Machine-readable schemas are exported as `SCHEMAS` from
`vita.helpers.diagnostics_contract`, with checked-in JSON schema and success/
failure fixtures under `tests/fixtures/diagnostics/`. These schemas are owned by
Vita CV; Tree reads them and must not rewrite CV's event streams or process
manifests. Each process writes only its own stream and process manifest. Trace
manifest metadata is immutable in meaning and safely replaced atomically; it
does not contain a shared mutable list of children.

`process.status` is `running`, `success`, `failed`, `interrupted`, or `incomplete`.
Inspection represents a manifest without a completion record as
`incomplete_or_running`: absence of an end event proves neither a crash nor a
currently live process. Normal exceptions, keyboard interruption and interpreter
exit record completion when possible. Abrupt kill, power loss or logging failure
can leave a running manifest or final partial JSONL line. Do not infer success
from them. Sequence gaps can result from bounded event rotation. There is no
attempt to reconstruct unrecorded history.

## Privacy boundary and capture statuses

The technical v1 lane retains technical metadata, prompt section labels/sizes, schema
structure and a labelled safe instruction summary. Exact interpolated prompts,
CVs, job descriptions, custom skills, provider error prose and model output are
not copied into that lane. The separate local journal retains them when enabled.
Business artifacts retain their existing content
and privacy characteristics; this is not a mechanism for anonymizing a CV.

Set `VITA_DIAGNOSTIC_CONTENT=sanitized` explicitly for additional response and
provider-error structure. This mode retains a fixed vocabulary of structural
field names, scalar types and sizes, replaces all source values and unknown
field names, and suppresses hidden reasoning. It does **not** enable raw capture.
Unstructured text, malformed/unbounded content or structures that cannot be
safely represented are suppressed. This conservative mode helps diagnose envelope
and schema errors; it does not recover the original prose. Regex-based removal
alone cannot guarantee anonymization, so regex is not used as permission to
persist arbitrary content.

Every capture reference has an ID, step/attempt correlation, `kind`,
`capture_status`, `reason`, `content_exists`, bounded relative `path` or `null`,
and size. Status meanings:

| Status | Meaning |
|---|---|
| `captured` | Host-authored safe diagnostic summary was saved |
| `redacted` | Source sections/values were replaced before writing |
| `disabled` | Content exists but content capture is off |
| `suppressed` | Capture requested but safe representation could not be established |
| `truncated` | Safe structure exceeded its artifact limit; a size-limit marker was saved |
| `unavailable` | Not observed, rejected before model output, unknown after transport, or logging failed |

`content_exists: false` and `no_model_response_produced` describe a known rejection
before usable model output. `null` means unknown/not observed, including some
transport failures; it is not an empty response. HTTP bodies and model responses
are distinct capture kinds. An unexpected HTTP-success envelope is
`response_shape`; invalid JSON/UTF-8 at the HTTP layer is `response_decode`.
Neither is guessed to be authentication or transport failure. Unknown causes
remain `unclassified`. Known provider categories retain the provider-error
contract and its retryability rules.
New diagnostic-only `tls`, `response_shape` and `response_decode` causes retain
`provider_error` in the legacy outcome category vocabulary, with safe specific
action text. This avoids invalidating consumers using the original v1 enum.

Diagnostics allowlist requested/effective provider/model/reasoning identifiers,
configuration origin categories, credential **presence** and variable/source
category, prompt/schema/adapter hashes, product version, HTTP status, recognized
provider codes, retry information, decoder/validation locations, and exception
types. Provider request IDs are recorded as SHA-256 references to avoid copying
arbitrary header values. The original ID cannot be recovered from that digest.
Technical stacks include Vita module names and line numbers; external paths, source lines,
locals, exception messages, full configuration/environment objects, authorization
headers, cookies and request URLs are excluded. CLI-inherited credentials/model
settings are unreported rather than asserted. Routing snapshots remain private.

## Storage and failure behavior

Technical artifacts are limited to 16 KiB each. Each process has a 32 MiB reservation; technical event
files rotate at 256 KiB and retain at most four files per process. The store has
a 256 MiB total cap, 100-trace limit and seven-day retention of completed traces,
checked on new executions. Reservations and a cross-process I/O lock coordinate
writers conservatively, so concurrent active runs can reach the cap early.
Completed traces are deleted oldest first when needed. Active/incomplete traces
and crash reservations are preserved; review and remove them explicitly if they
exhaust the store. No background collector or database is required.

On POSIX, trace directories use mode 0700 and files use 0600 where supported.
Windows relies on inherited project-directory ACLs; the application does not
claim to configure or verify NTFS ACLs. Protect the project directory. `.vita/`
is excluded from this repository's Git tracking; integration projects should
ignore `.vita/logs/`. The trace store also creates narrow `.gitignore` rules for
trace-ID directories, reservations and its lock, preserving existing rules.
Ignore rules cannot untrack previously committed files or defeat a force-add.
Diagnostics failure emits a safe warning and never causes
a new model call, retry, provider fallback, or replacement of the original error.
Failed logging can leave an incomplete manifest. Retention and limits bound the
diagnostic store, not existing business outputs or the legacy activity log.

## Vita Tree integration

Before launching a subprocess, set:

```text
VITA_PROJECT_ROOT=<absolute application project directory>
VITA_TRACEPARENT=00-<32-hex-tree-trace-id>-<16-hex-parent-span-id>-01
VITA_DIAGNOSTICS_DIR=<optional absolute persistent traces directory>
VITA_DIAGNOSTIC_CONTENT=local
```

`VITA_DIAGNOSTICS_DIR` names the **traces store**, not one trace's folder. It can
point outside a staging directory and should have appropriate access controls
and Git exclusions. Only W3C version-00 lowercase traceparent with nonzero IDs
and flags `00`/`01` is accepted. Invalid input generates a fresh trace and records
`trace_context_status: rejected`; raw invalid input is never logged. Without an
incoming context, Vita generates a standalone trace. The trace context does not
authorize content capture. OpenTelemetry export is a future extension.

Tree already knows the trace ID when it supplies a valid parent. Read
`<store>/<trace-id>/manifest.json`, enumerate independent `process-*.json`, then
consume JSONL files by process ID and sequence. Wait for subprocess exit before
assuming all final events are available. Join attempts using step/attempt IDs
and outcomes using `outcome_run_id`; do not infer causality from timestamps
alone. Read capture status and `content_exists` before showing an artifact link.
Artifact paths are relative to the trace directory; reject escaping/symlink
paths. A nonzero CLI exit remains authoritative even when older business outputs
are present. Export/inspection reapply the boundary, not arbitrary log contents.

## New inspection and export commands

These commands are introduced by this change; they were not present in previous
Vita CV versions:

```sh
vita diagnostics list
vita diagnostics inspect TRACE_ID --json
vita diagnostics export TRACE_ID --output technical-diagnostics.zip
```

Exports contain a re-sanitized technical `diagnostics.json` and explanatory
README. Artifact **bodies** and the private journal are excluded, including in local mode,
so a local file edited after capture cannot bypass the export boundary. Existing
export files are not overwritten. Failures print phase, effective route, known
category/status, next action, trace ID/location, response availability and capture
mode. Ordinary successful commands do not print a diagnostics banner.

Older attempts files did not retain these details. Upgrading does not reconstruct
discarded request bodies, responses, provider IDs or exception traces. Reproduce
with fixtures first; a live retry/generation still needs the user's provider and
spending authorization. Diagnostics tests measure contracts and redaction, not
model quality, availability, factual truth, or guaranteed anonymization.
