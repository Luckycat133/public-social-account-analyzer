# Repository Guidelines

## Project Structure & Module Organization

The Agent Skill lives in `skill/`. Its contract is defined by `skill/SKILL.md`; Python entry points are in `skill/scripts/`, platform adapters are in `skill/scripts/collectors/`, domain contracts are in `skill/references/`, and the dashboard template is in `skill/assets/`. Keep offline evaluation fixtures under `skill/evals/datasets/`. Pytest coverage lives in `tests/`, while architecture notes, plans, and acceptance records belong in `docs/`. `workspace/` task directories are generated artifacts, not source.

## Build, Test, and Development Commands

This project has no compiled build step and keeps production code on the Python standard library.

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -e ".[dev]"       # install Python 3.9+ project and pytest
python3 -m pytest tests/ -q              # run the complete regression suite
python3 -m pytest tests/test_douyin.py -q # run one focused module
python3 skill/scripts/split_dataset.py --verify
```

For a local smoke test, run `python3 skill/scripts/collect.py <public-profile-url> --limit 5 --out workspace/smoke`. Collection may access public pages; normalization, analysis, and rendering must remain deterministic and offline.

## Coding Style & Naming Conventions

Use four-space indentation, standard-library-first imports, type hints for public interfaces, and short docstrings that state behavioral contracts. Name modules, functions, and variables with `snake_case`; classes with `PascalCase`; constants with `UPPER_SNAKE_CASE`; and private helpers with a leading underscore. Preserve the one-way dependency flow from entry scripts to adapters to shared helpers. No formatter or linter is configured, so match surrounding code and run `git diff --check` before submitting.

## Testing Guidelines

Write pytest files as `tests/test_<area>.py` and test functions as `test_<behavior>()`. Add focused regression tests for every behavior change, especially URL validation, nullable evidence, `stop_reason` semantics, immutable workspace boundaries, and report escaping. Mock platform transport in automated tests; do not make live-network success a unit-test requirement. There is no configured line-coverage threshold, but the full suite must pass before review.

## Commit & Pull Request Guidelines

History follows Conventional Commit-style subjects such as `feat(analysis): compare classified content patterns`, `fix(douyin): harden public evidence analysis`, and `docs: publish Douyin capability boundaries`. Keep commits focused and use `feat`, `fix`, `test`, `docs`, `refactor`, or `chore` with an optional scope.

Pull requests should explain the user-visible change, evidence/security implications, and verification commands; link the relevant issue or design document. Include screenshots when `dashboard.html` output changes. Update `README.md`, `USAGE.md`, contracts, and `CHANGELOG.md` when behavior or configuration changes. Never commit OAuth tokens, signed URLs, raw private data, or generated workspaces.
