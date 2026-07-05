"""vita/helpers/llm.py — Zero-dependency HTTP client for popular LLM APIs.

Supported providers (OpenAI-compatible):
  openai, groq, mistral, deepseek, xai, together, perplexity, cohere

Non-compatible (different API format, handled separately):
  anthropic, gemini / google
"""
import json
import os
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from vita.helpers.env import load_env
from vita.helpers.extensions import get_llm_providers


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


def generate(system_prompt: str, user_prompt: str, provider: str | None = None) -> str:
    """Auto-detect provider from config and call the appropriate API."""
    env = load_env()
    providers = get_llm_providers()

    if not providers:
        providers = {"openai": {"model": "gpt-4o"}}

    provider_name = provider.lower() if provider else list(providers.keys())[0].lower()
    if provider_name not in providers:
        configured = ", ".join(providers.keys())
        raise ValueError(
            f"Provider '{provider_name}' is not configured. "
            f"Configured providers: {configured}"
        )

    config = providers[provider_name]
    model = config.get("model") or _DEFAULT_MODELS.get(provider_name, "gpt-4o")

    if provider_name == "codex":
        return _call_codex_cli(system_prompt, user_prompt, model)

    key_env_var = f"{provider_name.upper()}_API_KEY"
    api_key = env.get(key_env_var)
    if not api_key:
        raise ValueError(
            f"Missing API key for '{provider_name}'. "
            f"Run: vita keys set {provider_name} <your-key>"
        )

    print(f"🧠 Calling {provider_name} ({model})...")

    # Route to the correct API format
    if provider_name in _OPENAI_COMPATIBLE:
        url = _OPENAI_COMPATIBLE[provider_name]
        return _call_openai_compatible(system_prompt, user_prompt, api_key, model, url)
    elif provider_name == "anthropic":
        return _call_anthropic(system_prompt, user_prompt, api_key, model)
    elif provider_name in ("gemini", "google"):
        return _call_gemini(system_prompt, user_prompt, api_key, model)
    else:
        supported = list(_OPENAI_COMPATIBLE.keys()) + ["anthropic", "gemini"]
        raise ValueError(
            f"Unknown provider '{provider_name}'. "
            f"Supported: {', '.join(supported)}"
        )


def _call_codex_cli(system_prompt: str, user_prompt: str, model: str = "") -> str:
    """Run Codex CLI non-interactively using the user's local Codex login."""
    codex = _find_codex_cli()
    if not codex:
        raise RuntimeError(
            "Codex CLI not found. Install/login to Codex first, then run `codex login`."
        )

    prompt = f"{system_prompt}\n\n==== TASK ====\n{user_prompt}"
    output_dir = Path(".vita") / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "codex-output.md"

    cmd = [
        codex,
        "exec",
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(output_path),
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append("-")

    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    response = output_path.read_text(encoding="utf-8").strip()
    output_path.unlink(missing_ok=True)
    return response


def _find_codex_cli() -> str | None:
    """Find Codex even when the VS Code extension version changes and PATH is stale."""
    explicit = os.environ.get("VITA_CODEX") or os.environ.get("CODEX_EXE")
    if explicit and Path(explicit).is_file():
        return explicit

    codex = shutil.which("codex")
    if codex:
        return codex

    home = Path.home()
    matches: list[Path] = []
    for extensions_dir in [
        home / ".vscode" / "extensions",
        home / ".vscode-insiders" / "extensions",
    ]:
        if extensions_dir.exists():
            matches.extend(
                extensions_dir.glob(
                    "openai.chatgpt-*-win32-x64/bin/windows-x86_64/codex.exe"
                )
            )

    if not matches:
        return None

    latest = max(matches, key=lambda path: path.stat().st_mtime)
    codex_dir = str(latest.parent)
    if codex_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = codex_dir + os.pathsep + os.environ.get("PATH", "")
    return str(latest)

# ── API Implementations ────────────────────────────────────────────────────────

def _call_openai_compatible(
    system_prompt: str, user_prompt: str, api_key: str, model: str, url: str
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
        "temperature": 0.2,
    }
    return _post(url, headers, data)["choices"][0]["message"]["content"]


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
    return _post(url, headers, data)["content"][0]["text"]


def _call_gemini(
    system_prompt: str, user_prompt: str, api_key: str, model: str
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
    result = _post(url, headers, data)
    return result["candidates"][0]["content"]["parts"][0]["text"]


# ── HTTP Helper ───────────────────────────────────────────────────────────────

def _post(url: str, headers: dict, data: dict) -> dict:
    """Make a JSON POST request and return the parsed response."""
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        raise RuntimeError(f"API error {e.code}: {error_msg}")
