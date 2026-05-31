# VITA Extensions — Customization Guide

VITA ships with built-in role aliases and language codes, but every CV project
is different. The `.vita/extensions.json` file lets you extend or override these
defaults **without touching the package source**.

---

## File Location

```
.vita/extensions.json
```

This file is scaffolded automatically when you run `vita init`. Edit it freely —
it is gitignored by default so your customizations stay local.

---

## Format Reference

```json
{
  "llm_providers": {
    "<provider name>": {
      "model": "<model name>"
    }
  },
  "role_aliases": {
    "<verbose role name>": "<short code>"
  },
  "language_map": {
    "<language code>": "<full language name>"
  }
}
```

Keys prefixed with `_example_` are template placeholders — **delete them** and replace with your own entries.

---

## `llm_providers`

Configures the provider used by `vita analyze --auto`, `vita adapt --auto`,
`vita review --auto`, and `vita run --auto`.

**API providers** require a matching API key saved with `vita keys set`.

```json
{
  "llm_providers": {
    "gemini": {
      "model": "gemini-2.0-flash"
    }
  }
}
```

**Codex CLI** uses your local Codex login instead of an API key.

```json
{
  "llm_providers": {
    "codex": {
      "model": ""
    }
  }
}
```

Before using the Codex provider, make sure the Codex CLI works locally:

```sh
codex login
codex exec "Say hello"
```

Then run:

```sh
vita run --auto
```

---

## `role_aliases`

Maps verbose role names (as you type them in `vita new etp <company> <role>`)
to normalized short codes used in branch names.

**Rules:**
- Keys are **case-insensitive** (normalized to lowercase internally).
- Values should be **lowercase slugs**, ideally 2–6 characters.
- User-defined entries **win** over built-in ones on key conflict.

**Built-in aliases (already included):**

| Verbose Name | Short Code |
|---|---|
| `software engineer` | `swe` |
| `data engineer` | `de` |
| `machine learning` | `ml` |
| `machine learning engineer` | `ml` |
| `data scientist` | `ds` |
| `artificial intelligence` | `ai` |
| `backend` / `backend engineer` | `be` |
| `frontend` / `frontend engineer` | `fe` |
| `full stack` / `full stack engineer` | `fs` |
| `devops` | `devops` |
| `product manager` | `pm` |
| `infrastructure engineer` | `infra` |
| `pre-training engineer` | `pt` |
| `inference engineer` | `ie` |

**Example — add custom aliases:**

```json
{
  "role_aliases": {
    "research engineer": "re",
    "applied scientist": "as",
    "solutions architect": "sa",
    "site reliability engineer": "sre",
    "quantitative researcher": "quant"
  }
}
```

After adding this, running `vita new etp deepmind "research engineer"` will create the branch `etp-deepmind-re`.

---

## `language_map`

Maps short ISO language codes (used with `vita adapt --language <code>`) to
their full names, which are injected into the AI translation prompt.

**Rules:**
- Keys should be **ISO 639-1** codes (e.g. `zh`, `ja`, `ko`).
- Keys are **case-insensitive**.
- User-defined entries **win** over built-in ones on key conflict.

**Built-in languages (already included):**

| Code | Language |
|---|---|
| `en` | English |
| `fr` | French |
| `ar` | Arabic |
| `de` | German |
| `es` | Spanish |
| `it` | Italian |
| `nl` | Dutch |
| `pt` | Portuguese |

**Example — add more languages:**

```json
{
  "language_map": {
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "ko": "Korean",
    "sv": "Swedish",
    "pl": "Polish",
    "tr": "Turkish"
  }
}
```

After adding `zh`, running `vita adapt --language zh` will instruct the AI to write the CV in Chinese (Simplified).

---

## Full Example

```json
{
  "role_aliases": {
    "research engineer": "re",
    "applied scientist": "as",
    "solutions architect": "sa",
    "site reliability engineer": "sre"
  },
  "language_map": {
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "ko": "Korean"
  }
}
```

---

## How Merging Works

```
final_map = built_in_map + user_extensions
```

If the same key appears in both, **your entry wins**. This allows you to override
a built-in alias if you disagree with the default short code:

```json
{
  "role_aliases": {
    "machine learning engineer": "mle"
  }
}
```

This overrides the built-in `ml` → your branches will use `mle` instead.

---

## Malformed JSON

If `.vita/extensions.json` contains invalid JSON, VITA will print a warning and
fall back to the built-in defaults — no commands will fail.

```
⚠️  Malformed .vita/extensions.json — ignoring user extensions. (...)
```
