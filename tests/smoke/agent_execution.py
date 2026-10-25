"""Installed restricted adapter, with mocked process and no provider requests."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from vita.helpers import llm


def check():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as temporary:
        try:
            os.chdir(temporary)
            Path(".vita").mkdir()
            Path(".vita/extensions.json").write_text(json.dumps({"llm_providers":{"codex":{
                "model":"synthetic/exact-model", "reasoning_effort":"high", "execution_mode":"restricted"}}}))
            def process(cmd, **kwargs):
                assert "--ephemeral" in cmd and "--json" in cmd and '--model' in cmd
                assert 'model_reasoning_effort="high"' in cmd
                Path(cmd[cmd.index("--output-last-message") + 1]).write_text("FINAL")
                return subprocess.CompletedProcess(cmd, 0, '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}', "")
            capabilities = {"flags":["--config","features.shell_tool=false"], "cli_version":"codex-cli fixture", "mcp_servers_disabled":0,
                            "restrictions":["synthetic_preflight_mock"], "capability_processes":0, "capability_check_seconds":0}
            session = {}
            with patch.dict(os.environ, {"VITA_AGENT_EXECUTION":"restricted"}), patch.object(llm,"_find_codex_cli",lambda:"synthetic-codex"), \
                    patch("vita.helpers.agent_execution.preflight", return_value=capabilities), patch.object(subprocess,"run",side_effect=process):
                assert llm.generate("system","complete task",provider="codex",session=session) == "FINAL"
            assert session["route"]["model"] == "synthetic/exact-model"
            assert session["agent_telemetry"]["model_calls"] is None
            assert session["agent_telemetry"]["usage"]["input_tokens"] == 12
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    check()
    print("Installed restricted agent transport passed (synthetic only)")
