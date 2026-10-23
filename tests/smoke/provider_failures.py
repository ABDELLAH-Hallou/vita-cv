"""Installed distribution provider-failure controls; HTTP and time are stubbed."""

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from vita.commands import providers
from vita.helpers import llm, provider_errors, structured_output
from vita.helpers.provider_errors import PROVIDER_ERROR_SCHEMA
from vita.helpers.structured import parse_json, validate
from vita.helpers.structured_output import run_text


def main():
    secret = "installed-fixture-secret"
    env = {"GEMINI_API_KEY": secret}
    def error(status):
        return urllib.error.HTTPError("https://example.invalid", status, secret, {"Retry-After": "2"}, io.BytesIO(secret.encode()))
    response = io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"OK"}]},"finishReason":"STOP"}]}')
    http = Mock(side_effect=[error(503), response, error(401)])
    with (patch.object(llm, "load_env", return_value=env),
          patch.object(provider_errors, "load_env", return_value=env),
          patch.object(llm, "get_llm_providers", return_value={"gemini": {"model": "installed-fixture"}}),
          patch.object(llm.urllib.request, "urlopen", http),
          patch.object(structured_output.time, "sleep") as sleep):
        assert run_text(step="provider-fixture", generate=llm.generate, system="Diagnostic", prompt="OK", route={"provider": "gemini"}) == "OK"
        outcome = parse_json(Path(".vita/results/provider-fixture.outcome.json").read_text(encoding="utf-8"))
        validate(outcome["attempts"][0]["error"], PROVIDER_ERROR_SCHEMA)
        assert outcome["attempt_count"] == 2 and outcome["attempts"][0]["category"] == "overloaded"
        sleep.assert_called_once_with(2)
        assert not providers.run(provider="gemini", model="installed-fixture", generate=True)
        result = parse_json(Path(".vita/results/provider-check.json").read_text(encoding="utf-8"))
        assert result["error"]["category"] == "authentication" and not result["generation_verified"]
        assert result["attempts"] == 1 and secret not in json.dumps(result) + json.dumps(outcome)
        assert http.call_count == 3
    print("Installed provider-error contract and bounded retry controls passed")


if __name__ == "__main__":
    main()
