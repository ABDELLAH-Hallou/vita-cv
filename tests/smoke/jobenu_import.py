"""Exercise the installed Jobenu CLI with a synthetic export and no providers."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def check():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        environment = {**os.environ, "PYTHONUTF8": "1"}

        def command(*args):
            return subprocess.run(args, cwd=root, env=environment, capture_output=True,
                                  text=True, encoding="utf-8", check=True).stdout

        command("git", "init", "-b", "master")
        command("git", "config", "user.name", "Synthetic Import Smoke")
        command("git", "config", "user.email", "smoke@example.invalid")
        command("git", "config", "commit.gpgsign", "false")
        command("git", "config", "core.hooksPath", str(root / ".git/hooks"))
        command(sys.executable, "-m", "vita", "init")
        (root / "main.tex").write_text("Synthetic unchanged CV", encoding="utf-8")
        command("git", "add", "main.tex")
        command("git", "commit", "-m", "Synthetic base")
        source = root / "export.json"
        source.write_text(json.dumps({"exportedAt": "2026-10-31", "applications": [{
            "id": "synthetic-1", "company": "Acme", "position": "Machine Learning Engineer",
            "description": "Python experience; original wording preserved.", "status": "SAVED",
        }]}), encoding="utf-8")
        args = [sys.executable, "-m", "vita", "import", "jobenu", str(source), "--json"]
        preview = json.loads(command(*args, "--dry-run"))
        assert preview["entries"][0]["branch"] == "etp-acme-ml"
        imported = json.loads(command(*args, "--approval", "auto"))
        entry = imported["results"][0]
        workspace = Path(entry["workspace"])
        assert (workspace / "main.tex").read_text() == "Synthetic unchanged CV"
        assert "Python experience" in (workspace / "job.md").read_text()
        repeated = json.loads(command(*args, "--approval", "auto"))
        assert repeated["results"][0]["workspace"] == str(workspace)
        assert command("git", "branch", "--show-current").strip() == "master"


if __name__ == "__main__":
    check()
    print("Installed Jobenu preview, import and idempotent reuse passed; no providers called")
