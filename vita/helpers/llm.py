"""vita/helpers/llm.py — Zero-dependency HTTP client for popular LLM APIs.

Supported providers (OpenAI-compatible):
  openai, openrouter, groq, mistral, deepseek, xai, together, perplexity, cohere

Non-compatible (different API format, handled separately):
  anthropic, gemini / google
"""
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from vita.helpers import diagnostics as diagnostic
from vita.helpers.config import load_config
from vita.helpers.env import load_env
from vita.helpers.extensions import add_llm_provider, get_llm_providers
from vita.helpers.provider_errors import (
    ProviderError,
    UnsupportedSchema,
    http_category,
    retry_after_seconds,
    safe_identifier,
    safe_route,
)
from vita.helpers.structured import generation_schema

# ── OpenAI-Compatible Provider Registry ───────────────────────────────────────
# All of these accept the exact same request/response format as OpenAI.
# Adding a new provider is as simple as adding a line here.
_OPENAI_COMPATIBLE = {
    "openai":      "https://api.openai.com/v1/chat/completions",
    "groq":        "https://api.groq.com/openai/v1/chat/completions",
    "mistral":     "https://api.mistral.ai/v1/chat/completions",
    "deepseek":    "https://api.deepseek.com/v1/chat/completions",
    "xai":         "https://api.x.ai/v1/chat/completions",
    "together":    "https://api.together.xyz/v1/chat/completions",
    "perplexity":  "https://api.perplexity.ai/chat/completions",
    "cohere":      "https://api.cohere.com/compatibility/v1/chat/completions",
    "openrouter":  "https://openrouter.ai/api/v1/chat/completions",
}

# Default models per provider
_DEFAULT_MODELS = {
    "openai":     "gpt-4o",
    "groq":       "llama-3.3-70b-versatile",
    "mistral":    "mistral-large-latest",
    "deepseek":   "deepseek-chat",
    "xai":        "grok-3-mini",
    "together":   "meta-llama/Llama-3-70b-chat-hf",
    "perplexity": "sonar-pro",
    "cohere":     "command-r-plus",
    "openrouter": "openai/gpt-4o",
    "anthropic":  "claude-3-5-sonnet-20241022",
    "gemini":     "gemini-2.0-flash",
    "google":     "gemini-2.0-flash",
    "codex":      "",
}


def generate(
    system_prompt: str, user_prompt: str, provider: str | None = None,
    model: str | None = None, *, response_schema: dict | None = None,
    session: dict | None = None,
) -> str:
    """One adapter attempt. The operation runner owns the shared retry budget."""
    try:
        return _generate_once(system_prompt, user_prompt, provider, model,
                              response_schema=response_schema, session=session)
    except ProviderError:
        raise
    except (TimeoutError, subprocess.TimeoutExpired):
        raise ProviderError(code="timeout") from None
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        diagnostic.failure("provider_request", exc, category="unclassified")
        raise ProviderError() from None
    except OSError as exc:
        diagnostic.failure("provider_request", exc, category="unclassified")
        raise ProviderError(code="provider_error") from None


def _generate_once(system_prompt, user_prompt, provider=None, model=None, *, response_schema=None, session=None):
    """Resolve exactly one route and call it without a fallback or hidden retry."""
    # A structured operation reuses this private snapshot across attempts. It
    # contains credentials and must never be serialized into outcome records.
    requested_model = model
    if session is not None and "resolved" in session:
        resolved = session["resolved"]
    else:
        try:
            resolved = _resolve(provider, model)
        except (ValueError, TypeError, OSError):
            raise ProviderError(code="configuration") from None
        if session is not None:
            session["resolved"] = resolved
    provider_name, model, config, env = resolved
    diagnostic.routing(provider, requested_model, resolved)
    native = response_schema is not None and provider_name in {"codex", "openai", "openrouter", "gemini", "google"}
    native = native and config.get("structured_output", "auto") != "off"
    if session is not None:
        session["mode"] = "native_schema" if native else "validated_prompt"
        session["route"] = {"provider": provider_name, "model": model or None,
                            "reasoning_effort": config.get("reasoning_effort") if provider_name in ("codex", "openai", "openrouter") else None}
    options = {"response_schema": generation_schema(response_schema)} if native else {}
    reasoning = config.get("reasoning_effort")
    if reasoning is not None and provider_name in {"codex", "openai", "openrouter"}:
        options["reasoning_effort"] = reasoning

    if provider_name == "codex":
        return _call_codex_cli(system_prompt, user_prompt, model, **options)

    key_env_var = f"{provider_name.upper()}_API_KEY"
    api_key = env.get(key_env_var)
    if provider_name == "google":
        api_key = api_key or env.get("GEMINI_API_KEY")
    if not api_key:
        diagnostic.failure("configuration", category="configuration")
        if diagnostic.current():
            diagnostic.current().response_exists = False
        diagnostic.capture("response", exists=False)
        raise ProviderError(code="configuration")
    public = safe_route({"provider": provider_name, "model": model}, {"resolved": resolved})
    print(f"🧠 Calling {public['provider']} ({public['model']})...")
    if provider_name == "openai":
        return _call_openai(system_prompt, user_prompt, api_key, model, **options)
    if provider_name == "openrouter":
        return _call_openrouter(system_prompt, user_prompt, api_key, model, **options)
    if provider_name in _OPENAI_COMPATIBLE:
        return _call_openai_compatible(system_prompt, user_prompt, api_key, model, _OPENAI_COMPATIBLE[provider_name])
    if provider_name == "anthropic":
        return _call_anthropic(system_prompt, user_prompt, api_key, model)
    if provider_name in ("gemini", "google"):
        return _call_gemini(system_prompt, user_prompt, api_key, model, **options)
    raise ValueError(f"Unknown provider '{provider_name}'")


def prepare_session(provider: str | None = None, model: str | None = None) -> dict:
    """Freeze routing before cache lookup. This private object contains credentials.

    Explicit Codex assessment routing can use its CLI without modifying the
    provider registry or asking an interactive question during preparation.
    """
    try:
        return {"resolved": _resolve(provider, model, allow_prompt=False)}
    except (ValueError, OSError):
        raise ProviderError(code="configuration") from None


@diagnostic.phase("configuration")
def _resolve(provider: str | None, model: str | None, *, allow_prompt: bool = True) -> tuple:
    """Resolve configuration once, without changing the requested model."""
    requested_model = model
    env = load_env()
    providers = get_llm_providers()

    if not providers:
        providers = {"openai": {"model": "gpt-4o"}}

    provider_name = provider.lower() if provider else list(providers.keys())[0].lower()
    if provider_name not in providers:
        if provider_name == "codex":
            auto_add = load_config().get("auto_add_codex_provider", False)
            if auto_add:
                add_llm_provider("codex", {"model": ""})
                providers["codex"] = {"model": ""}
                print("Added Codex to .vita/extensions.json automatically.")
            elif allow_prompt:
                answer = input(
                    "Codex is not configured in .vita/extensions.json. Add it? (y/n): "
                ).strip().lower()
                if answer == "y":
                    add_llm_provider("codex", {"model": ""})
                    providers["codex"] = {"model": ""}
                    print("Added Codex to .vita/extensions.json.")
                else:
                    raise ValueError(
                        "Codex is not configured. Add it to .vita/extensions.json "
                        "or rerun and answer 'y'."
                    )
        elif provider_name in _OPENAI_COMPATIBLE or provider_name in ("gemini", "google", "anthropic"):
            # Explicit routing via .env does not require a duplicate extensions.json entry.
            providers[provider_name] = {}
        else:
            configured = ", ".join(providers.keys())
            raise ValueError(
                f"Provider '{provider_name}' is not configured. "
                f"Configured providers: {configured}"
            )

    config = dict(providers.get(provider_name, {}))
    origins = {"provider_origin": "explicit" if provider else "extensions",
               "model_origin": "explicit" if model else "extensions" if config.get("model") else "default",
               "reasoning_origin": "extensions" if config.get("reasoning_effort") else "cli_inherited" if provider_name == "codex" else "default"}
    model = model or config.get("model") or _DEFAULT_MODELS.get(provider_name, "gpt-4o")
    if config.get("structured_output", "auto") not in {"auto", "off"}:
        raise ValueError("structured_output must be auto or off")
    resolved = provider_name, model, config, dict(env)
    diagnostic.routing(provider, requested_model, resolved, origins)
    return resolved


def _call_codex_cli(system_prompt: str, user_prompt: str, model: str = "", *,
                    response_schema: dict | None = None, reasoning_effort: str | None = None) -> str:
    """Run Codex CLI non-interactively using the user's local Codex login."""
    codex = _find_codex_cli()
    if not codex:
        raise ProviderError(code="configuration")

    prompt = f"{system_prompt}\n\n==== TASK ====\n{user_prompt}"
    output_dir = Path(".vita") / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    # Separate paths prevent stale responses or concurrent runs sharing output.
    with tempfile.TemporaryDirectory(prefix="codex-", dir=output_dir) as temporary:
        output_path = Path(temporary) / "output.txt"
        cmd = [codex, "exec", "--sandbox", "read-only", "--output-last-message", str(output_path)]
        if response_schema is not None:
            schema_path = Path(temporary) / "schema.json"
            schema_path.write_text(json.dumps(response_schema), encoding="utf-8")
            cmd.extend(["--output-schema", str(schema_path)])
        if model:
            cmd.extend(["--model", model])
        if reasoning_effort is not None:
            cmd.extend(["--config", "model_reasoning_effort=" + json.dumps(reasoning_effort)])
        cmd.append("-")
        result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            if response_schema is not None and re.search(r"unexpected argument ['\"]--output-schema['\"]", error):
                raise UnsupportedSchema()
            # CLI diagnostics have no stable JSON error envelope. Only recognize
            # explicit status/model markers; never publish stderr or retry a guess.
            status = re.search(r"\b(?:HTTP(?: status)?|status(?: code)?)[: =]+(401|403|408|429|500|502|503|504|529)\b", error, re.IGNORECASE)
            code = http_category(int(status[1]), error) if status else (
                "invalid_model" if re.search(r"model_not_found|invalid_model|model[^\n]{0,120}(?:does not exist|not supported)", error, re.IGNORECASE)
                else "provider_error")
            raise ProviderError(code=code, status=int(status[1]) if status else None)
        if not output_path.is_file():
            raise ProviderError("Codex returned no final output file", "empty_response")
        return output_path.read_text(encoding="utf-8").strip()


def _codex_extension_roots(home: Path) -> tuple[Path, ...]:
    """Return the standard local and remote VS Code extension directories."""
    return (
        home / ".vscode" / "extensions",
        home / ".vscode-insiders" / "extensions",
        home / ".vscode-server" / "extensions",
        home / ".vscode-remote" / "extensions",
    )


def _find_codex_cli() -> str | None:
    """Find Codex on PATH or in a locally installed VS Code ChatGPT extension."""
    explicit = os.environ.get("VITA_CODEX") or os.environ.get("CODEX_EXE")
    if explicit and Path(explicit).is_file():
        return explicit

    if codex := shutil.which("codex"):
        return codex

    executable = "codex.exe" if os.name == "nt" else "codex"

    candidates: list[Path] = []
    for root in _codex_extension_roots(Path.home()):
        if not root.is_dir():
            continue

        for extension in root.glob("openai.chatgpt-*"):
            if not extension.is_dir():
                continue

            for candidate in extension.rglob(executable):
                if candidate.is_file() and (
                    os.name == "nt" or os.access(candidate, os.X_OK)
                ):
                    candidates.append(candidate)

    if not candidates:
        return None

    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    codex_dir = str(latest.parent)
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if codex_dir not in path_entries:
        os.environ["PATH"] = codex_dir + os.pathsep + os.environ.get("PATH", "")
    return str(latest)

# ── API Implementations ────────────────────────────────────────────────────────

def _call_openai(system_prompt: str, user_prompt: str, api_key: str, model: str, **options) -> str:
    return _call_openai_compatible(system_prompt, user_prompt, api_key, model, _OPENAI_COMPATIBLE["openai"], **options)


def _call_openrouter(system_prompt: str, user_prompt: str, api_key: str, model: str, **options) -> str:
    return _call_openai_compatible(system_prompt, user_prompt, api_key, model, _OPENAI_COMPATIBLE["openrouter"], **options)

@diagnostic.phase("decoding")
def _call_openai_compatible(
    system_prompt: str, user_prompt: str, api_key: str, model: str, url: str, *,
    response_schema: dict | None = None, reasoning_effort: str | None = None,
) -> str:
    """Handles OpenAI and all OpenAI-compatible APIs (Groq, Mistral, DeepSeek, etc.)."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    }
    # Leave optional sampling controls unset: reasoning/nano models can reject them.
    if response_schema is not None:
        data["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "vita_output", "strict": True, "schema": response_schema,
        }}
        if url == _OPENAI_COMPATIBLE["openrouter"]:
            data["provider"] = {"require_parameters": True}
    if reasoning_effort is not None:
        if url == _OPENAI_COMPATIBLE["openrouter"]:
            data["reasoning"] = {"effort": reasoning_effort}
        else:
            data["reasoning_effort"] = reasoning_effort
    result = _post(url, headers, data)
    if (not isinstance(result, dict) or not isinstance(result.get("choices"), list) or not result["choices"]
            or not isinstance(result["choices"][0], dict) or not isinstance(result["choices"][0].get("message"), dict)):
        raise ProviderError(code="response_shape")
    choice = result["choices"][0]
    if choice["message"].get("refusal") or choice.get("finish_reason") == "content_filter":
        raise ProviderError("Provider refused the response", "refusal")
    if choice.get("finish_reason") not in (None, "stop"):
        raise ProviderError("Provider did not complete its response", "incomplete_response")
    content = choice["message"].get("content")
    if not isinstance(content, str) or not content.strip():
        if diagnostic.current():
            diagnostic.current().response_exists = True
        diagnostic.capture("response", "", exists=True)
        raise ProviderError("Provider returned no text", "empty_response")
    return content


@diagnostic.phase("decoding")
def _call_anthropic(
    system_prompt: str, user_prompt: str, api_key: str, model: str
) -> str:
    """Handles Anthropic Claude (unique API format)."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    data = {
        "model": model,
        "max_tokens": 8192,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": 0.2,
    }
    result = _post(url, headers, data)
    if not isinstance(result, dict):
        raise ProviderError(code="response_shape")
    if result.get("stop_reason") == "refusal":
        raise ProviderError("Provider refused the response", "refusal")
    if result.get("stop_reason") not in (None, "end_turn", "stop_sequence"):
        raise ProviderError("Provider did not complete its response", "incomplete_response")
    if not isinstance(result.get("content"), list) or any(not isinstance(p, dict) or not isinstance(p.get("text", ""), str) for p in result["content"]):
        raise ProviderError(code="response_shape")
    content = "".join(part.get("text", "") for part in result["content"] if part.get("type", "text") == "text")
    if not content.strip():
        if diagnostic.current():
            diagnostic.current().response_exists = True
        diagnostic.capture("response", "", exists=True)
        raise ProviderError(code="empty_response")
    return content


@diagnostic.phase("decoding")
def _call_gemini(
    system_prompt: str, user_prompt: str, api_key: str, model: str, *, response_schema: dict | None = None,
) -> str:
    """Handles Google Gemini (API key as query param, different body format)."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model}:generateContent?key={api_key}"
    )
    headers = {"Content-Type": "application/json"}
    data = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    if response_schema is not None:
        data["generationConfig"].update(responseMimeType="application/json", responseJsonSchema=response_schema)
    result = _post(url, headers, data)
    if not isinstance(result, dict):
        raise ProviderError(code="response_shape")
    if result.get("promptFeedback", {}).get("blockReason"):
        raise ProviderError("Provider blocked the response", "refusal")
    if "candidates" not in result or not isinstance(result["candidates"], list):
        raise ProviderError(code="response_shape")
    if not result["candidates"]:
        raise ProviderError(code="empty_response")
    candidate = result["candidates"][0]
    if not isinstance(candidate, dict) or not isinstance(candidate.get("content", {}), dict):
        raise ProviderError(code="response_shape")
    reason = candidate.get("finishReason")
    if reason in {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST"}:
        raise ProviderError("Provider blocked the response", "refusal")
    if reason not in (None, "STOP"):
        raise ProviderError("Provider did not complete its response", "incomplete_response")
    parts = candidate.get("content", {}).get("parts")
    if not isinstance(parts, list) or any(not isinstance(p, dict) or not isinstance(p.get("text", ""), str) for p in parts):
        raise ProviderError(code="response_shape")
    content = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    if not content.strip():
        if diagnostic.current():
            diagnostic.current().response_exists = True
        diagnostic.capture("response", "", exists=True)
        raise ProviderError(code="empty_response")
    return content


# ── HTTP Helper ───────────────────────────────────────────────────────────────

def _post(url: str, headers: dict, data: dict | None, *, method: str = "POST") -> dict:
    """Make a JSON POST request and return the parsed response."""
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with diagnostic.span("provider_request"):
            with urllib.request.urlopen(req, timeout=120) as response:
                raw = response.read()
                diagnostic.http_metadata(getattr(response, "status", 200), getattr(response, "headers", {}), raw.decode("utf-8", errors="replace"))
        with diagnostic.span("decoding"):
            try:
                result = json.loads(raw.decode("utf-8"))
                if not isinstance(result, dict):
                    raise ProviderError(code="response_shape")
                return result
            except (ValueError, UnicodeError) as exc:
                diagnostic.failure("decoding", exc, category="response_decode", line=getattr(exc, "lineno", None), column=getattr(exc, "colno", None))
                raise ProviderError(code="response_decode") from None
    except urllib.error.HTTPError as e:
        error_msg = e.read(8192).decode("utf-8", errors="replace")
        diagnostic.http_metadata(e.code, e.headers, error_msg, rejected=True)
        # Only explicit lack of format support permits a prompt-only fallback.
        # Invalid schemas, auth, quota, and transport failures never trigger it.
        constrained = data is not None and ("response_format" in data or "responseJsonSchema" in data.get("generationConfig", {}))
        category = http_category(e.code, error_msg)
        diagnostic.failure("provider_request", e, category=category, http_status=e.code)
        if constrained and category != "invalid_model" and e.code in (400, 422) and unsupported_schema_error(error_msg):
            raise UnsupportedSchema(status=e.code) from None
        raise ProviderError(code=category, status=e.code,
                            retry_after=retry_after_seconds(e.headers.get("Retry-After") if e.headers else None)) from None
    except urllib.error.URLError as e:
        code = "tls" if isinstance(e.reason, ssl.SSLCertVerificationError) else (
            "timeout" if isinstance(e.reason, TimeoutError) else "connection")
        diagnostic.failure("provider_request", e.reason if isinstance(e.reason, Exception) else e, category=code)
        raise ProviderError(code=code) from None
    except TimeoutError:
        raise ProviderError(code="timeout") from None


def unsupported_schema_error(message: str) -> bool:
    text = message.lower()
    if any(term in text for term in ("invalid schema", "invalid json schema", "schema keyword", "schema for",
                                     "additionalproperties", "minitems", "minlength")):
        return False
    fields = ("response_format", "json_schema", "responsejsonschema", "response_mime_type", "responsemimetype")
    return any(field in text for field in fields) and any(
        phrase in text for phrase in ("not supported", "unsupported parameter", "unknown field", "unknown name")
    )


def discover_models(session: dict) -> dict:
    """Read one catalog page; discovery is never evidence of generation access."""
    provider, model, _, env = session["resolved"]
    session["route"] = {"provider": provider, "model": model or None, "reasoning_effort": None}
    if provider == "codex":
        return {"status": "unavailable", "models": [], "has_more": None,
                "selected_model_listed": None}
    key = env.get(f"{provider.upper()}_API_KEY") or (env.get("GEMINI_API_KEY") if provider == "google" else None)
    if not key:
        raise ProviderError(code="configuration")
    if provider in ("gemini", "google"):
        result = _post(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", {}, None, method="GET")
        models = [item.get("name", "").removeprefix("models/") for item in result.get("models", [])]
        more = bool(result.get("nextPageToken"))
    else:
        url = "https://api.anthropic.com/v1/models" if provider == "anthropic" else (
            _OPENAI_COMPATIBLE[provider].removesuffix("/chat/completions") + "/models")
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"} if provider == "anthropic" else {"Authorization": f"Bearer {key}"}
        result = _post(url, headers, None, method="GET")
        models = [item.get("id", "") for item in result.get("data", [])]
        more = bool(result["has_more"]) if "has_more" in result else None
    safe = [identifier for item in models if (identifier := safe_identifier(item, (key,))) is not None]
    return {"status": "listed", "models": safe, "has_more": more,
            "selected_model_listed": model in models}
