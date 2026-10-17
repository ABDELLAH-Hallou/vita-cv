"""Release approval, provenance, immutable artifacts, and retry behavior."""

import base64
import copy
import hashlib
import io
import json
import subprocess
import sys
import urllib.error
from unittest.mock import Mock

import pytest

from scripts import release_promotion as promotion
from vita import __version__

REPO = "owner/vita-cv"


@pytest.fixture
def candidate(tmp_path):
    dist = tmp_path / "built"
    dist.mkdir()
    for name in promotion.filenames(__version__):
        (dist / name).write_bytes(name.encode())
    return promotion.make_record(dist, f"v{__version__}", "a" * 40, 123, 1)


def index_data(candidate):
    return {"info": {"version": candidate["version"]}, "urls": [
        {"filename": name, "digests": {"sha256": digest}, "yanked": False,
         "url": f"https://test-files.pythonhosted.org/packages/{name}"}
        for name, digest in candidate["files"].items()
    ]}


def approved_pull(candidate):
    return {"merged": True, "merge_commit_sha": "b" * 40,
            "head": {"ref": f"release/pypi-{candidate['tag']}", "repo": {"full_name": REPO}},
            "base": {"ref": "master", "repo": {"full_name": REPO}}}


def source_run(candidate):
    return {"id": 123, "run_attempt": 1, "repository": {"full_name": REPO},
            "path": ".github/workflows/release.yml", "event": "push",
            "head_sha": candidate["source_sha"], "status": "completed", "conclusion": "success"}


def changes(candidate):
    return [{"filename": promotion.record_path(candidate["tag"]), "status": "added"}]


@pytest.mark.parametrize("field,value", [
    ("version", "9.9.9"), ("tag", "v2.4.0rc1"), ("source_sha", "master"),
    ("testpypi_run_id", True), ("testpypi_run_attempt", 0), ("schema_version", 2),
    ("files", {"../../unsafe.whl": "a" * 64}),
])
def test_invalid_records_are_rejected(candidate, field, value):
    candidate[field] = value
    with pytest.raises(ValueError):
        promotion.validate_record(candidate)


def test_approval_requires_merge_same_repo_and_exact_branch(candidate):
    promotion.validate_approval(candidate, approved_pull(candidate), changes(candidate), REPO)
    mutations = [("merged", False), ("head.ref", "some-feature"),
                 ("head.repo.full_name", "fork/vita-cv"), ("base.ref", "dev")]
    for field, value in mutations:
        pull = approved_pull(candidate)
        target = pull
        parts = field.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
        with pytest.raises(ValueError, match="merged same-repository"):
            promotion.validate_approval(candidate, pull, changes(candidate), REPO)


@pytest.mark.parametrize("files", [[], [{"filename": "README.md", "status": "added"}]])
def test_promotion_cannot_change_unrelated_files(candidate, files):
    with pytest.raises(ValueError, match="only add"):
        promotion.validate_approval(candidate, approved_pull(candidate), files, REPO)


def test_existing_approval_cannot_be_modified(candidate):
    files = changes(candidate)
    files[0]["status"] = "modified"
    with pytest.raises(ValueError, match="only add"):
        promotion.validate_approval(candidate, approved_pull(candidate), files, REPO)


@pytest.mark.parametrize("field,value", [
    ("conclusion", "failure"), ("status", "in_progress"), ("head_sha", "b" * 40),
    ("event", "pull_request"), ("path", ".github/workflows/ci.yml"), ("run_attempt", 2),
    ("repository", {"full_name": "fork/vita-cv"}),
])
def test_promotion_requires_successful_matching_testpypi_attempt(candidate, field, value):
    run = source_run(candidate)
    promotion.validate_source_run(candidate, run, REPO)
    run[field] = value
    with pytest.raises(ValueError, match="must have succeeded"):
        promotion.validate_source_run(candidate, run, REPO)


@pytest.mark.parametrize("change", ["hash", "yanked", "unexpected", "duplicate"])
def test_index_mismatch_is_rejected(candidate, change):
    data = index_data(candidate)
    if change == "hash":
        data["urls"][0]["digests"]["sha256"] = "0" * 64
    elif change == "yanked":
        data["urls"][0]["yanked"] = True
    elif change == "unexpected":
        data["urls"][0]["filename"] = "other-package.whl"
    else:
        data["urls"].append(copy.deepcopy(data["urls"][0]))
    with pytest.raises(ValueError):
        promotion.verify_index_files(candidate, data)


def test_partial_upload_is_only_allowed_for_safe_production_retry(candidate):
    data = index_data(candidate)
    data["urls"].pop()
    with pytest.raises(LookupError):
        promotion.verify_index_files(candidate, data)
    assert len(promotion.verify_index_files(candidate, data, allow_partial=True)) == 1


def test_downloads_identical_bytes_without_building(candidate, tmp_path, monkeypatch):
    monkeypatch.setattr(promotion, "metadata", lambda *args: index_data(candidate))

    def download(url, timeout):
        stream = io.BytesIO(url.rsplit("/", 1)[1].encode())
        stream.url = url
        return stream

    monkeypatch.setattr(promotion.urllib.request, "urlopen", download)
    destination = tmp_path / "promoted"
    promotion.download_verified(candidate, destination)
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in destination.iterdir()} == candidate["files"]


@pytest.mark.parametrize("bad_host", [False, True])
def test_download_rejects_wrong_bytes_or_external_host(candidate, tmp_path, monkeypatch, bad_host):
    data = index_data(candidate)
    if bad_host:
        data["urls"][0]["url"] = "https://attacker.invalid/payload.whl"
    monkeypatch.setattr(promotion, "metadata", lambda *args: data)
    stream = io.BytesIO(b"different bytes")
    stream.url = data["urls"][0]["url"]
    fetch = Mock(return_value=stream)
    monkeypatch.setattr(promotion.urllib.request, "urlopen", fetch)
    with pytest.raises(ValueError, match="download host|SHA-256"):
        promotion.download_verified(candidate, tmp_path / "download")
    if bad_host:
        fetch.assert_not_called()


def test_index_propagation_is_retried(candidate, tmp_path, monkeypatch):
    metadata = Mock(side_effect=[LookupError("not visible yet"), index_data(candidate)])
    monkeypatch.setattr(promotion, "metadata", metadata)
    sleep = Mock()
    monkeypatch.setattr(promotion.time, "sleep", sleep)

    def fetch(url, timeout):
        stream = io.BytesIO(url.rsplit("/", 1)[1].encode())
        stream.url = url
        return stream

    monkeypatch.setattr(promotion.urllib.request, "urlopen", fetch)
    promotion.download_verified(candidate, tmp_path / "download")
    sleep.assert_called_once_with(15)


def test_open_promotion_is_idempotent_and_retries_only_provenance(candidate, monkeypatch):
    state = {"record": None, "pull": None, "writes": []}

    def api(endpoint, data=None, **kwargs):
        if data is not None:
            state["writes"].append((endpoint, data, kwargs))
            if endpoint.endswith("/git/trees"):
                state["record"] = json.loads(data["tree"][0]["content"])
                assert data["tree"][0]["path"] == promotion.record_path(candidate["tag"])
                return {"sha": "tree"}
            if endpoint.endswith("/git/commits"):
                return {"sha": "new-head"}
            if endpoint.endswith("/pulls"):
                state["pull"] = {"html_url": "https://github.com/owner/vita-cv/pull/1", "state": "open"}
                return state["pull"]
            return {}
        if "/pulls?" in endpoint:
            return [state["pull"]] if state["pull"] else []
        if "/contents/" in endpoint:
            return {"content": base64.b64encode(json.dumps(state["record"]).encode()).decode()}
        if "/git/commits/" in endpoint:
            return {"tree": {"sha": "base-tree"}}
        if endpoint.endswith("/master") or state["record"] is not None:
            return {"object": {"sha": "base"}}
        return None

    monkeypatch.setattr(promotion, "github", api)
    first = promotion.open_promotion(candidate, REPO)
    writes = len(state["writes"])
    assert promotion.open_promotion(candidate, REPO) == first
    assert len(state["writes"]) == writes
    candidate["testpypi_run_attempt"] = 2
    assert promotion.open_promotion(candidate, REPO) == first
    assert state["record"]["testpypi_run_attempt"] == 2
    assert state["writes"][-1][2] == {"method": "PATCH"}
    assert state["writes"][-1][1]["force"] is False
    candidate["files"][next(iter(candidate["files"]))] = "0" * 64
    with pytest.raises(ValueError, match="different release bytes"):
        promotion.open_promotion(candidate, REPO)
    state["pull"]["state"] = "closed"
    writes = len(state["writes"])
    assert promotion.open_promotion(candidate, REPO) == first
    assert len(state["writes"]) == writes


def test_prepare_uses_approved_commit_not_current_package_version(candidate, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    event = {"inputs": {"promotion_pr": "1"}}
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", candidate["tag"])
    monkeypatch.setenv("GITHUB_SHA", candidate["source_sha"])
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def api(endpoint):
        if "/attempts/" in endpoint:
            return source_run(candidate)
        if "/files?" in endpoint:
            return changes(candidate)
        return approved_pull(candidate)

    def git(*args):
        if args[0] == "show":
            assert args[1].startswith("b" * 40 + ":")
            return json.dumps(candidate)
        if args[0] == "rev-parse":
            return candidate["source_sha"]
        assert args == ("merge-base", "--is-ancestor", "a" * 40, "b" * 40)
        return ""

    monkeypatch.setattr(promotion, "github", api)
    monkeypatch.setattr(promotion, "git", git)
    download = Mock()
    monkeypatch.setattr(promotion, "download_verified", download)
    monkeypatch.setattr(promotion, "check_existing_pypi", Mock())
    promotion.prepare(tmp_path / "dist", REPO)
    download.assert_called_once_with(candidate, tmp_path / "dist")
    assert output.read_text(encoding="utf-8") == f"tag={candidate['tag']}\n"
    assert json.loads((tmp_path / "promotion-record.json").read_text(encoding="utf-8")) == candidate


def test_github_missing_branch_is_not_an_authentication_failure(monkeypatch):
    result = subprocess.CompletedProcess([], 1, '{"status":"404"}', "not found")
    monkeypatch.setattr(promotion.subprocess, "run", Mock(return_value=result))
    assert promotion.github("some/ref", missing_ok=True) is None
    result.stdout = '{"status":"403"}'
    with pytest.raises(RuntimeError):
        promotion.github("some/ref", missing_ok=True)


def test_existing_production_release_requires_matching_bytes(candidate, monkeypatch):
    absent = urllib.error.HTTPError("url", 404, "missing", {}, None)
    monkeypatch.setattr(promotion, "metadata", Mock(side_effect=absent))
    promotion.check_existing_pypi(candidate)
    data = index_data(candidate)
    monkeypatch.setattr(promotion, "metadata", Mock(return_value=data))
    promotion.check_existing_pypi(candidate)
    data["urls"][0]["digests"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        promotion.check_existing_pypi(candidate)


def test_propose_verifies_uploaded_bytes_before_creating_pr(candidate, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GH_TOKEN", "test-token")
    for key, value in {"GITHUB_REF_NAME": candidate["tag"], "GITHUB_SHA": candidate["source_sha"],
                       "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["release_promotion", "propose", "--dist", "built"])
    events = []
    monkeypatch.setattr(promotion, "download_verified", lambda *args: events.append("verify"))
    monkeypatch.setattr(promotion, "publish_test_prerelease", lambda *args: events.append("prerelease"))
    monkeypatch.setattr(promotion, "open_promotion", lambda *args: events.append("create") or "url")
    promotion.main()
    assert events == ["verify", "prerelease", "create"]
    monkeypatch.setattr(promotion, "download_verified", Mock(side_effect=ValueError("wrong bytes")))
    events.clear()
    with pytest.raises(ValueError):
        promotion.main()
    assert events == []


@pytest.mark.parametrize("verified", [True, False])
def test_github_release_stays_prerelease_until_pypi_verification(candidate, tmp_path, monkeypatch, verified):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("RELEASE_TAG", candidate["tag"])
    monkeypatch.setenv("GITHUB_SHA", candidate["source_sha"])
    monkeypatch.setattr(sys, "argv", ["release_promotion", "finalize"])
    path = tmp_path / "promotion-record.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    download = Mock(side_effect=None if verified else ValueError("mismatch"))
    monkeypatch.setattr(promotion, "download_verified", download)
    monkeypatch.setattr(promotion, "github", Mock(return_value={"id": 42}))
    patch = Mock()
    monkeypatch.setattr(promotion.subprocess, "run", patch)
    if verified:
        promotion.main()
        assert "prerelease=false" in patch.call_args.args[0]
        assert "make_latest=legacy" in patch.call_args.args[0]
        assert download.call_args.args[-1] == "pypi"
    else:
        with pytest.raises(ValueError):
            promotion.main()
        patch.assert_not_called()


def test_dispatch_uses_tag_and_requires_matching_merge_event(candidate, tmp_path, monkeypatch):
    event = {"number": 1, "action": "closed", "pull_request": approved_pull(candidate)}
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setattr(promotion, "read_event", lambda: event)
    monkeypatch.setattr(promotion, "approved_record", lambda *args: (candidate, approved_pull(candidate)))
    api = Mock()
    monkeypatch.setattr(promotion, "github", api)
    promotion.dispatch(REPO)
    api.assert_called_once_with(f"repos/{REPO}/actions/workflows/promote-pypi.yml/dispatches", {
        "ref": candidate["tag"], "inputs": {"promotion_pr": "1"},
    })
    api.reset_mock()
    event["pull_request"]["merge_commit_sha"] = "c" * 40
    with pytest.raises(ValueError, match="merge commit changed"):
        promotion.dispatch(REPO)
    api.assert_not_called()


def test_manual_dispatch_cannot_publish_an_unmerged_pr(candidate, monkeypatch):
    pull = approved_pull(candidate)
    pull["merged"] = False
    monkeypatch.setattr(promotion, "github", Mock(return_value=pull))
    read_git = Mock()
    monkeypatch.setattr(promotion, "git", read_git)
    with pytest.raises(ValueError, match="must be merged"):
        promotion.approved_record(REPO, 1)
    read_git.assert_not_called()


def test_production_cannot_run_from_master(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    download = Mock()
    monkeypatch.setattr(promotion, "download_verified", download)
    with pytest.raises(ValueError, match="version tag"):
        promotion.prepare(tmp_path / "dist", REPO)
    download.assert_not_called()


def test_github_accepts_empty_dispatch_response(monkeypatch):
    result = subprocess.CompletedProcess([], 0, "", "")
    call = Mock(return_value=result)
    monkeypatch.setattr(promotion.subprocess, "run", call)
    assert promotion.github("workflow/dispatches", {"ref": "v2.4.0"}) is None
    assert json.loads(call.call_args.kwargs["input"]) == {"ref": "v2.4.0"}


@pytest.mark.parametrize("draft", [True, False])
def test_publish_prerelease_never_demotes_existing_stable_release(monkeypatch, draft):
    call = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps({"isDraft": draft}), ""))
    monkeypatch.setattr(promotion.subprocess, "run", call)
    promotion.publish_test_prerelease("v2.4.0", REPO)
    assert call.call_count == (2 if draft else 1)
    if draft:
        assert "--draft=false" in call.call_args.args[0]
        assert "--prerelease" in call.call_args.args[0]
