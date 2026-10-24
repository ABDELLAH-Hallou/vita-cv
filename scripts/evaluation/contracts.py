"""Versioned, local-only dataset contracts and verifiable text anchors."""

import hashlib
import itertools
import json
import math
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

VERSION = 1
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
SPLITS = ("development", "holdout")
CONTROLS = ("primary", "unchanged_analyze", "unchanged_review", "mismatched_role")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite JSON number: " + value)

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=invalid)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), "Refusing to overwrite an existing artifact: " + str(path))
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def identifier(value):
    require(isinstance(value, str) and ID.fullmatch(value), "Expected a simple pseudonymous identifier")
    return value


def text(value):
    require(isinstance(value, str) and bool(value.strip()), "Expected nonempty text")


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "Timestamps must include a timezone")
    return result


def local_file(root, relative, sha=None):
    require(isinstance(relative, str) and not Path(relative).is_absolute(), "Asset paths must be relative")
    path = (Path(root) / relative).resolve()
    require(path.is_relative_to(Path(root).resolve()) and path.is_file(), "Missing or escaping local asset")
    if sha is not None:
        require(isinstance(sha, str) and SHA.fullmatch(sha) and file_hash(path) == sha, "Stale asset hash: " + relative)
    return path


def protocol_check(protocol):
    reference = read(Path(__file__).with_name("protocol.json"))
    # Version 1 fixes definitions/statistics. Sampling quotas can be preregistered differently.
    for key in reference.keys() - {"status", "minimum_primary_per_cell", "minimum_holdout_per_challenge"}:
        require(protocol.get(key) == reference[key], "Unsupported protocol alteration: " + key)
    require(set(protocol) == set(reference), "Unexpected protocol fields")
    require(protocol["status"] in ("draft_requires_human_preregistration", "approved_by_custodian"), "Unknown protocol approval status")
    for split in SPLITS:
        require(type(protocol["minimum_primary_per_cell"][split]) is int and protocol["minimum_primary_per_cell"][split] >= 1, "Invalid sampling quota")
    require(type(protocol["minimum_holdout_per_challenge"]) is int and protocol["minimum_holdout_per_challenge"] >= 1, "Invalid challenge quota")


def dataset(study, protocol):
    cases, hashes, groups = [], {}, {}
    for split in SPLITS:
        manifest = read(study / split / "manifest.json")
        require(manifest.get("schema_version") == VERSION and isinstance(manifest.get("cases"), list), "Invalid split manifest")
        primary_candidates, primary_jobs = set(), set()
        for case in manifest["cases"]:
            identifier(case["id"])
            require(case["split"] == split and case["domain"] in protocol["domains"] and case["seniority"] in protocol["seniority"] and case["native_format"] in protocol["native_formats"], "Invalid case stratum")
            require(case["control"] in CONTROLS and case["origin"] in ("synthetic", "consented", "licensed"), "Invalid case control/origin")
            text(case["role"])
            text(case["language"])
            text(case["rights_reference"])
            require(case["rights_approved"] is True and case["contact_redaction_verified"] is True, "Rights/redaction review remains pending")
            require(isinstance(case["tasks"], list) and case["tasks"] and len(set(case["tasks"])) == len(case["tasks"]) and set(case["tasks"]) <= set(protocol["tasks"]), "Invalid task selection")
            require(set(case["challenges"]) <= set(protocol["challenge_tags"]), "Unknown challenge tag")
            for name in ("candidate_group", "job_group", "family_id"):
                identifier(case[name])
                key = (name, case[name])
                require(key not in groups or groups[key] == split, "Group leakage between development and holdout")
                groups[key] = split
            if case["control"] == "primary":
                require(case["tasks"] == protocol["tasks"], "Primary cases must cover all five stages in protocol order")
                require(case["candidate_group"] not in primary_candidates and case["job_group"] not in primary_jobs, "Primary sampling requires distinct candidate and job families; repeats belong in controls")
                primary_candidates.add(case["candidate_group"])
                primary_jobs.add(case["job_group"])
            assets = case["assets"]
            require(isinstance(assets, list) and assets, "Cases require captured assets")
            require(len({a["id"] for a in assets}) == len(assets), "Duplicate asset identities")
            require({a["role"] for a in assets} >= {"cv", "job"}, "CV and job text assets are required")
            require(sum(a["role"] == "cv" for a in assets) == sum(a["role"] == "job" for a in assets) == 1, "Use one canonical CV and one canonical JD text asset, plus includes/knowledge/native assets")
            for asset in assets:
                identifier(asset["id"])
                require(asset["role"] in ("cv", "job", "native", "included", "knowledge"), "Unknown asset role")
                path = local_file(study / split, asset["path"], asset["sha256"])
                require(type(asset["is_text"]) is bool, "Asset text flag must be boolean")
                if asset["role"] in ("cv", "job", "included", "knowledge"):
                    require(asset["is_text"], "Annotation sources require canonical UTF-8 text")
                if asset["is_text"]:
                    text(path.read_text(encoding="utf-8"))
                if asset.get("derived_from"):
                    require(asset["derived_from"] in {a["id"] for a in assets} and asset.get("conversion_verified") is True, "Native-format conversion requires source identity and human verification")
                if asset["role"] == "knowledge":
                    require(asset.get("verified") is True, "Knowledge-base evidence must be explicitly verified")
                    text(asset.get("verification_reference"))
                key = asset["sha256"]
                require(key not in hashes or hashes[key] == split, "Identical content leaked across splits")
                hashes[key] = split
            if case["native_format"] in ("pdf", "docx"):
                native = {a["id"] for a in assets if a["role"] == "native" and not a["is_text"]}
                require(native and any(a["role"] == "cv" and a.get("derived_from") in native for a in assets), "Native PDF/DOCX must retain the original and a verified text conversion")
                for asset in (a for a in assets if a["id"] in native):
                    path = local_file(study / split, asset["path"])
                    if case["native_format"] == "pdf":
                        require(path.read_bytes().startswith(b"%PDF-"), "Native PDF header is missing")
                    else:
                        require(zipfile.is_zipfile(path), "Native DOCX must be a ZIP document")
                        with zipfile.ZipFile(path) as archive:
                            require("word/document.xml" in archive.namelist(), "Native DOCX main document is missing")
            else:
                cv_path = next(a["path"] for a in assets if a["role"] == "cv")
                require(Path(cv_path).suffix.lower() in ((".tex",) if case["native_format"] == "latex" else (".md", ".markdown")), "Native text format does not match its source file")
            cases.append(case)
    by_id = {c["id"]: c for c in cases}
    require(len(by_id) == len(cases), "Duplicate case IDs across splits")
    for case in cases:
        if case["control"] == "primary":
            require(case["paired_case_id"] is None, "Primary cases cannot pair with themselves")
            continue
        parent = by_id.get(case["paired_case_id"])
        require(parent is not None and parent["control"] == "primary" and parent["split"] == case["split"] and parent["family_id"] == case["family_id"] and parent["candidate_group"] == case["candidate_group"], "Control must link to a primary in the same split and family")
        def cv(c):
            return sorted(a["sha256"] for a in c["assets"] if a["role"] in ("cv", "included", "knowledge", "native"))

        def jobs(c):
            return sorted(a["sha256"] for a in c["assets"] if a["role"] == "job")
        require(cv(case) == cv(parent), "Control changed candidate sources")
        if case["control"].startswith("unchanged_"):
            require(jobs(case) == jobs(parent) and case["domain"] == parent["domain"], "Unchanged control changed the job")
            require(case["tasks"] == (["analyze"] if case["control"] == "unchanged_analyze" else ["review"]), "Unchanged controls must select their declared stage")
        else:
            require(jobs(case) != jobs(parent) and case["domain"] != parent["domain"], "Mismatched role requires a different-domain job with the same CV")
            require({"analyze", "adapt", "cover"} <= set(case["tasks"]), "Mismatched-role controls must cover assessment and document proposals")
    return cases


def configuration_check(document, protocol):
    require(document.get("schema_version") == VERSION and isinstance(document.get("configurations"), list), "Invalid configurations")
    configs = document["configurations"]
    require(len({c["id"] for c in configs}) == len(configs), "Duplicate configuration IDs")
    for config in configs:
        require(set(config) == {"id", "provider", "model", "product_revision", "prompt_revision", "schema_revision", "as_of_date", "extraction_enabled", "reasoning_effort", "temperature"}, "Unknown configuration fields; do not include credentials")
        identifier(config["id"])
        for key in ("provider", "model", "product_revision", "prompt_revision", "schema_revision", "as_of_date"):
            text(config[key])
        identifier(config["provider"])
        require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,159}", config["model"])) and "://" not in config["model"], "Unsafe model identifier")
        require(bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", config["product_revision"])) and SHA.fullmatch(config["prompt_revision"]) and SHA.fullmatch(config["schema_revision"]), "Pin product, prompt and schema hashes rather than version guesses")
        date.fromisoformat(config["as_of_date"])
        require(type(config["extraction_enabled"]) is bool, "Explicit extraction setting required")
        require(config["reasoning_effort"] is None or isinstance(config["reasoning_effort"], str), "Explicit reasoning setting required")
        value = config["temperature"]
        require(value is None or type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 2, "Invalid temperature")
    return configs


def coverage(cases, protocol):
    cells, missing_controls = [], []
    for split, domain, seniority, native in itertools.product(SPLITS, protocol["domains"], protocol["seniority"], protocol["native_formats"]):
        selected = [c for c in cases if c["split"] == split and c["domain"] == domain and c["seniority"] == seniority and c["native_format"] == native and c["control"] == "primary"]
        cells.append({"split": split, "domain": domain, "seniority": seniority, "native_format": native,
                      "target": protocol["minimum_primary_per_cell"][split], "actual": len(selected)})
    for case in cases:
        if case["control"] == "primary":
            found = {c["control"] for c in cases if c["paired_case_id"] == case["id"]}
            missing_controls.extend({"case_id": case["id"], "control": control} for control in protocol["controls"] if control not in found)
    challenges = {tag: sum(tag in c["challenges"] for c in cases if c["split"] == "holdout" and c["control"] == "primary") for tag in protocol["challenge_tags"]}
    complete = all(c["actual"] >= c["target"] for c in cells if c["split"] == "holdout") and all(n >= protocol["minimum_holdout_per_challenge"] for n in challenges.values()) and not any(x for x in missing_controls if next(c for c in cases if c["id"] == x["case_id"])["split"] == "holdout")
    return {"status": "targets_met" if complete else "sampling_pending", "cells": cells,
            "holdout_challenges": challenges, "missing_controls": missing_controls}


def reference(study, case, observation, ref):
    require(isinstance(ref, dict), "Expected a source reference")
    if ref["document"] == "output":
        path = local_file(study, observation["artifact"]["path"], observation["artifact"]["sha256"])
    else:
        require(ref["document"].startswith("asset:"), "Unknown reference document")
        assets = {a["id"]: a for a in case["assets"]}
        asset = assets.get(ref["document"].removeprefix("asset:"))
        require(asset is not None and asset["is_text"], "Reference requires a captured text asset")
        path = local_file(study / case["split"], asset["path"], asset["sha256"])
    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = ref["line_start"], ref["line_end"]
    require(type(start) is int and type(end) is int and 1 <= start <= end <= len(lines), "Out-of-bounds source span")
    text(ref["quote"])
    require(ref["quote"] in "\n".join(lines[start - 1:end]), "Quotation does not match the captured span")


def prediction(study, observation, unit):
    path = local_file(study, observation["artifact"]["path"], observation["artifact"]["sha256"])
    value = read(path)
    pointer = unit["prediction_pointer"]
    require(isinstance(pointer, str) and pointer.startswith("/"), "Requirement units need an output JSON pointer")
    tokens = [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]
    for token in tokens:
        if isinstance(value, list):
            require(bool(re.fullmatch(r"0|[1-9][0-9]*", token)), "JSON pointers require nonnegative array indexes")
            value = value[int(token)]
        else:
            value = value[token]
    if unit["prediction_mode"] == "requirement_bucket":
        require(len(tokens) >= 3 and tokens[-3] == "requirements" and tokens[-2] in ("must_have", "nice_to_have"), "Invalid requirement bucket pointer")
        return {"must_have": "required", "nice_to_have": "preferred"}[tokens[-2]]
    if unit["prediction_mode"] == "requirement_handling":
        require(isinstance(value, dict), "Requirement handling needs a captured criterion object")
        if value.get("category") == "employment_condition" or value.get("kind") == "employment_condition" or "employment_conditions" in tokens:
            return "employment_condition"
        require(value.get("classification") in ("required", "preferred", "unclear"), "Criterion object lacks explicit modality")
        return value["classification"]
    require(unit["prediction_mode"] == "value", "Unknown prediction mode")
    return value
