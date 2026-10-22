"""Versioned JSON contracts and strict validation for pipeline artifacts.

The validator implements only the JSON Schema keywords used by these contracts.
No model response is saved as a successful artifact until it passes validation.
"""

import json
import math
import re
import tempfile
from pathlib import Path

CATEGORIES = ("hard_skills", "soft_skills", "experience", "responsibilities", "keywords")
STRING = {"type": "string"}
TEXT = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": TEXT}
SCORE = {"type": "number", "minimum": 0, "maximum": 100}
COUNT = {"type": "integer", "minimum": 0}


def object_schema(properties: dict, optional: tuple = ()) -> dict:
    return {"type": "object", "properties": properties,
            "required": [key for key in properties if key not in optional],
            "additionalProperties": False}


JOB_SCHEMA = object_schema({
    "schema_version": {"type": "integer", "const": 1},
    "source_sha256": TEXT,
    "jobs": {"type": "array", "minItems": 1, "items": object_schema({
        "id": TEXT,
        **{key: {"type": ["string", "null"]} for key in ("title", "company", "location", "date_posted")},
        "hard_skills": STRINGS,
        "soft_skills": STRINGS,
        "requirements": object_schema({"must_have": STRINGS, "nice_to_have": STRINGS}),
        "responsibilities": STRINGS,
        "summary": STRING,
    })},
})

CRITERION_SCHEMA = object_schema({
    "id": TEXT, "job_id": TEXT, "category": {"type": "string", "enum": list(CATEGORIES)},
    "criterion": TEXT, "importance": {"type": "string", "enum": ["must_have", "nice_to_have"]},
    "status": {"type": "string", "enum": ["matched", "partial", "missing"]},
    "evidence": STRING, "feedback": STRING,
})
EVALUATION_SCHEMA = object_schema({
    "schema_version": {"type": "integer", "const": 1},
    "overall_score": SCORE,
    "category_scores": object_schema({category: SCORE for category in CATEGORIES}),
    "executive_summary": TEXT,
    "qualitative_summary": STRING,
    "comparison": object_schema({
        "status": {"type": "string", "enum": ["available", "unavailable", "not_applicable", "not_recorded"]},
        "baseline_overall_score": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
        "overall_delta": {"type": ["number", "null"], "minimum": -100, "maximum": 100},
    }),
    "strengths": STRINGS, "gaps": STRINGS, "recommendations": STRINGS,
    "metrics": object_schema({
        "criteria": {"type": "array", "minItems": 1, "items": CRITERION_SCHEMA},
        "matched_count": COUNT, "partial_count": COUNT, "missing_count": COUNT, "total_count": COUNT,
    }),
    "metadata": object_schema({
        "job_sha256": TEXT, "context_sha256": TEXT, "criteria_sha256": TEXT,
        "rubric_version": {"type": "string", "const": "weighted-criteria-v1"},
    }),
}, optional=("metadata", "qualitative_summary", "comparison"))

# Provenance and public report summaries/comparisons are supplied by the host.
# Excluding host-owned fields also avoids optional fields in strict APIs.
EVALUATION_OUTPUT_SCHEMA = object_schema({
    key: value for key, value in EVALUATION_SCHEMA["properties"].items()
    if key not in {"metadata", "qualitative_summary", "comparison"}
})


def generation_schema(schema: dict) -> dict:
    """Conservative provider subset; the full host contract stays authoritative."""
    result = {key: schema[key] for key in ("type", "enum") if key in schema}
    if "const" in schema:
        result["enum"] = [schema["const"]]
    if "properties" in schema:
        result["properties"] = {key: generation_schema(value) for key, value in schema["properties"].items()}
        result["required"] = list(schema["properties"])
        result["additionalProperties"] = False
    if "items" in schema:
        result["items"] = generation_schema(schema["items"])
    return result


def validate(value, schema: dict, path: str = "$") -> None:
    expected = schema["type"]
    types = expected if isinstance(expected, list) else [expected]
    matches = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "null": value is None,
        "integer": type(value) is int,
        "number": type(value) is int or (type(value) is float and math.isfinite(value)),
    }
    if not any(matches[kind] for kind in types):
        raise ValueError(f"{path}: expected {expected}")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path}: unsupported schema/rubric version")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: invalid enum value")
    if isinstance(value, dict):
        properties = schema["properties"]
        if set(schema["required"]) - value.keys() or value.keys() - properties.keys():
            raise ValueError(f"{path}: missing required or unexpected fields")
        for key, item in value.items():
            validate(item, properties[key], f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{path}: too few items")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value.strip()) < schema.get("minLength", 0):
            raise ValueError(f"{path}: empty text")
        value.encode("utf-8")  # Reject lone surrogates before artifact writes.
    elif type(value) in (int, float):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError(f"{path}: number outside allowed range")


def parse_json(text: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Non-finite JSON number")

    text = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.DOTALL)
    value = json.loads(fence.group(1) if fence else text,
                       object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("Expected one JSON object")
    return value


def json_text(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def write_artifact(path: Path, text: str) -> None:
    """Replace an artifact only after its complete UTF-8 contents have been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
