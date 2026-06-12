# 🧰 claude-skills — hand-crafted skills for Claude Code

![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-blue.svg)
![Made for Claude Code](https://img.shields.io/badge/made%20for-Claude%20Code-orange.svg)

A small, curated collection of skills for [Claude Code](https://claude.com/claude-code),
written from scratch with an emphasis on determinism and verifiability rather
than vibes.

## What is a skill?

A skill is a folder containing a `SKILL.md` file (YAML frontmatter with a
`name` and a `description`, followed by Markdown instructions) plus any
supporting scripts or resources. Claude Code reads the description to decide
*when* the skill applies, then follows the body as its playbook for *how* to do
the task — turning a vague request like "write me a changelog" into a
repeatable procedure. See the official
[anthropics/skills](https://github.com/anthropics/skills) repository for the
format specification and reference examples.

## Skills

| Skill | What it does | When it activates |
|---|---|---|
| [`changelog-pro`](skills/changelog-pro/SKILL.md) | Generates verified changelogs/release notes from git history: Conventional Commits parsing, noise filtering, issue/compare links, semver suggestion, idempotent `CHANGELOG.md` writes — every bullet must cite a real commit hash | "changelog", "release notes", "what has changed since…" |
| [`eda-quicklook`](skills/eda-quicklook/SKILL.md) | Profiles a CSV with a zero-dependency Python script (types, missing %, stats, ASCII histograms, top values, warnings), then interprets the problems and suggests next steps | "explore this CSV", "EDA", "what does this data look like" |

## Installation

```bash
git clone https://github.com/qiuskye/claude-skills ~/.claude/skills-qiuskye
cp -r ~/.claude/skills-qiuskye/skills/changelog-pro ~/.claude/skills/
cp -r ~/.claude/skills-qiuskye/skills/eda-quicklook ~/.claude/skills/
| [`repo-onboard`](skills/repo-onboard/) | Understand any unknown repo in minutes — git-driven map, hot files, entry points, cited report | "explain this repo", "onboarding" |
| [`token-diet`](skills/token-diet/) | Frugal mode: surgical reads, grep-first, hard token budgets with end-of-task metrics | "modo ahorro", "token diet" |
```

Claude Code picks up skills from `~/.claude/skills/` automatically; start a new
session and they are available. To install for a single project instead, copy
the folders into `<project>/.claude/skills/`.

## Design principles

- **Deterministic pipelines.** Each skill is a numbered sequence of exact
  commands, not a mood board. Two runs on the same repository or dataset should
  produce the same result.
- **Anti-hallucination checks.** Output must be traceable to ground truth:
  `changelog-pro` requires every bullet to cite a real commit hash and ends
  with a mandatory cross-check against `git log`; `eda-quicklook` constrains
  interpretation to what the profiler actually printed.
- **Stdlib only.** Bundled scripts run on a bare `python3` — no `pip install`,
  no environment drift, nothing to break on a colleague's machine.

## Credits

- [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills)
  for the conceptual inspiration behind `changelog-pro` (its
  `changelog-generator` ships without a license, so this repository contains a
  clean-room reimplementation — no text was reused).
- [obra/superpowers](https://github.com/obra/superpowers) and
  [anthropics/skills](https://github.com/anthropics/skills) as references for
  the skill format and authoring style.
- [keepachangelog.com](https://keepachangelog.com) and
  [Conventional Commits](https://www.conventionalcommits.org) for the
  changelog conventions.

## License

[MIT](LICENSE)
