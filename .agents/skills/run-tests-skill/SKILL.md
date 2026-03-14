---
name: run-project-tests
description: Run tests after code changes. Use this skill proactively after modifying source code, before committing, or when user mentions testing.
allowed-tools: Bash, Read
model: haiku
---

# Run Project Tests

Automatically run the appropriate test suite after making any code changes to ensure nothing is broken.

## Quick Commands

### Fast Feedback (Development)
```bash
uvx pytest -m unit -x              # Unit tests, stop on first failure
uvx pytest -m unit                 # All unit tests
uvx pytest tests/unit/domain/      # Domain layer tests
uvx pytest tests/unit/application/ # Application layer tests
```

### Pre-commit Validation
```bash
uvx pytest -m unit && uvx ruff check . --fix && uvx ruff format .
```

### Full Test Suite
```bash
uvx pytest                         # All tests (unit + integration + e2e)
uvx pytest -m integration          # Integration tests only
uvx pytest --cov=src --cov-report=html  # With coverage report
```

## Workflow

1. **After code change**: `uvx pytest -m unit -x`
2. **Before commit**: `uvx pytest -m unit && uvx ruff check . --fix && uvx ruff format .`
3. **Fix failures immediately** - don't accumulate broken tests

## Project-Specific Notes

- Uses **UV** package manager - always use `uvx pytest` (not `pytest` directly)
- **3-tier test architecture**: unit (fast), integration (medium), e2e (slow)
- Test config: `tests/config.ini`
- Test data uses `tmp_path` fixture (no hardcoded paths)

## Detailed Documentation

For comprehensive testing strategy, architecture details, troubleshooting, and best practices, see [AGENTS.md - Testing Strategy](../../AGENTS.md#testing-strategy).
