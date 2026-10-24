---
name: python-stdlib
description: Python 3.9+ standard library and pyproject packaging for public-social-account-analyzer. Use for stdlib-only scripts, type hints, package configuration, and import paths.
---

# Python stdlib Skill

Scope: `skill/scripts/` (collect.py, run_pipeline.py, immutable_workspace.py, task_contract.py, collectors/*, etc.), `pyproject.toml`, and import path configuration (`skill/scripts`, `skill/scripts/collectors`).

## Invariants

- Project runs on **Python 3.9+ stdlib only** — no third-party runtime imports in production code.
- Tests need `pytest` (dev dependency only).
- `pyproject.toml`: `[tool.setuptools.packages.find] include = ["skill*"]`; `[tool.pytest.ini_options] pythonpath = ["skill/scripts", "skill/scripts/collectors"]`.
- Naming: `snake_case` modules/functions/vars, `PascalCase` classes, `UPPER_SNAKE_CASE` constants, leading underscore for private helpers.
- Type hints on public interfaces; short docstrings stating the behavioral contract.
- One-way dependency flow: entry scripts → adapters → shared helpers (`base.py`, `_constants.py`, `_utils.py`). Adapters import `browser_backend` only when fallback is enabled.
- `git diff --check` before commits; no formatter/linter configured — match surrounding 4-space indentation.

## When to use

- Adding or editing stdlib-only Python scripts under `skill/scripts/`.
- Changing `pyproject.toml`, import paths, or package discovery.
- Touching naming conventions, type hints, or docstring style.

## Verification

- `python3 -m pytest tests/ -q` full regression; focused tests for changed modules.
- `python3 -m py_compile` on changed scripts (or `python3 -m compileall`).
- `git diff --check` before commit.
- Never commit OAuth tokens, signed URLs, raw private data, or generated `workspace/` payloads.
