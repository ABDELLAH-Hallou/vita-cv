"""TOON serialization for the JD contract's JSON shapes (TOON spec 4.x).

Supports nested objects, primitive arrays, and lists of objects containing arrays.
This deliberately is not a general-purpose TOON encoder/decoder. Uniform tables
and keyed tables are outside the JD contract and rejected rather than misencoded.
"""

import math
import re


def _quoted(value: str) -> str:
    value.encode("utf-8")
    escapes = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
    body = "".join(escapes.get(char, f"\\u{ord(char):04x}" if ord(char) < 32 else char) for char in value)
    return '"' + body + '"'


def _key(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", value) else _quoted(value)


def _primitive(value) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise ValueError("TOON JD values must be finite")
        return str(int(value)) if value == int(value) else format(value, ".15g")
    if not isinstance(value, str):
        raise ValueError("Unsupported TOON primitive")
    quote = (
        not value or value.strip(" \t") != value or value in ("true", "false", "null")
        or re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?", value, re.I)
        or any(char in value for char in ':"\\[]{},')
        or any(ord(char) < 32 for char in value) or value.startswith(("-", "#"))
    )
    value.encode("utf-8")
    return _quoted(value) if quote else value


def encode_job(data: dict) -> str:
    """Encode a validated job.json envelope deterministically with two-space indent."""
    from vita.helpers.structured import JOB_SCHEMA, validate

    validate(data, JOB_SCHEMA)

    def fields(obj, depth):
        result = []
        pad = "  " * depth
        for key, value in obj.items():
            label = _key(key)
            if isinstance(value, dict):
                result.append(f"{pad}{label}:")
                result.extend(fields(value, depth + 1))
            elif isinstance(value, list):
                if not value:
                    result.append(f"{pad}{label}: []")
                elif all(not isinstance(item, (list, dict)) for item in value):
                    result.append(f"{pad}{label}[{len(value)}]: " + ",".join(map(_primitive, value)))
                else:
                    result.append(f"{pad}{label}[{len(value)}]:")
                    for item in value:
                        lines = fields(item, depth + 2)
                        result.append("  " * (depth + 1) + "- " + lines[0].lstrip(" "))
                        result.extend(lines[1:])
            else:
                result.append(f"{pad}{label}: {_primitive(value)}")
        return result

    return "\n".join(fields(data, 0))
