# VITA Extensions — Customization Guide

Codex supports an opt-in `execution_mode: "restricted"` alongside its existing
model/reasoning settings. See [AGENT_EXECUTION.md](AGENT_EXECUTION.md) for exact
controls, limitations, diagnostics, baseline selection and evaluation plans.

VITA ships with built-in role aliases, language codes, and LLM provider support,
but every CV project is different. The `.vita/extensions.json` file lets you
extend or override these defaults **without touching the package source**.

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

Keys starting with `_` are ignored. Use them for documentation or template
placeholders, and delete/replace them when you want an entry to become active.

---

## `llm_providers`

Configures the provider used by `vita analyze --auto`, `vita adapt --auto`,
`vita review --auto`, `vita cover --auto`, and `vita run --auto`. Stage-specific
settings in `.vita/.env` can override this fallback, including an independent
provider for `vita extract --auto`. See [pipeline configuration](PIPELINE.md).

**API providers** require a matching API key saved with `vita keys set`, in
`.vita/.env`, or in the process environment. OpenAI uses `OPENAI_API_KEY`,
OpenRouter uses `OPENROUTER_API_KEY`, and Gemini uses `GEMINI_API_KEY`.
Explicitly selecting a supported API provider does not require a duplicate
entry in `extensions.json`; an entry can still supply its default model.

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

When you run a command with `--provider codex` and Codex is missing from
`.vita/extensions.json`, VITA asks whether it should add the provider for you.
Set `"auto_add_codex_provider": true` in `.vita/config.json` to add it
automatically without a prompt.

Then run:

```sh
vita run --auto
```

If you configure more than one provider, VITA uses the first provider in
`.vita/extensions.json` by default. Choose a specific provider with
`--provider`:

```sh
vita run --auto --provider codex
vita adapt --auto --provider gemini
vita review --auto --provider anthropic
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
  "llm_providers": {
    "codex": {
      "model": ""
    },
    "gemini": {
      "model": "gemini-2.0-flash"
    }
  },
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

## Custom task skills

Place Markdown files directly in `.vita/skills/<task>/`. Run `vita sync --auto`
to add these folders to an existing project without replacing your files.

| Folder | Bundled skills used by default |
|---|---|
| `extract/` | None; optional local extraction guidance |
| `analyze/` | `job-description-analyzer.md` |
| `adapt/` | `tech-resume-optimizer.md`, `resume-bullet-writer.md`, `resume-ats-optimizer.md`, `resume-tailor.md` |
| `review/` | `resume-reviewer.md` |
| `assess/` | `assessment-judge.md` (shared scoring judge for Analyze and Review) |
| `cover/` | `cover-letter-generator.md` |

A nonempty file with the same filename replaces that bundled skill for that
task. Other `.md` files add guidance after the default skills, in filename order.
Empty files are ignored, and subfolders are not scanned. Project-local writing
and style guidance takes precedence over bundled guidance; factual accuracy,
the requested language, and the required output format still apply.

For example, create `.vita/skills/adapt/writing-style.md`:

```markdown
Write the profile in natural French with connected sentences.
Explain the candidate's main role and the kind of problems they solve.
Use technologies selectively and avoid keyword quotas in the summary.
Include a metric only when its context is clear from the source CV.
```

Add corresponding review guidance in `.vita/skills/review/` if you want the
separate `vita review --qualitative` writing audit to assess the same preferences.
Analyze/Review task skills are qualitative-only; use `.vita/skills/assess/` for
shared scoring guidance. Keep canonical criteria, evidence rules and the host
assessment contract authoritative. Put cover letter preferences in
`.vita/skills/cover/`; CV-only skills are not loaded for the letter.

Custom skills work with every configured provider and with manual prompt
generation. They are embedded in the generated prompt, so regenerate it after
editing a skill. `.vita/` is normally ignored by Git; back up or explicitly
version your customizations if needed. `vita init --force` still replaces the
whole `.vita/` directory, including custom skills; use `sync` for migration.

## Malformed JSON

For AI-generated JSON (extraction and evaluations), see
[structured output and recovery](PIPELINE.md#structured-output-and-format-recovery).
Provider entries in `llm_providers` accept `"structured_output": "auto"` (default)
or `"off"` (validated prompt mode). Codex, OpenAI, and OpenRouter entries also
accept `"reasoning_effort": "low"` (or another value supported by the selected
model); retries preserve this value. Omitting reasoning effort preserves the
provider/CLI default. No retry changes the selected model.

If `.vita/extensions.json` contains invalid JSON, VITA will print a warning and
fall back to the built-in defaults — no commands will fail.

```
⚠️  Malformed .vita/extensions.json — ignoring user extensions. (...)
```
