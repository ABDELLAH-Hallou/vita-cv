"""Create and verify a human-approved promotion of exact TestPyPI distributions.

Uses the GitHub CLI for authenticated API requests and the public PyPI JSON API
for artifacts. There is deliberately no package build or upload in this script.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from vita.helpers.release import validate_release_tag

RECORD_DIR = ".github/releases/pypi"
INDEX_HOSTS = {"testpypi": "test.pypi.org", "pypi": "pypi.org"}
FILE_HOSTS = {"testpypi": "test-files.pythonhosted.org", "pypi": "files.pythonhosted.org"}


def github(endpoint: str, data: dict | None = None, *, missing_ok=False, method="POST"):
    command = ["gh", "api", endpoint]
    if data is not None:
        command += ["--method", method, "--input", "-"]
    result = subprocess.run(command, input=json.dumps(data) if data is not None else None,
                            text=True, capture_output=True, encoding="utf-8")
    if result.returncode:
        if missing_ok:
            try:
                status = json.loads(result.stdout).get("status")
            except (ValueError, AttributeError):
                status = None
            if str(status) == "404":
                return None
        raise RuntimeError(f"GitHub API request failed: {endpoint}: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def record_path(tag: str) -> str:
    validate_release_tag(tag, tag.removeprefix("v"))
    return f"{RECORD_DIR}/{tag}.json"


def filenames(version: str) -> set[str]:
    return {f"vita_cv-{version}-py3-none-any.whl", f"vita_cv-{version}.tar.gz"}


def validate_record(record: dict) -> None:
    fields = {"schema_version", "version", "tag", "source_sha", "testpypi_run_id",
              "testpypi_run_attempt", "files"}
    if not isinstance(record, dict) or set(record) != fields or type(record["schema_version"]) is not int:
        raise ValueError("Invalid promotion record fields")
    if record["schema_version"] != 1:
        raise ValueError("Unsupported promotion record version")
    if not isinstance(record["tag"], str) or not isinstance(record["version"], str):
        raise ValueError("Invalid release version")
    validate_release_tag(record["tag"], record["version"])
    if not isinstance(record["source_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", record["source_sha"]):
        raise ValueError("Invalid source commit")
    for field in ("testpypi_run_id", "testpypi_run_attempt"):
        if type(record[field]) is not int or record[field] < 1:
            raise ValueError(f"Invalid {field}")
    if not isinstance(record["files"], dict) or set(record["files"]) != filenames(record["version"]):
        raise ValueError("Expected exactly the release wheel and source distribution")
    if any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
           for digest in record["files"].values()):
        raise ValueError("Invalid artifact SHA-256 digest")


def make_record(dist: Path, tag: str, sha: str, run_id: int, attempt: int) -> dict:
    validate_release_tag(tag)
    version = tag.removeprefix("v")
    if {path.name for path in dist.iterdir()} != filenames(version):
        raise ValueError("Build output must contain exactly the release wheel and sdist")
    record = {
        "schema_version": 1, "version": version, "tag": tag, "source_sha": sha,
        "testpypi_run_id": run_id, "testpypi_run_attempt": attempt,
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(dist.iterdir())},
    }
    validate_record(record)
    return record


def metadata(version: str, index: str) -> dict:
    url = f"https://{INDEX_HOSTS[index]}/pypi/vita-cv/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def verify_index_files(record: dict, data: dict, *, allow_partial=False) -> dict:
    if data["info"]["version"] != record["version"]:
        raise ValueError("Index returned a different release version")
    entries = data["urls"]
    files = {entry["filename"]: entry for entry in entries}
    expected = record["files"]
    if len(files) != len(entries) or set(files) - set(expected):
        raise ValueError("Index contains unexpected or duplicate distributions")
    if not allow_partial and set(files) != set(expected):
        raise LookupError("The complete release is not yet visible on the index")
    for name, entry in files.items():
        if entry.get("yanked") or entry["digests"]["sha256"] != expected[name]:
            raise ValueError(f"Index artifact differs from the approved build: {name}")
    return files


def download_verified(record: dict, destination: Path, index="testpypi") -> None:
    validate_record(record)
    files = None
    for attempt in range(10):
        try:
            files = verify_index_files(record, metadata(record["version"], index))
            break
        except (urllib.error.URLError, LookupError):
            if attempt == 9:
                raise
            time.sleep(15)
    if files is None:
        raise RuntimeError("The release could not be verified on the index")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Download destination must be empty")
    for name, entry in files.items():
        url = entry["url"]
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != FILE_HOSTS[index]:
            raise ValueError("Unexpected package download host")
        with urllib.request.urlopen(url, timeout=60) as response:
            if urllib.parse.urlsplit(response.url).netloc != FILE_HOSTS[index]:
                raise ValueError("Unexpected package download redirect")
            content = response.read()
        if hashlib.sha256(content).hexdigest() != record["files"][name]:
            raise ValueError(f"Downloaded bytes failed SHA-256 verification: {name}")
        (destination / name).write_bytes(content)


def check_existing_pypi(record: dict) -> None:
    # Partial uploads can be retried, but skip-existing must never hide a mismatch.
    try:
        data = metadata(record["version"], "pypi")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return
        raise
    verify_index_files(record, data, allow_partial=True)


def promotion_body(record: dict, repo: str) -> str:
    version = record["version"]
    rows = "\n".join(f"| `{name}` | `{digest}` |" for name, digest in record["files"].items())
    return (
        f"Promote **vita-cv {version}** from TestPyPI to PyPI.\n\n"
        "**Merge this PR only after you have tested the TestPyPI package.** "
        "Merging publishes the exact files listed below, without rebuilding. "
        "Leaving this PR open or closing it without merging does not publish to PyPI.\n\n"
        f"[TestPyPI package](https://test.pypi.org/project/vita-cv/{version}/) · "
        f"[TestPyPI workflow](https://github.com/{repo}/actions/runs/{record['testpypi_run_id']})\n\n"
        "Install in a disposable virtual environment:\n\n```sh\n"
        f"python -m pip install --no-cache-dir --no-deps --index-url https://test.pypi.org/simple/ vita-cv=={version}\n"
        "vita --version\n```\n\n"
        f"Source: `{record['source_sha']}` ({record['tag']}).\n\n"
        f"| Distribution | SHA-256 |\n|---|---|\n{rows}\n"
    )


def publish_test_prerelease(tag: str, repo: str) -> None:
    result = subprocess.run(["gh", "release", "view", tag, "--repo", repo, "--json", "isDraft"],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    if json.loads(result.stdout)["isDraft"]:
        subprocess.run(["gh", "release", "edit", tag, "--repo", repo, "--draft=false",
                        "--prerelease", "--latest=false"], check=True)
    # A retry after production promotion must not demote a stable release.


def open_promotion(record: dict, repo: str) -> str:
    validate_record(record)
    root = f"repos/{repo}"
    branch = f"release/pypi-{record['tag']}"
    path = record_path(record["tag"])
    owner = repo.split("/")[0]
    pulls = github(f"{root}/pulls?state=all&head={owner}:{branch}&base=master")
    if pulls and pulls[0]["state"] == "closed":
        # Never reopen a deliberately rejected promotion or duplicate an approved one.
        return pulls[0]["html_url"]
    existing = github(f"{root}/git/ref/heads/{branch}", missing_ok=True)
    saved = None
    if existing:
        content = github(f"{root}/contents/{path}?ref={branch}")
        saved = json.loads(base64.b64decode(content["content"]))
        validate_record(saved)
        immutable = ("schema_version", "version", "tag", "source_sha", "files")
        if any(saved[key] != record[key] for key in immutable):
            raise ValueError("Existing promotion branch records different release bytes")
    if saved != record:
        # Retried runs may replace only provenance, never the approved package bytes.
        base = (existing or github(f"{root}/git/ref/heads/master"))["object"]["sha"]
        commit = github(f"{root}/git/commits/{base}")
        tree = github(f"{root}/git/trees", {
            "base_tree": commit["tree"]["sha"],
            "tree": [{"path": path, "mode": "100644", "type": "blob",
                      "content": json.dumps(record, indent=2) + "\n"}],
        })
        created = github(f"{root}/git/commits", {
            "message": f"chore(pypi): release {record['version']}",
            "tree": tree["sha"], "parents": [base],
        })
        if existing:
            github(f"{root}/git/refs/heads/{branch}", {"sha": created["sha"], "force": False}, method="PATCH")
        else:
            github(f"{root}/git/refs", {"ref": f"refs/heads/{branch}", "sha": created["sha"]})
    if pulls:
        return pulls[0]["html_url"]
    pull = github(f"{root}/pulls", {
        "title": f"chore(pypi): release {record['version']}", "head": branch,
        "base": "master", "body": promotion_body(record, repo),
    })
    return pull["html_url"]


def validate_approval(record: dict, pull: dict, changed_files: list, repo: str) -> None:
    validate_record(record)
    if (pull.get("merged") is not True or pull["base"]["ref"] != "master"
            or pull["base"]["repo"]["full_name"] != repo
            or pull["head"]["repo"]["full_name"] != repo
            or pull["head"]["ref"] != f"release/pypi-{record['tag']}"):
        raise ValueError("PyPI publishing requires a merged same-repository promotion PR")
    if len(changed_files) != 1 or changed_files[0]["filename"] != record_path(record["tag"]) \
            or changed_files[0]["status"] != "added":
        raise ValueError("A promotion PR must only add its versioned approval record")


def validate_source_run(record: dict, run: dict, repo: str) -> None:
    if (run["id"] != record["testpypi_run_id"]
            or run["run_attempt"] != record["testpypi_run_attempt"]
            or run["repository"]["full_name"] != repo
            or run["path"] != ".github/workflows/release.yml"
            or run["event"] != "push" or run["head_sha"] != record["source_sha"]
            or run["status"] != "completed" or run["conclusion"] != "success"):
        raise ValueError("The recorded TestPyPI workflow attempt must have succeeded for this source")


def approved_record(repo: str, number: int) -> tuple[dict, dict]:
    if type(number) is not int or number < 1:
        raise ValueError("Invalid promotion PR number")
    pull = github(f"repos/{repo}/pulls/{number}")
    if pull.get("merged") is not True or not re.fullmatch(r"[0-9a-f]{40}", pull.get("merge_commit_sha") or ""):
        raise ValueError("Promotion PR must be merged before production publishing")
    branch = pull["head"]["ref"]
    tag = branch.removeprefix("release/pypi-")
    path = record_path(tag)
    raw = git("show", f"{pull['merge_commit_sha']}:{path}")
    record = json.loads(raw)
    changes = github(f"repos/{repo}/pulls/{number}/files?per_page=100")
    validate_approval(record, pull, changes, repo)
    return record, pull


def read_event() -> dict:
    return json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))


def dispatch(repo: str) -> None:
    event = read_event()
    if os.environ["GITHUB_EVENT_NAME"] != "pull_request" or event["action"] != "closed":
        raise ValueError("Dispatch requires a merged-PR event")
    record, pull = approved_record(repo, event["number"])
    if pull["merge_commit_sha"] != event["pull_request"]["merge_commit_sha"]:
        raise ValueError("Promotion merge commit changed")
    github(f"repos/{repo}/actions/workflows/promote-pypi.yml/dispatches", {
        "ref": record["tag"], "inputs": {"promotion_pr": str(event["number"])},
    })


def prepare(dist: Path, repo: str) -> None:
    if os.environ["GITHUB_EVENT_NAME"] != "workflow_dispatch" or os.environ["GITHUB_REF_TYPE"] != "tag":
        raise ValueError("Production publishing must run on the tested version tag")
    record, pull = approved_record(repo, int(read_event()["inputs"]["promotion_pr"]))
    tag = record["tag"]
    if os.environ["GITHUB_REF_NAME"] != tag or os.environ["GITHUB_SHA"] != record["source_sha"]:
        raise ValueError("Publishing ref does not match the approved version tag")
    run = github(f"repos/{repo}/actions/runs/{record['testpypi_run_id']}/attempts/{record['testpypi_run_attempt']}")
    validate_source_run(record, run, repo)
    if git("rev-parse", f"refs/tags/{tag}^{{commit}}") != record["source_sha"]:
        raise ValueError("Release tag no longer matches the tested commit")
    git("merge-base", "--is-ancestor", record["source_sha"], pull["merge_commit_sha"])
    download_verified(record, dist)
    check_existing_pypi(record)
    Path("promotion-record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"tag={record['tag']}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("propose", "dispatch", "prepare", "finalize"))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    repo = os.environ["GITHUB_REPOSITORY"]
    if args.command == "propose":
        if not os.environ.get("GH_TOKEN"):
            raise ValueError("RELEASE_PLEASE_TOKEN is required to open the promotion PR")
        record = make_record(args.dist, os.environ["GITHUB_REF_NAME"], os.environ["GITHUB_SHA"],
                             int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"]))
        download_verified(record, Path("verified-testpypi"))
        publish_test_prerelease(record["tag"], repo)
        print(open_promotion(record, repo))
    elif args.command == "dispatch":
        dispatch(repo)
    elif args.command == "prepare":
        prepare(args.dist, repo)
    else:
        tag = os.environ["RELEASE_TAG"]
        record = json.loads(Path("promotion-record.json").read_text(encoding="utf-8"))
        validate_record(record)
        if record["tag"] != tag or record["source_sha"] != os.environ["GITHUB_SHA"]:
            raise ValueError("Finalization must refer to the approved release")
        download_verified(record, Path("verified-pypi"), "pypi")
        release = github(f"repos/{repo}/releases/tags/{tag}")
        subprocess.run(["gh", "api", "--method", "PATCH", f"repos/{repo}/releases/{release['id']}",
                        "-F", "prerelease=false", "-f", "make_latest=legacy"], check=True)


if __name__ == "__main__":
    main()
