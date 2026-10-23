"""Public diagnostics v1 schemas, separate from business/outcome contracts."""

from vita.helpers.diagnostics import CAPTURE_STATUSES, CATEGORIES, EVENTS, PHASES
from vita.helpers.structured import object_schema

TEXT = {"type": "string"}
TOKEN = {"type": ["string", "null"]}
COUNT = {"type": "integer", "minimum": 0}
VERSION = {"type": "integer", "const": 1}
DETAILS = object_schema({
    **{key: COUNT for key in ("attempt", "attempts", "max_attempts", "http_status", "line", "column", "offset", "bytes", "chars")},
    **{key: {"type": "number", "minimum": 0} for key in ("duration_ms", "delay_seconds", "retry_after_seconds")},
    **{key: TOKEN for key in ("requested_provider", "effective_provider", "requested_model", "effective_model", "reasoning")},
    **{key: TEXT for key in ("prompt_sha256", "schema_sha256", "adapter_sha256", "request_id_sha256", "credential_variable", "credential_origin", "provider_origin", "model_origin", "reasoning_origin", "provider_code", "location", "exception_type")},
    **{key: {"type": ["boolean", "null"]} for key in ("retryable", "credential_present", "response_exists", "http_response_exists", "reused")},
    "category": {"type": "string", "enum": list(CATEGORIES)},
    "outcome_run_id": TEXT,
})
DETAILS["required"] = []
EVENT_SCHEMA = object_schema({
    "schema_version": VERSION, "trace_id": TEXT, "process_id": TEXT,
    "workflow_id": TEXT, "step": TOKEN, "step_id": TOKEN, "sequence": COUNT,
    "attempt_id": TOKEN,
    "timestamp": TEXT, "event": {"type": "string", "enum": list(EVENTS)},
    "phase": {"type": "string", "enum": list(PHASES)},
    "span_id": TOKEN, "parent_span_id": TOKEN,
    "status": {"type": "string", "enum": ["ok", "error", "running", "interrupted"]},
    "details": DETAILS,
})
REFERENCE_SCHEMA = object_schema({
    "id": TEXT, "kind": TEXT, "capture_status": {"type": "string", "enum": list(CAPTURE_STATUSES)},
    "step_id": TOKEN, "attempt_id": TOKEN,
    "reason": TEXT, "content_exists": {"type": ["boolean", "null"]}, "path": TOKEN, "bytes": COUNT,
})
MANIFEST_SCHEMA = object_schema({
    "schema_version": VERSION, "trace_id": TEXT, "product": {"type": "string", "const": "vita-cv"},
    "product_version": TEXT, "ownership": {"type": "string", "const": "project"},
    "process_manifests": TEXT, "events": TEXT, "artifact_limit_bytes": COUNT,
    "content_policy": {"type": "string", "const": "source-aware-structure-only"},
    "trace_context_status": {"type": "string", "enum": ["accepted", "generated", "rejected"]},
})
FAILURE_SCHEMA = object_schema({"phase": TEXT, "details": DETAILS, "frames": {"type": "array", "items": object_schema({"module": TEXT, "line": COUNT})}})
PROCESS_SCHEMA = object_schema({
    "product_version": TEXT,
    "schema_version": VERSION, "trace_id": TEXT, "process_id": TEXT, "status": {"type": "string", "enum": ["running", "success", "failed", "interrupted", "incomplete"]},
    "updated_at": TEXT, "active_spans": {"type": "array", "items": object_schema({"span_id": TEXT, "parent_span_id": TOKEN, "phase": TEXT})},
    "failure": {**FAILURE_SCHEMA, "type": ["object", "null"]},
    "capture_enabled": {"type": "boolean"}, "logging_complete": {"type": "boolean"},
    "diagnostic_artifacts": {"type": "array", "items": REFERENCE_SCHEMA},
})
ARTIFACT_SCHEMA = object_schema({
    "schema_version": VERSION, "kind": TEXT,
    "capture_status": {"type": "string", "enum": list(CAPTURE_STATUSES)},
    "data": {"type": "object", "additionalProperties": True},
})
SCHEMAS = {"event": EVENT_SCHEMA, "manifest": MANIFEST_SCHEMA, "process": PROCESS_SCHEMA, "reference": REFERENCE_SCHEMA, "artifact": ARTIFACT_SCHEMA}
