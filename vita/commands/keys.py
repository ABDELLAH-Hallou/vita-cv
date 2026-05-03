"""vita/commands/keys.py — LLM API key management.

Commands:
  vita keys list
  vita keys set <provider> <key>
  vita keys remove <provider>
"""

import sys
from vita.helpers.env import load_env, set_env_key, ENV_FILE
from vita.helpers.logging import log


def _obfuscate(key: str) -> str:
    """Return an obfuscated version of the API key for safe display."""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


def run(action: str, provider: str = None, key: str = None) -> None:
    if action == "list":
        env_vars = load_env()
        print("LLM API Keys Configured (.vita/.env):\n")
        
        found = False
        for env_key, env_val in env_vars.items():
            if env_key.endswith("_API_KEY"):
                print(f"  {env_key}: {_obfuscate(env_val)}")
                found = True
                
        if not found:
            print("  No API keys found. Use `vita keys set <PROVIDER> <KEY>` to add one.")
            
    elif action == "set":
        if not provider or not key:
            print("Error: Provider and key are required for 'set' action.")
            sys.exit(1)
            
        provider_env = f"{provider.upper()}_API_KEY"
        set_env_key(provider_env, key)
        print(f"✅ Securely saved {provider_env} to {ENV_FILE}")
        log(f"Set API key for {provider}")
        
    elif action == "remove":
        if not provider:
            print("Error: Provider is required for 'remove' action.")
            sys.exit(1)
            
        provider_env = f"{provider.upper()}_API_KEY"
        set_env_key(provider_env, "") # Blank out the key
        print(f"🗑️ Removed {provider_env} from {ENV_FILE}")
        log(f"Removed API key for {provider}")
        
    else:
        print(f"Error: Unknown action '{action}'")
        sys.exit(1)
