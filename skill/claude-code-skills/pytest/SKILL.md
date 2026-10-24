---
name: pytest
description: Pytest test suite for public-social-account-analyzer. Use for regression tests, mock platform transport, URL validation, stop_reason semantics, immutable workspace boundaries, and report escaping.
---

# Pytest Skill

Scope: `tests/` directory (`test_*.py`), `tests/conftest.py`, and `pyproject.toml` pytest config (`pythonpath = ["skill/scripts", "skill/scripts/collectors"]`).

## Invariants

- Test file naming: `tests/test_<area>.py`; test function naming: `test_<behavior>()`.
- Add targeted regression tests for each behavior change — especially URL validation, nullable evidence fields, `stop_reason` semantics, immutable workspace boundaries, and report escaping.
- **Mock platform transport in tests; do not make live network success a unit-test requirement.**
- Full suite must be 100% green before commit: `python3 -m pytest tests/ -q`.
- Focused runs: `python3 -m pytest tests/test_douyin.py -q` or `-k classification` filters.

## When to use

- Adding, editing, or deleting tests under `tests/`.
- Changing behavior covered by existing tests (regression verification).
- Touching `conftest.py` or pytest configuration.

## Verification

- `python3 -m pytest tests/ -q` full regression green.
- Focused test for the changed module passes.
- `git diff --check` before commit.
