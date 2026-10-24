"""Exercise installed public ingestion CLI, with synthetic review-gate decisions."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def check():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "synthetic.docx"
        text = "Ingénieure — Sen 2017; TTR; 40%; 250 ms; diplôme en cours."
        with zipfile.ZipFile(source, "w") as package:
            package.writestr("[Content_Types].xml", "<Types/>")
            package.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
        original = source.read_bytes()
        (root / "main.tex").write_text("Existing direct LaTeX", encoding="utf-8")

        def cli(*args, expected=0):
            result = subprocess.run([sys.executable, "-m", "vita", "ingest", *args, "--json"],
                                    cwd=root, env={**os.environ, "PYTHONUTF8": "1"},
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            assert result.returncode == expected, result.stdout + result.stderr
            return json.loads(result.stdout)

        captured = cli("capture", str(source))
        assert captured["sha256"] == hashlib.sha256(original).hexdigest()
        extracted = cli("extract", captured["id"])
        assert extracted["paragraphs"][0]["text"] == text
        assert extracted["stages"]["review"] == "not_started"
        plan = ".vita/ingestion/review.json"
        form = cli("review", extracted["revision"], "--output", plan)
        assert cli("approve", extracted["revision"], "--review", plan, expected=1)["status"] == "blocked"
        form.update(reviewer="SYNTHETIC-SOFTWARE-TEST-NOT-HUMAN-REVIEW", original_viewed=True, reading_order_checked=True)
        for paragraph in form["paragraphs"]:
            paragraph.update(source_checked=True, decision="keep", approved_text=text,
                             association="preserve_unassigned", rationale="Software gate fixture; preserve unresolved source wording.")
        (root / plan).write_text(json.dumps(form, ensure_ascii=False), encoding="utf-8")
        approved = cli("approve", extracted["revision"], "--review", plan)
        exported = cli("latex", approved["revision"], "--output", "imported.tex", "--language", "fr")
        assert exported["stages"]["latex"] == "generated" and exported["stages"]["compile"] == "not_run"
        assert r"40\%" in (root / "imported.tex").read_text(encoding="utf-8")
        assert (root / "main.tex").read_text(encoding="utf-8") == "Existing direct LaTeX"
        assert source.read_bytes() == original
        assert cli("show", exported["revision"], "--kind", "exports")["generated_file_status"] == "unchanged"


if __name__ == "__main__":
    check()
    print("Installed ingestion CLI and review gate passed; human review was not performed")
