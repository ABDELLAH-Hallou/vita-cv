"""vita/helpers/llm.py — Zero-dependency HTTP client for LLM APIs."""
import json
import urllib.request
import urllib.error
from vita.helpers.env import load_env
from vita.helpers.extensions import get_llm_providers


def generate(system_prompt: str, user_prompt: str) -> str:
    """Read config, pick provider, and call LLM API."""
    env = load_env()
    providers = get_llm_providers()
    
    if not providers:
        # Default fallback
        providers = {"openai": {"model": "gpt-4o"}}
        
    # We just pick the first configured provider for now
    provider_name = list(providers.keys())[0].lower()
    model = providers[provider_name].get("model", "gpt-4o")
    
    key_env_var = f"{provider_name.upper()}_API_KEY"
    api_key = env.get(key_env_var)
    if not api_key:
        raise ValueError(f"Missing API key for {provider_name}. Run `vita keys set {provider_name} <key>`.")
        
    print(f"🧠 Calling {provider_name} ({model})...")
    
    if provider_name == "openai":
        return _call_openai(system_prompt, user_prompt, api_key, model)
    elif provider_name == "anthropic":
        return _call_anthropic(system_prompt, user_prompt, api_key, model)
    else:
        raise ValueError(f"Unsupported provider: {provider_name}")


def _call_openai(system_prompt: str, user_prompt: str, api_key: str, model: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        raise RuntimeError(f"OpenAI API error: {e.code} - {error_msg}")


def _call_anthropic(system_prompt: str, user_prompt: str, api_key: str, model: str) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    data = {
        "model": model,
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["content"][0]["text"]
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        raise RuntimeError(f"Anthropic API error: {e.code} - {error_msg}")
