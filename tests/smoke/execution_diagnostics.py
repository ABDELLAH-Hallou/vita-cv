"""Installed-wheel diagnostics privacy control; never calls a live provider."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

from vita.helpers.diagnostics import inspect_trace
from vita.helpers.diagnostics_contract import EVENT_SCHEMA
from vita.helpers.provider_errors import ProviderError
from vita.helpers.structured import validate
from vita.helpers.structured_output import StructuredOutputError, run_text


def main():
    canary = "PRIVATE_EXECUTION_DIAGNOSTICS_CANARY"
    provider = Mock(side_effect=ProviderError(status=503))
    before = set(Path(".vita/logs/traces").glob("*"))
    with patch.dict("os.environ", {"VITA_DIAGNOSTIC_CONTENT": "off"}), patch("vita.helpers.structured_output.time.sleep"):
        try:
            run_text(step="cover", generate=provider, system=canary, prompt=canary,
                     route={"provider": "gemini", "model": "synthetic-model"})
        except StructuredOutputError:
            pass  # Expected synthetic overload; inspect its separate diagnostics.
        else:
            raise AssertionError("Synthetic provider failure was accepted")
    added = set(Path(".vita/logs/traces").glob("*")) - before
    trace = next(p for p in added if p.is_dir() and len(p.name) == 32)
    result = inspect_trace(trace.name)
    assert result["processes"][0]["status"] == "failed" and provider.call_count == 3
    assert result["processes"][0]["failure"]["category"] == "overloaded"
    for file in trace.rglob("*"):
        if file.is_file():
            text = file.read_text(encoding="utf-8")
            assert canary not in text
            if file.suffix == ".jsonl":
                for line in text.splitlines():
                    validate(json.loads(line), EVENT_SCHEMA)
    print("Installed execution diagnostics privacy control passed")


if __name__ == "__main__":
    main()
