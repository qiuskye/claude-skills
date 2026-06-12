---
name: token-diet
description: >
  Frugal-mode operating rules that minimize token consumption without losing
  output quality. Activate when the user says "modo ahorro", "token diet",
  "gasta pocos tokens", "save tokens", "low token mode", or otherwise asks to
  reduce token/context usage. Stays active for the rest of the session unless
  the user turns it off ("modo normal", "token diet off").
---

# Token Diet

Operate as a frugal worker: every read, command, and word must earn its place.
Quality is non-negotiable — frugality means cutting waste, not corners.
These rules are operative and measurable, not aspirational.

## Core rules

### 1. Surgical reading

- NEVER read a whole file when a `grep -n` / glob can locate the relevant
  section first. Locate, then read only that range with `offset`/`limit`.
- Hard cap: **max 100 lines per initial read** of any file. Extend with a
  second targeted read only if the first slice proves insufficient.
- NEVER re-read a file already read in this session. Trust the harness file
  state; after an Edit/Write, do not re-open the file to "verify".
- Before any Read, ask: "do I know the line range?" If not, run a search
  first (Rule 2).

### 2. Search before read

Mandatory pipeline for locating anything:

1. `grep -rn "<pattern>" <scoped-dir> | head -5` (or Grep tool with
   `head_limit: 5`) — always cap output, never dump full matches.
2. Decide from those ≤5 hits which file:line matters.
3. Read ONLY that range (`offset` = hit line − ~10, `limit` ≤ 100).

Scope every search to the narrowest plausible directory; never grep from the
repo root when a subdirectory is known. Prefer symbol-aware tools (LSP,
ctags) over text search when available — they cost fewer round trips.

### 3. Cheap delegation

- Any sweep task (search across many files, "where is X used", inventory,
  naming-convention hunts) goes to a subagent (e.g. `Explore`), NOT the main
  context.
- The subagent prompt MUST state: "Return ONLY the conclusion in 1–5 lines
  (paths + line numbers). No file contents, no dumps, no excerpts."
- Never duplicate delegated work: once dispatched, wait for the result
  instead of searching in parallel yourself.
- One sweep = one subagent. Batch related questions into a single prompt
  rather than spawning several agents for fragments of the same question.

### 4. Lean responses

- TL;DR first: open every answer with a 1–2 line conclusion, details after
  (and only if they add information).
- NEVER paste code that already exists in the diff or that the user just
  showed you. Reference it as `path/to/file.ts:42` instead of quoting blocks.
- No restating the question, no narrating routine tool use, no summaries of
  code you merely read. Show code only when the exact text is load-bearing
  (a bug, a signature, a proposed snippet not yet written anywhere).

### 5. Proportional verification

- Run tests targeted at the change: the specific test file, or
  `--grep`/`-k`/`-t` filtered to the touched behavior.
- NEVER run the full suite, full lint, or full build unless the user asks or
  the change is genuinely cross-cutting (build config, shared core module).
- One verification pass per change. If it passes, stop — no "just to be
  sure" re-runs.

### 6. Explicit budget

- Before starting a task, estimate the steps and announce the plan:
  "Plan: N reads, M commands" (e.g. "Plan: 3 partial reads, 2 commands").
- Track against it. If actual usage exceeds **2× the announced budget**,
  STOP: tell the user the budget is blown, state why, and propose a
  re-scoped plan before continuing. Do not silently grind on.

### 7. Savings report

At the end of every task, append one line of metrics so the user sees the
savings:

> Token diet: X files read (partial), Y commands, Z subagents. Budget: kept /
> exceeded (N×).

## Anti-patterns (hard prohibitions)

- Reading lockfiles or generated artifacts: `package-lock.json`,
  `yarn.lock`, `pnpm-lock.yaml`, `Cargo.lock`, `poetry.lock`, `dist/`,
  `build/`, `.min.js`, vendored deps, `node_modules/` — grep them at most,
  never read.
- `cat` / full Read of any file >500 lines. Slice it or grep it.
- Repeated screenshots of the same UI state; one screenshot per distinct
  state, ever.
- `git diff` without paths, `git log` without `-n`, `ls -R` from the root,
  unscoped `find` — always bound output (`head`, `-n`, path args).
- Re-running a command whose output is already in context.
- Pasting tool output back to the user verbatim when one line summarizes it.
- Exploratory "let me read a few files to get familiar" reads with no
  specific question attached.

## When NOT to use

Suspend this skill (and say so) when frugality would compromise correctness:

- **Security reviews / audits** — exhaustive coverage is the point; partial
  reads create blind spots.
- **Exhaustive audits or migrations** that require touching/verifying every
  file (license sweeps, API deprecation across the codebase).
- **Debugging where prior partial reads already misled you** — escalate to
  full reads of the suspect files.
- The user explicitly asks for completeness over cost.

When suspended for one task, announce it ("token diet paused: security
review requires full reads") and resume afterwards.
