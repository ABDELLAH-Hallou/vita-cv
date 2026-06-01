# VITA — CV as Code

> **One base CV. Infinite targeted variants. Zero duplicates.**
>
> `vita-cv` is a CLI tool that treats your resume like source code — versioned with git, branched per company, and built from LaTeX.

```sh
uv tool install vita-cv
```

---

## How It Works

VITA manages your CV using git branches:

| Branch | Purpose |
|---|---|
| `master` | Your canonical base — the CV you're always proud of |
| `gen-<role>` | Domain-specific base (e.g. `gen-swe`, `gen-ml`) |
| `etp-<company>-<role>` | Tailored CV for a specific application (e.g. `etp-google-swe`) |

Every time you apply somewhere, you create a branch. VITA tracks that in a registry so you never accidentally send the wrong version or apply twice.

---

## Prerequisites

- **uv** — [install](https://docs.astral.sh/uv/getting-started/installation/) (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Python 3.10+** — managed automatically by uv
- **Git** (must be in PATH)
- **LaTeX** — [TeX Live](https://tug.org/texlive/) or [MiKTeX](https://miktex.org/), with `latexmk`

---

## Quick Start

```sh
# 1. Install vita from PyPI as a persistent tool
uv tool install vita-cv
# → vita is now available globally in your terminal

# 2. Create your CV project directory
mkdir my-cv && cd my-cv

# 3. Initialize VITA (creates .vita/ and git repo)
vita init

# 4. Edit .vita/config.json — set your name
#    "author": "yourname"

# 5. Create your LaTeX CV (see below)
# ... write main.tex, sections/, etc.

# 6. Commit your base CV
git add .
git commit -m "base: initial CV"

# 7. Apply to a company
vita new etp google "software engineer"
# → creates branch etp-google-swe, updates registry

# 8. Tailor your CV for this job, then build
vita build
```

---

## Your CV Project Structure

After running `vita init`, your project should look like this:

```
my-cv/
├── main.tex              ← LaTeX entry point (you create this)
├── sections/             ← Modular CV sections (you create these)
│   ├── experience.tex
│   ├── education.tex
│   ├── skills.tex
│   └── ...
├── job.md                ← Paste job descriptions here (for AI prompts)
├── out/                  ← PDF output (auto-created on build)
│
└── .vita/                ← Auto-created by `vita init`
    ├── config.json       ← Your settings (author, output paths, etc.)
    ├── companies.json    ← Registry of all companies you've applied to
    ├── extensions.json   ← Your custom role aliases and languages
    └── logs/             ← CLI activity log
```

> `.vita/` is gitignored — your registry and config stay local.

---

## Files You Need to Create

VITA manages the `.vita/` directory for you. **You are responsible for the LaTeX files.**

### `main.tex` — Entry Point

Your main LaTeX file. VITA will compile this with `latexmk`. Example minimal structure:

```latex
\documentclass{article}

\begin{document}

\input{sections/experience}
\input{sections/education}
\input{sections/skills}

\end{document}
```

You can use any LaTeX CV class (e.g. `moderncv`, `altacv`, `awesome-cv`).

### `sections/` — Modular Content

Split your CV into files so each branch only touches relevant sections:

```
sections/
├── experience.tex   ← Work history (most frequently changed per company)
├── education.tex    ← Education
├── skills.tex       ← Skills (adjust keywords per role)
├── summary.tex      ← Optional: tailored headline
└── projects.tex     ← Optional
```

### `job.md` — Job Description (for AI prompts)

When you run `vita adapt` or `vita analyze`, VITA looks for `job.md` in your project root. Paste the job posting there:

```markdown
Company: Google
Role: Senior Software Engineer

[Paste full job description here]
```

---

## Configuration Reference

`vita init` creates `.vita/config.json` with these defaults:

```json
{
  "author": "",
  "output_dir": "out",
  "output_filename": "cv-{author}.pdf",
  "tex_entry": "main.tex",
  "default_base_branch": "master",
  "allow_multiple_per_company": true,
  "warn_on_duplicate": true
}
```

| Key | What it does |
|---|---|
| `author` | Your name — used in the PDF filename |
| `output_dir` | Where the compiled PDF goes (`out/` by default) |
| `output_filename` | PDF name template. `{author}` is substituted automatically |
| `tex_entry` | Your LaTeX entry file (default: `main.tex`) |
| `default_base_branch` | The branch `vita new` checks out from if no base exists |
| `allow_multiple_per_company` | If `false`, blocks a second CV for the same company |
| `warn_on_duplicate` | If `true`, warns (but doesn't block) on duplicate company |

---

## CLI Commands

### `vita init`

Initialize VITA in the current directory. Creates `.vita/`, scaffolds config files, and runs `git init`.

```sh
vita init          # first-time setup
vita init --force  # wipe and re-initialize
```

---

### `vita new etp <company> <role>`

Create a new tailored CV branch for a job application.

```sh
vita new etp google "software engineer"
vita new etp openai ml
vita new etp stripe "backend engineer" --commit  # commit pending changes first
```

- Normalizes the role (`software engineer` → `swe`)
- Creates branch `etp-<company>-<role>` off your base branch
- Registers the company in `.vita/companies.json`
- Warns if you've already applied to this company

---

### `vita status`

See all companies, branches, and where you currently are.

```sh
vita status
```

```
VITA Status — yourname
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Current branch : etp-google-swe

Companies (2):
  google  [2 CVs]
    ├── etp-google-swe   base: gen-swe   ← you are here
    └── etp-google-ml    base: gen-ml

  meta  [1 CV] [LOCKED]
    └── etp-meta-swe     base: gen-swe

Base branches:
  gen-swe · gen-ml
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### `vita sync`

Reconcile the `.vita` directory and registry with your actual git branches. Useful if you created or deleted branches manually, or if local `.vita` files such as `config.json`, `extensions.json`, `.env`, or generated artifact directories are missing.

```sh
vita sync              # interactive
vita sync --dry-run    # preview only, no changes written
vita sync --auto       # apply all changes without prompting
```

---

### `vita build`

Compile your LaTeX CV to PDF using `latexmk`.

```sh
vita build
```

Output goes to `out/cv-<author>.pdf` (or whatever you configured).

---

### `vita diff <company>`

Show what changed in a company branch versus its base.

```sh
vita diff google
```

---

### `vita lock / unlock <company>`

Lock a company to prevent creating new CVs for it (e.g. you've accepted an offer).

```sh
vita lock amazon
vita unlock amazon
```

---

### `vita analyze`

Generate an AI prompt to analyze your CV against the job in `job.md`.

```sh
vita analyze
```

Saves the prompt to `.vita/current_prompt.md`. Open it and give it to your AI assistant.

---

### `vita adapt [--language <code>]`

Generate an AI prompt to tailor your CV to the job in `job.md`.

```sh
vita adapt               # English (default)
vita adapt --language fr # French
vita adapt --language ar # Arabic
```

---

### `vita review`

Generate an AI prompt to review and improve your CV in general.

```sh
vita review
```

---

## Typical Workflow

```sh
# Day 1 — Set up your CV project
uv tool install vita-cv
mkdir my-cv && cd my-cv
vita init
# → edit .vita/config.json (set author)
# → write main.tex and sections/

git add .
git commit -m "base: initial CV"

# Applying to a company
git checkout -b gen-swe         # create your domain baseline
# → tailor the CV for SWE roles generally
git add . && git commit -m "gen-swe: baseline"

vita new etp google "software engineer"
# → now on branch etp-google-swe

# Paste job description
echo "..." > job.md
vita analyze    # get analysis prompt
vita adapt      # get tailoring prompt
# → run prompts with AI, apply suggestions to sections/

vita build      # compile to PDF
# → out/cv-yourname.pdf

vita status     # review all companies
```

---

## Building the PDF

VITA uses `latexmk` automatically. If you need to build manually:

```sh
# Standard
latexmk -pdf -outdir=out main.tex

# With bibliography (BibTeX/Biber)
pdflatex -output-directory=out main.tex
biber --input-directory=out --output-directory=out main
pdflatex -output-directory=out main.tex
pdflatex -output-directory=out main.tex
```

---

## Extensibility

VITA ships with built-in role aliases and language codes. You can add your own in `.vita/extensions.json` (created by `vita init`):

```json
{
  "role_aliases": {
    "research engineer": "re",
    "applied scientist": "as",
    "solutions architect": "sa"
  },
  "language_map": {
    "zh": "Chinese (Simplified)",
    "ja": "Japanese"
  }
}
```

Your entries are merged on top of the built-ins — your values win on conflict.

See [EXTENSIONS.md](EXTENSIONS.md) for the full list of built-in aliases and all format details.

---

## AI Skills

VITA includes a library of AI agent skills for specialized tasks. Reference them when prompting your AI assistant:

| Category | Skills |
|---|---|
| **Writing** | `resume-writer`, `resume-bullet-writer`, `resume-quantifier` |
| **Reviewing** | `resume-reviewer`, `resume-ats-optimizer` |
| **Targeting** | `resume-tailor`, `job-description-analyzer`, `resume-section-builder` |
| **Documents** | `cover-letter-generator`, `linkedin-profile-optimizer` |
| **Prep** | `interview-prep-generator`, `salary-negotiation-prep`, `offer-comparison-analyzer` |
| **Specialized** | `tech-resume-optimizer`, `executive-resume-writer`, `academic-cv-builder` |
| **Transitions** | `career-changer-translator`, `creative-portfolio-resume` |

**Example usage:**

> "Use the `resume-tailor` skill to update `sections/experience.tex` based on the job description I pasted in `job.md`."

> "Run `interview-prep-generator` on my CV and generate 5 STAR stories for a Google interview."

---

## Design Philosophy

- **Warn, don't block** — duplicate CVs trigger a warning, not a hard stop (`--force` overrides, `locked: true` blocks permanently)
- **CLI enforces naming** — roles are normalized automatically (`data engineer` → `de`, `machine learning engineer` → `ml`)
- **Registry is the truth** — `.vita/companies.json` is the authoritative record; use `vita sync` if it drifts from git
- **User-extensible** — role aliases and language codes are fully overridable via `.vita/extensions.json`
- **No cloud** — everything is local; your CV data never leaves your machine
