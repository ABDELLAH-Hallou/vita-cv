"""Installed-wheel developer diagnostics replay, synthetic and network-free."""

import io
import json
import os
import tempfile
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from vita.helpers import diagnostics as d
from vita.helpers import llm
from vita.helpers.pipeline_config import load_pipeline_settings
from vita.helpers.structured_output import StructuredOutputError, run_text


@d.diagnosed(name="extract")
def replay():
    route = load_pipeline_settings().route("extract").kwargs()
    run_text(
        step="extract",
        generate=llm.generate,
        system="PRIVATE_SYSTEM_CANARY",
        prompt="PRIVATE_USER_CANARY",
        route=route,
    )


def main():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as temporary:
        try:
            os.chdir(temporary)
            Path(".vita").mkdir()
            Path(".vita/extensions.json").write_text(
                json.dumps({"llm_providers": {"gemini": {"model": "configured-gemini"}}}),
                encoding="utf-8",
            )
            error = urllib.error.HTTPError(
                "https://provider.invalid",
                401,
                "Unauthorized",
                {"x-request-id": "synthetic-request-id"},
                io.BytesIO(b'{"error":{"message":"Specific synthetic provider failure"}}'),
            )
            with (
                patch.dict(
                    os.environ,
                    {
                        "VITA_PROJECT_ROOT": temporary,
                        "VITA_DIAGNOSTICS_DIR": str(Path(temporary) / ".vita/logs/traces"),
                        "VITA_DIAGNOSTIC_CONTENT": "local",
                        "GEMINI_API_KEY": "fixture-private-api-secret",
                        "EXTRACTION_MODEL": "",
                        "EXTRACTION_PROVIDER": "gemini",
                    },
                ),
                patch.object(llm.urllib.request, "urlopen", side_effect=error) as http,
            ):
                try:
                    replay()
                except StructuredOutputError:
                    pass
                else:
                    raise AssertionError("Synthetic provider rejection was accepted")
                assert http.call_count == 1
                latest = json.loads(
                    Path(".vita/logs/traces/latest.json").read_text(encoding="utf-8")
                )
                trace = Path(".vita/logs/traces") / latest["trace_id"]
                local = trace / "journal" / latest["process_id"]
                configuration = (local / "configuration.json").read_text(encoding="utf-8")
                assert (
                    "configured-gemini" in configuration
                    and "built_in_extraction_default" in configuration
                )
                assert (
                    next(local.rglob("system-prompt.txt")).read_text(encoding="utf-8")
                    == "PRIVATE_SYSTEM_CANARY"
                )
                assert "Specific synthetic provider failure" in next(
                    local.rglob("provider-error-body.txt")
                ).read_text(encoding="utf-8")
                assert "_post" in "\n".join(
                    path.read_text(encoding="utf-8") for path in local.rglob("exception-*.txt")
                )
                assert "fixture-private-api-secret" not in "\n".join(
                    path.read_text(encoding="utf-8") for path in trace.rglob("*") if path.is_file()
                )
                d.export_trace(latest["trace_id"], Path("support.zip"))
                with zipfile.ZipFile("support.zip") as archive:
                    assert b"PRIVATE_SYSTEM_CANARY" not in archive.read("diagnostics.json")
        finally:
            os.chdir(previous)
    print("Installed developer journal replay passed")


if __name__ == "__main__":
    main()
