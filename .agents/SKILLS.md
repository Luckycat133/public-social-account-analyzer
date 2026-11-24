# Curated Project Skill Routing

This repository keeps task-specific Skills in `.agents/skills` (Codex and other IDE entry points) and mirrors them under `.claude/skills` (Claude Code entry point). Both directories hold the same maintained content so Codex and Claude read identical Skills.

This table records the Skills added for public-social-account-analyzer. Load only the Skill whose trigger matches the current task. Existing repository instructions (`CLAUDE.md`, `AGENTS.md`) and the user's current request take priority over a Skill.

| Skill | Use here for |
|---|---|
| `public-social-account-analyzer` | End-to-end public social account analysis workflow, CLI invocation contracts, evidence gates, and deliverable format |
| `python-stdlib` | Python 3.9+ stdlib-only scripts, pyproject packaging, type hints, package configuration, import paths |
| `pytest` | Pytest regression tests, mock platform transport, URL validation, stop_reason semantics, immutable workspace boundaries, report escaping |
| `social-media-analysis` | Platform adapters (Bilibili/Douyin/Weibo/Xiaohongshu), content classification, business insights, taxonomy drafts, immutable analysis workspaces |
| `web-scraping` | Public web scraping, collection adapters, Cookie handling, URL allowlist/canonicalization, browser fallback, rate limiting, retry strategies |
| `python-pypi-package-builder` | End-to-end PyPI packaging, PEP 440/SemVer versioning, and OIDC Trusted Publishing |
| `directory-submissions` | Skill marketplaces (`skills.sh`, ClawHub, plugin manifests) and directory submissions |
| `clawhub` | ClawHub skill publishing, syncing, and verification workflows |
| `github-release` | GitHub Releases, SemVer tagging, and Keep a Changelog release workflows |

## Maintenance rules

- Keep domain and implementation Skills in the project instead of the global Codex Skill directory.
- Preserve project-specific Skills as the source of truth; do not replace them with an archived global copy.
- Prefer links for IDE-specific discovery so Codex and Claude read the same maintained content.
- Add or expand a Skill only when it captures repeatable project knowledge not already clear from code or repository documentation.
- For small changes, run focused checks first and expand testing only when failures, risk, or new scope justify it.
