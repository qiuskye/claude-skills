---
name: repo-onboard
description: Fast, token-cheap orientation report for an unfamiliar repository using a deterministic git-based pipeline (file map, hot files, entry points, activity) with strict read budgets. Use when the user says things like "explícame este repo", "onboarding", "qué hace este proyecto", "explain this repo", or "give me a tour of this codebase".
---

# repo-onboard

Produce an orientation report for the current repository **in minutes**, not hours.
The pipeline below is deterministic and cheap: almost everything comes from `git`
metadata and shell one-liners. You only read file contents in Step 5, and only
within the stated line budgets.

**Hard rules:**

- Do NOT read whole files "to understand them". Respect the budgets in Step 5.
- Do NOT recurse into `node_modules`, `dist`, `build`, `vendor`, `.git`, lockfiles.
- Run the commands of Steps 1-4 before reading any file content. Batch
  independent commands in parallel where possible.
- If the directory is not a git repo, fall back to `find . -type f | head -200`
  for Step 1, skip Steps 2 and 4, and say so in the report.

## Step 1 — Map the terrain (no file reads)

```bash
git ls-files | head -200
git ls-files | sed -n 's/.*\.\([a-zA-Z0-9]*\)$/\1/p' | sort | uniq -c | sort -rn | head -10
```

Detect the project type from key files in the listing — read **only** the
manifests that exist, nothing else:

| File present              | Project type      | Manifest to read            |
|---------------------------|-------------------|-----------------------------|
| `package.json`            | Node/JS/TS        | `package.json`              |
| `pyproject.toml`          | Python            | `pyproject.toml`            |
| `requirements.txt` only   | Python (legacy)   | `requirements.txt`          |
| `go.mod`                  | Go                | `go.mod`                    |
| `Cargo.toml`              | Rust              | `Cargo.toml`                |
| `pom.xml` / `build.gradle`| Java/JVM          | first 60 lines only         |
| `composer.json`           | PHP               | `composer.json`             |
| `Gemfile`                 | Ruby              | `Gemfile`                   |
| `Dockerfile` / `compose*` | (deploy signal)   | first 30 lines only         |

Monorepos: if you see multiple manifests (e.g. `packages/*/package.json`),
note the workspace layout but read only the root manifest.

## Step 2 — Hot files (the heart of the repo)

```bash
git log --pretty=format: --name-only -200 | sort | uniq -c | sort -rn | head -15
```

The most-touched files are where the real work happens. Filter out noise
(lockfiles, generated files, CHANGELOG) mentally. Keep the top 3 *source*
files for Step 5.

## Step 3 — Entry points (heuristics, no reads yet)

By project type, look for these in the Step 1 listing:

- **Node/TS:** `main`/`bin`/`exports` and `scripts` in `package.json` (already
  read in Step 1); `src/index.*`, `src/main.*`, `src/app.*`, `src/cli.*`.
- **Python:** `[project.scripts]` / `[tool.poetry.scripts]` in `pyproject.toml`;
  `__main__.py`, `main.py`, `app.py`, `cli.py`, `manage.py`, `wsgi.py`.
- **Go:** `main.go`, `cmd/*/main.go`.
- **Rust:** `src/main.rs`, `src/bin/*`, `[[bin]]` in `Cargo.toml`.
- **Generic:** `Makefile` targets, `docker-compose` services, CI workflow names
  (`.github/workflows/*.yml` filenames only).

List candidates; do not open them unless they are also hot files.

## Step 4 — Activity and people

```bash
git log --oneline -15
git shortlog -sn | head -5
git log --reverse --format=%ad --date=short | head -1   # repo age (first commit)
git log -1 --format=%ad --date=short                     # last commit
```

This tells you: is the repo alive, who owns it, and what the team is working
on right now.

## Step 5 — Targeted reads (the ONLY content reads, strict budgets)

1. `README*` — **first 60 lines only**.
2. The **3 most relevant hot files** from Step 2 — **first 80 lines each**.
   Prefer files that are both hot AND entry-point candidates.

Total budget: ~300 lines of file content for the whole pipeline. If a file is
binary or generated, skip it and pick the next hot file.

## Step 6 — Report (fixed sections, in the user's language)

Produce exactly these sections:

1. **Qué es** — 2-3 sentences: purpose, project type, stack.
2. **Arquitectura en 5 líneas** — max 5 lines describing how the pieces fit.
3. **Dónde está cada cosa** — short table: concern → directory/file.
4. **Por dónde empezar a tocar** — the 2-3 files a newcomer should open first
   (hot files + entry points), and the command to run/test the project if the
   manifest revealed one.
5. **Riesgos / deuda visible** — only what the data shows: stale repo, single
   contributor (bus factor), huge hot file, no tests visible, no README, etc.

**Anti-hallucination rule:** every architectural claim must cite the file it
comes from, e.g. "uses Express (`package.json`)", "auth lives in
`src/middleware/auth.ts` (hot file, 14 commits)". If you did not see evidence
for a claim in Steps 1-5, either omit it or mark it explicitly as a guess
("probablemente X — no verificado"). Never invent directories, frameworks, or
behavior.
