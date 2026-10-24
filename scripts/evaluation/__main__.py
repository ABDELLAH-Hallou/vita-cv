"""Offline CLI. No provider clients, model calls, annotation generation or uploads."""

import argparse
import json
import sys
from pathlib import Path

from scripts.evaluation.contracts import VERSION, require, write
from scripts.evaluation.scoring import independent_reviews, markdown, score
from scripts.evaluation.study import (
    freeze,
    initialize,
    load_packet,
    packet,
    review_template,
    status,
)


def adjudication_template(root, packet_path, review_paths, reviewer_id, destination):
    registration, doc = load_packet(root, packet_path)
    reviews, hashes, _ = independent_reviews(root, registration, doc, review_paths)
    assignments = {a["case_id"]: a for a in doc["assignments"]["assignments"]}
    observations = {o["id"]: o for o in doc["observations"]}
    decisions = []
    require(any(a["adjudicator_id"] == reviewer_id for a in assignments.values()), "Assign a distinct qualified human adjudicator first")
    for unit in doc["units"]:
        assignment = assignments.get(observations[unit["observation_id"]]["case_id"])
        if not assignment or assignment["adjudicator_id"] != reviewer_id:
            continue
        ratings = [reviews.get((r, unit["id"])) for r in assignment["reviewer_ids"]]
        if all(ratings) and ratings[0]["label"] != ratings[1]["label"]:
            decisions.append({"unit_id": unit["id"], "label": None, "rationale": "", "evidence_kind": None, "refs": [], "checked_sources": []})
    result = {"schema_version": VERSION, "packet_sha256": doc["sha256"], "adjudicator_id": reviewer_id,
              "review_sha256": hashes, "completed_at": None, "reviewed_original_submissions": False, "decisions": decisions}
    write(destination, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create an empty private holdout and unannotated development example")
    init.add_argument("path", type=Path)
    for command in ("status", "freeze", "packet", "template", "adjudication-template", "score"):
        p = commands.add_parser(command)
        p.add_argument("--study", type=Path, required=True)
        if command in ("template", "adjudication-template", "score"):
            p.add_argument("--packet", type=Path, required=True)
        if command in ("template", "adjudication-template"):
            p.add_argument("--reviewer", required=True)
        if command in ("adjudication-template", "score"):
            p.add_argument("--reviews", type=Path, nargs="*", default=[])
        if command in ("packet", "template", "adjudication-template", "score"):
            p.add_argument("--output", type=Path, required=True)
        if command == "packet":
            p.add_argument("--split", choices=("development", "holdout"), required=True)
        if command == "score":
            p.add_argument("--adjudications", type=Path, nargs="*", default=[])
            p.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = initialize(args.path.resolve())
        else:
            root = args.study.resolve()
            if args.command == "status":
                result = status(root)
            elif args.command == "freeze":
                result = freeze(root)
            elif args.command == "packet":
                result = packet(root, args.output.resolve(), args.split)
            elif args.command == "template":
                result = review_template(root, args.packet, args.reviewer, args.output.resolve())
            elif args.command == "adjudication-template":
                result = adjudication_template(root, args.packet, args.reviews, args.reviewer, args.output.resolve())
            else:
                result = score(root, args.packet, args.reviews, args.adjudications)
                args.output.mkdir(parents=True, exist_ok=False)
                write(args.output / "report.json", result)
                (args.output / "report.md").write_text(markdown(result), encoding="utf-8")
                print(json.dumps({"status": result["status"], "sampling": result["sampling"]["status"], "agreement": result["agreement"]["status"], "report": str(args.output / "report.json")}, indent=2))
                unfinished = result["split"] != "holdout" or result["status"] != "reviewed_available_outputs" or result["sampling"]["status"] != "targets_met" or any(o["execution_status"] == "not_run" for o in result["observations"])
                return 1 if args.require_complete and unfinished else 0
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, IndexError, AttributeError) as exc:
        print(f"Evaluation validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
