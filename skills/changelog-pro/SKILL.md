---
name: changelog-pro
description: Generates reliable, hallucination-free changelogs and release notes directly from git history, with Conventional Commits parsing, noise filtering, and a semver suggestion. Use when the user asks for a "changelog", "release notes", or "what has changed since" a tag, commit, or date.
---

# changelog-pro

Produce a changelog that is **fully traceable to real commits**. Every line in the
output must map to at least one actual commit hash. Follow this pipeline as a
deterministic sequence — do not skip, reorder, or improvise steps.

## Inputs (optional, ask only if ambiguous)

- `BASE` — a tag, commit, or `--since` date to diff from. Default: resolved in Step 1.
- `AUDIENCE` — `user` (default), `dev`, or `marketing`. See "Audience modes".
- `PATH` — a subdirectory for monorepo scoping. See "Monorepo support".

> **SECURITY — never interpolate refs or paths unquoted.** Git tag/ref names can
> contain shell metacharacters (`$`, backtick, `(`, `)`, `|`, `>`, `<`, spaces).
> A malicious tag like `v5-$(rm -rf ~)` would execute code if pasted into an
> unquoted command. **Always** assign refs/paths/dates to a shell variable, wrap
> every use in double quotes (`"$BASE"`, `"$PATH"`, `"$DATE"`), and validate any
> ref before using it (see Step 1). Do not improvise the commands below.

## Pipeline

### Step 1 — Resolve the base ref

```bash
BASE="$(git describe --tags --abbrev=0 2>/dev/null)"
```

- If this prints a tag, use it as `BASE` — but first **validate** it. Reject any
  ref containing shell metacharacters, then confirm it points at a real commit:
  ```bash
  if printf '%s' "$BASE" | grep -q '[$`|<>()[:space:]]'; then
    echo "Refusing unsafe ref: $BASE" >&2; exit 1
  fi
  git rev-parse --verify --quiet -- "$BASE^{commit}" >/dev/null || {
    echo "Not a valid commit: $BASE" >&2; exit 1
  }
  ```
- If there are **no tags** (`BASE` is empty), fall back to the first commit:
  ```bash
  BASE="$(git rev-list --max-parents=0 HEAD | tail -1)"
  ```
- If the user supplied a `--since` date instead (e.g. "what changed since last
  Monday"), assign it to a variable and quote it in Step 2
  (`DATE="last Monday"; git log --since="$DATE" ...`), skipping the
  `"$BASE"..HEAD` range.

### Step 2 — Collect the raw commit data

```bash
git log "$BASE"..HEAD --no-merges --pretty=format:'%h%x1f%an%x1f%s%x1f%b%x1e'
```

Fields are: short hash, author name, subject, body — separated by the **unit
separator** `\x1f` (`%x1f`), and each commit record terminated by the **record
separator** `\x1e` (`%x1e`). These control characters never appear in normal
commit text, so they survive multiline bodies (`%b`) that contain `|` or
newlines. Parse by splitting the whole output on `\x1e` into records, then each
record on `\x1f` into the 4 fields; a single record may span multiple lines.
This output is the **single source of truth** for the rest of the pipeline.
Never invent entries that are not in it.

For monorepo scoping, append `-- "$PATH"` (quoted; see "Monorepo support").

### Step 3 — Parse Conventional Commits into sections

Classify each commit by its subject prefix (`type(scope): message`):

| Prefix | Section | Order |
|---|---|---|
| `!` after type, or footer `BREAKING CHANGE:` in body | 🚨 Breaking Changes | 1 (always at the very top) |
| `feat` | ✨ Features | 2 |
| `fix` | 🐛 Fixes | 3 |
| `perf` | ⚡ Performance | 4 |
| `refactor` | 🔧 Internal | 5 |
| `docs`, `chore`, `ci`, `build`, `test`, `style` | **Excluded** — include only for `AUDIENCE=dev` (under 🔧 Internal) | 6 |

Commits that do not follow Conventional Commits: classify by intent from the
subject line (e.g. "add X" → Features, "fix Y" → Fixes); if genuinely unclear,
put them under 🔧 Internal rather than guessing a user-facing meaning.

Rewrite each subject as a clear, past-or-present-tense bullet. Keep the scope as
a bold prefix when it adds context: `**auth:** added session refresh`.

### Step 4 — Filter noise

Drop entirely:

- Version bump commits (`bump version`, `v1.2.3`, `release 1.2.3`, changes to
  version files only).
- Merge commits (already excluded by `--no-merges`, but also drop subjects
  starting with `Merge `).
- Bot commits (author contains `[bot]`, `dependabot`, `renovate`, `github-actions`).

Dependency updates that survive (human-made `chore(deps)` / `build(deps)`):
collapse them into a **single line**, e.g.
`- Updated dependencies (abc1234, def5678, 9abcdef)`.

### Step 5 — Resolve links

Get the repository URL once:

```bash
git remote get-url origin
```

Normalize it to `https://github.com/OWNER/REPO` (strip `.git`, convert
`git@github.com:OWNER/REPO.git` SSH form). Then:

- Replace every `#123` issue/PR reference in bullets with
  `[#123](https://github.com/OWNER/REPO/issues/123)`.
- Add a compare link under the version heading, using the resolved `$BASE`
  value: `https://github.com/OWNER/REPO/compare/$BASE...HEAD`
  (use the new tag instead of `HEAD` if the user named one).
- If the remote is not GitHub (or there is no remote), keep plain-text `#123`
  references and omit the compare link — do not fabricate URLs.

### Step 6 — Suggest a semver bump

Based on the sections that ended up non-empty:

- Any 🚨 Breaking Changes → **major**
- Else any ✨ Features → **minor**
- Else → **patch**

Report the suggestion explicitly, e.g. "Suggested bump: 1.4.2 → 1.5.0 (minor:
new features, no breaking changes)". If the project is pre-1.0, note that
breaking changes conventionally bump the minor instead.

### Step 7 — Anti-hallucination verification (mandatory)

1. Every bullet **must** cite at least one real short hash in parentheses at the
   end of the line: `- Added dark mode toggle (a1b2c3d)`.
2. After drafting, re-read the Step 2 output and cross-check **every line** of
   the draft against it:
   - Hash not present in the git log → **delete the bullet**.
   - Bullet describes something the cited commit does not contain → rewrite it
     to match the commit, or delete it.
3. Never merge two unrelated commits into one invented "summary" feature. A
   bullet may cite multiple hashes only when the commits are genuinely the same
   change (e.g. a fix and its follow-up).

This step is not optional. A shorter, verified changelog beats a richer,
speculative one.

### Step 8 — Idempotent write to CHANGELOG.md

Follow the [Keep a Changelog](https://keepachangelog.com) format:

- If `CHANGELOG.md` exists:
  - Releasing a version → insert a new `## [X.Y.Z] - YYYY-MM-DD` section
    directly below the `## [Unreleased]` heading (create `[Unreleased]` if
    missing).
  - Not releasing → merge the bullets into the existing `## [Unreleased]`
    section.
  - **Never duplicate**: before inserting, check whether a bullet citing the
    same hash already exists in the target section; skip those.
- If `CHANGELOG.md` does not exist, create it with the standard Keep a
  Changelog header, then the new section.
- Show the user the final rendered section before (or while) writing it.

## Audience modes

| `AUDIENCE` | Tone | Included sections |
|---|---|---|
| `user` (default) | Plain language, benefit-oriented, no internal jargon | Breaking, Features, Fixes, Performance |
| `dev` | Technical, keeps scopes and refactor details | All sections, including Internal and docs/chore/ci/build |
| `marketing` | Enthusiastic but factual highlights, 3–6 bullets max | Features and major Fixes only; no hashes in the prose, but keep a hash-cited appendix for verification |

Even in `marketing` mode, Step 7 still applies internally: do not announce
anything that lacks a backing commit.

## Monorepo support

When the user asks for a changelog of a single package/app, scope every
`git log` invocation with a pathspec:

```bash
PATH_SPEC="packages/my-app"
git log "$BASE"..HEAD --no-merges \
  --pretty=format:'%h%x1f%an%x1f%s%x1f%b%x1e' -- "$PATH_SPEC"
```

Always quote both the ref (`"$BASE"`) and the pathspec (`"$PATH_SPEC"`) — see the
SECURITY note above; a path is just as injectable as a ref.

Also prefer package-scoped tags (`my-app@1.2.0`, `my-app-v1.2.0`) as `BASE` when
they exist (validate them exactly as in Step 1):
```bash
BASE="$(git describe --tags --abbrev=0 --match 'my-app*' 2>/dev/null)"
```
Write to the package's own `CHANGELOG.md` if one exists there.

## Credits

The idea for this skill is inspired by `changelog-generator` from
[ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills).
That project ships without a license, so this skill is a **clean-room
reimplementation written from scratch** — no text or structure was copied.
Formatting conventions follow [keepachangelog.com](https://keepachangelog.com)
and [Conventional Commits](https://www.conventionalcommits.org).
