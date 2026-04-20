# VITA — Resume as a Service

> **Resume-as-Code + Policy Enforcement Layer**
>
> VITA is a git-based CV management system that lets you maintain, version, and tailor your resume for different companies and roles — while enforcing consistency and preventing accidental duplicate applications.

---

## Why VITA?

Most people manage CVs as loose files. VITA treats your resume like source code:

- ✅ **Versioned** — every change is tracked via git
- ✅ **Branched** — one base CV, infinite targeted variants
- ✅ **Guarded** — CLI warns you before you apply twice to the same company
- ✅ **Reproducible** — LaTeX builds are automated and standardized

---

## Branch Structure

| Branch Pattern | Purpose |
|---|---|
| `master` | Stable base CVs by domain |
| `gen-<field>` | General CV per domain (e.g. `gen-ml`, `gen-swe`) |
| `etp-<company>-<role>` | Company-specific tailored CV (e.g. `etp-google-swe`) |

---

## Project Structure

```
.
├── main.tex          # LaTeX CV entry point
├── sections/         # Modular CV sections
├── .vita/
│   ├── companies.json  # Company registry (source of truth)
│   ├── config.json     # CLI configuration with defaults
│   └── logs/           # Application logs
├── vita/
│   ├── assets/         # Built-in prompts and skills
│   ├── commands/       # CLI command logic
│   └── utils.py        # Shared utilities
└── README.md
```

---

## CLI Usage

### Setup

Activate the venv, then `vita` is available directly:

```sh
.\venv\Scripts\activate
vita <command>
```

> First time only: `pip install -e .` registers `vita` as a binary in the venv.

---

### Initialize a new VITA repo

```sh
vita init
```

Scaffolds `.vita/` with default `config.json` and an empty `companies.json`.

### Create a new tailored CV branch

```sh
vita new etp <company> <role>
```

Example:

```sh
vita new etp google swe
```

Checks the registry, warns if a CV for that company already exists, creates the branch, and updates `companies.json`.

### Build the CV (PDF)

```sh
vita build
```

Auto-detects whether a `.bib` file is present and switches between `latexmk` and the 4-step `pdflatex + biber` flow automatically.

### Check application status

```sh
vita status
```

Example output:

```
📋 VITA Status — Abdellah_HALLOU
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Current branch : etp-google-swe

Companies (3):
  google  [2 CVs]
    ├── etp-google-swe   base: gen-swe   ← you are here
    └── etp-google-ml    base: gen-ml

  meta    [1 CV]
    └── etp-meta-de      base: gen-de

  amazon  [1 CV] [LOCKED]
    └── etp-amazon-swe   base: gen-swe

Base branches:
  gen-ml · gen-swe · gen-de
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### View diff from base CV

```sh
vita diff <company>
```

### Lock / Unlock a company

```sh
vita lock <company>
vita unlock <company>
```

---

## Building LaTeX Manually

### Standard build

```sh
latexmk -pdf -outdir=out main.tex
latexmk -pdf -outdir=out -interaction=nonstopmode -synctex=1 main.tex
```

### Fix bibliography (BibTeX/Biber) issues

Run these steps in order:

```sh
# Step 1 — First pass: writes .aux and .bcf with citekeys
pdflatex -output-directory=out main.tex

# Step 2 — Biber resolves citations
biber --input-directory=out --output-directory=out main

# Step 3 — Second pass: writes bibliography into PDF
pdflatex -output-directory=out main.tex

# Step 4 — Third pass: fixes cross-references
pdflatex -output-directory=out main.tex
```

---

## Configuration

After `vita init`, `.vita/config.json` is created with these defaults:

```json
{
  "author": "",
  "output_dir": "out",
  "output_filename": "cv-{author}.pdf",
  "tex_entry": "main.tex",
  "build_mode": "auto",
  "default_base_branch": "master",
  "strict_mode": false,
  "allow_multiple_per_company": true,
  "warn_on_duplicate": true
}
```

---

## AI Agents & Skills

VITA includes an extensive suite of built-in AI Agent Skills that you can use with Antigravity or any supporting AI assistant. These skills automatically apply industry best practices for specific career tasks.

### Core Resume Optimization
- `resume-writer.md` & `resume-reviewer.md`: Custom general writer and reviewer agents.
- `resume-ats-optimizer.md`: General ATS formatting and optimization.
- `resume-bullet-writer.md` & `resume-quantifier.md`: Improve and quantify your experience bullets.
- `resume-section-builder.md` & `resume-formatter.md`: Help restructuring specific resume sections.
- `resume-version-manager.md`: Manage multiple versions of your resume.

### Job Targeting & Strategy
- `job-description-analyzer.md`: Analyze a job description, calculate a match score, and identify gaps.
- `resume-tailor.md`: Customize your CV specifically for a target role.
- `offer-comparison-analyzer.md`: Compare multiple job offers objectively.

### Supporting Documents & Prep
- `cover-letter-generator.md`: Write highly personalized cover letters.
- `linkedin-profile-optimizer.md`: Optimize your LinkedIn profile to match your CV.
- `interview-prep-generator.md`: Generate STAR interview stories based on your CV bullets.
- `salary-negotiation-prep.md`: Get strategies for offer negotiation.

### Specialized Roles & Extensions
- **Industry specific**: `tech-resume-optimizer.md`, `executive-resume-writer.md`, `academic-cv-builder.md`
- **Career transitions**: `career-changer-translator.md`
- **Portfolios/Creative**: `creative-portfolio-resume.md`, `portfolio-case-study-writer.md`
- **References**: `reference-list-builder.md`

### How To Use Them

You can invoke any skill by directly referencing it when prompting your AI assistant (skills are located in the package directory):

**Example 1: Tailoring for a job**
> "Please use the `resume-tailor` skill to update my `main.tex` file so it aligns with this job description I just pasted."

**Example 2: Fixing your bullet points**
> "Analyze the experience section in my CV using the `resume-bullet-writer` skill and suggest improvements."

**Example 3: Interview prep**
> "I have an interview tomorrow at Google. Use `interview-prep-generator` to help me generate STAR stories from my resume."

---

## Design Philosophy

- **Warn, don't block** — duplicate company CVs trigger a warning, not a hard stop (use `--force` to override, or set `locked: true` per company)
- **CLI enforces naming** — branch names are normalized automatically (`data engineer` → `de`)
- **Registry is the truth** — `companies.json` is the authoritative record, not branch names alone