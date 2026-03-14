---
name: fix-issues
description: Fix code quality issues and test failures iteratively. Use when user mentions fixing issues, linting errors, type errors, or failing tests.
allowed-tools: Bash, Read, Edit, Write
model: sonnet
---

# Fix Code Quality Issues

Automatically fix ruff linting issues, basedpyright errors/warnings, and test failures through iterative cycles until all issues are resolved.

## When to Use

- User mentions "fix issues", "fix linting", "fix errors"
- User asks to resolve type checking errors
- User wants to fix failing tests
- User requests code quality improvements
- After significant refactoring or feature additions

## Workflow

Execute this iterative process until all issues are resolved:

### 1. Fix Linting Issues
```bash
uvx ruff check . --fix
```
- Ruff will auto-fix most issues
- Review any remaining issues that require manual intervention

### 2. Fix Type Errors
```bash
uvx basedpyright src/ tests/
```
- Review and fix type errors
- Add missing type annotations
- Resolve import issues

### 3. Run Tests
```bash
uvx pytest -m unit -x
```
- Run unit tests first (fast feedback)
- Fix any failing tests
- Once unit tests pass, run full suite: `uvx pytest`

### 4. Repeat Until Clean
```bash
# Iterate until all checks pass:
uvx ruff check . && uvx basedpyright src/ tests/ && uvx pytest
```

## Success Criteria

All of the following must pass:
- ✅ `uvx ruff check .` - No linting errors
- ✅ `uvx basedpyright src/ tests/` - No type errors
- ✅ `uvx pytest` - All tests passing

## Order of Operations

**Important**: Fix in this order for efficiency:
1. **Linting first** - Quick auto-fixes, often resolves type issues too
2. **Type checking second** - Catches issues linting missed
3. **Tests last** - Run on clean code, avoid cascading failures

## Common Issues

### Ruff Issues
- Unused imports: `F401` - Remove or add to `__all__`
- Line length: `E501` - Break long lines
- Type annotations: Missing or incorrect types

### Type Errors
- Missing imports: Add dependencies with `uv add`
- Incorrect types: Fix type annotations
- Return types: Add explicit return types

### Test Failures
- Logic errors: Fix implementation
- Missing fixtures: Update test setup
- Import errors: Check module paths

## Project Context

This project uses:
- **Ruff** for linting and formatting
- **basedpyright** for type checking (Python 3.13 target)
- **pytest** for testing (unit/integration/e2e)
- **UV** for package management

For detailed development workflow, see [AGENTS.md - Development Best Practices](../../AGENTS.md#development-best-practices).
