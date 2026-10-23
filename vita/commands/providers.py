"""Explicit, separate model discovery and small generation diagnostics."""

import sys
from contextlib import redirect_stdout
from pathlib import Path

from vita.helpers import llm
from vita.helpers.diagnostics import diagnosed
from vita.helpers.provider_errors import normalize_error, safe_route
from vita.helpers.structured import json_text, parse_json, write_artifact
from vita.helpers.structured_output import StructuredOutputError, run_text


@diagnosed(name="provider-check")
def run(*, provider: str, model: str | None = None, generate: bool = False, as_json: bool = False) -> bool:
    step = "provider-check" if generate else "provider-discovery"
    result = {"schema_version": 1, "check": "generation" if generate else "discovery",
              "provider": None, "model": None, "status": "failed", "generation_verified": False,
              "may_consume_usage": generate, "discovery": None, "error": None, "attempts": 0}
    session = {}
    try:
        with redirect_stdout(sys.stderr):
            session = llm.prepare_session(provider, model)
        name, selected, _, _ = session["resolved"]
        route = {"provider": name, "model": selected}
        result.update({key: value for key, value in safe_route(route, session).items() if key in ("provider", "model")})
        if generate:
            print("This test generation may consume provider usage. It sends only a synthetic diagnostic prompt.", file=sys.stderr)
            with redirect_stdout(sys.stderr):
                run_text(step=step, generate=llm.generate, system="You are running a connection diagnostic.",
                         prompt="Reply with OK.", route=route, session=session)
            result.update(status="success", generation_verified=True)
        else:
            def discover(system, prompt, **kwargs):
                return json_text(llm.discover_models(session))
            catalog = run_text(step=step, generate=discover, system="", prompt="Model catalog discovery only.",
                               route=route, session=session)
            result.update(status="success", discovery=parse_json(catalog))
        result["attempts"] = session.get("request", {}).get("attempt", 0)
    except StructuredOutputError as exc:
        result["error"] = exc.error
        result["attempts"] = (exc.error or {}).get("attempts", session.get("request", {}).get("attempt", 0))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        result["error"] = normalize_error(exc).contract(step=step, route=safe_route(
            {"provider": provider, "model": model}, session), attempts=0, max_attempts=0)
    write_artifact(Path(f".vita/results/{step}.json"), json_text(result))
    if as_json:
        print(json_text(result))
    elif result["error"]:
        print(result["error"]["action"])
    elif generate:
        print(f"Generation succeeded with {result['provider']} / {result['model']}. This does not evaluate content quality.")
    else:
        print("Model discovery completed. A listed model does not prove generation access. "
              "Catalogs may be partial; absence is not an invalid-model diagnosis. "
              "Use --generate for a generation check; it may consume provider usage.")
    return result["status"] == "success"
