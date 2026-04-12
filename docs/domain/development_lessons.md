# Development Lessons — Common Issues and Prevention Strategies

Canonical reference for recurring patterns observed during code fixes in this codebase.
Agents should read this alongside the main instruction rules in CLAUDE.md.

---

## 1. Code Quality and Duplication
- Always check for duplicate test methods or functions before adding new code.
- Command: `grep -n "def method_name" . -r`

## 2. Type Safety and Annotations
- Add `@override` to methods overriding base class methods.
- Annotate all class attributes with types unless class is marked `@final`.
- Prefix unused parameters with `_param`; use bare `_` for completely ignored params.

```python
class MyClass:
    attr1: Type1

    @override
    def method_name(self, _param: UnusedType) -> None:
        pass
```

## 3. String and Code Formatting
- Keep f-strings on single lines or use explicit parenthesised concatenation.
- Break long lines with `(...)` grouping:

```python
# Good
error_message = (
    f"Error in row {row_number}: "
    f"Expected format X, got Y"
)
```

## 4. Function and Method Design
- Use parameter names that match the interface being implemented.
  Example: `lambda optionstr: optionstr` not `lambda option: option` for ConfigParser.
- Required vs Optional: use required parameters for essential data; only use defaults when a sensible default exists.

## 5. Dependencies and Imports
- Check all imports against declared dependencies before submitting.
- Import from public `__all__` exports; avoid `_private` imports in tests unless necessary.
- Run tests early to catch missing imports.

## 6. Testing Best Practices
- 3-tier structure: unit (`tests/unit/`) → integration (`tests/integration/`) → e2e (`tests/end_to_end/`).
- Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`.
- Unit tests may access internal functions; integration/e2e use only public APIs.

## 7. Refactoring and Maintenance
- Make small incremental changes and run `uv run pytest` after each one.
- Remove temporary scripts immediately after use.

## 8. Error Handling and Logging
- Always include row numbers and problematic data in error messages.
- Use `from e` exception chaining to preserve original context.
- Logging: parameterised format (`%s`). Exceptions: f-strings. See §1 Instruction Rules for full detail.

## 9. API Design for Production vs Testing
- Do not add features or parameters solely to satisfy tests; adjust tests to match production patterns instead.
- When tests need special handling, first try to make tests reflect real usage before adding complexity to production code.

## 10. Test Path and Fixture Management
- Never use `Path(__file__).parent.parent` in tests — breaks when files move.
- Always use pytest fixtures (`tmp_path`, `tmp_path_factory`) for file operations:

```python
# ✅ GOOD
@pytest.fixture
def test_file(tmp_path: Path) -> Path:
    f = tmp_path / "test.csv"
    f.write_text("test,data")
    return f
```

## 11. Simplify Unnecessary Complexity (YAGNI)
- Remove parameters that always have the same value (e.g. `require_trades_section=True` → hardcode it).
- Do not add features "just in case".

## 12. Excel/openpyxl Column Width
- openpyxl stores formulas as strings; `cell.value` returns the raw formula (e.g., `"=USD EUR*(1234.56)"`), not the computed result.
- Auto-width logic must skip formula cells (`cell.data_type == "f"`) and size columns from headers + non-formula values only.
- The crypto sheet auto-width block has a missing `default=0` in `max()` that raises `ValueError` on empty columns — always provide `default=0` when calling `max()` on a generator.

## 13. Test Real Behavior, Not Implementation Details
- Verify that a feature works end-to-end, not just that it returns a certain value.
- Use realistic test data; check that integrated components produce correct outputs.

---

## Pre-Commit Checklist

1. `uv run pytest -x` — stop on first failure
2. `uv run ruff check . --fix` — auto-fix linting
3. `uv run basedpyright src/ tests/` — type checking
4. `uv run ruff check . --select=E501` — line length
5. Confirm all imports have matching dependencies
6. `grep -r "Path(__file__)" tests/` — no fragile test paths
7. Review new parameters: are any always constant? (remove them)
8. Do tests verify actual functionality or just return values?
9. Remove temporary files or scripts
10. Update relevant docs if API changed

## Quality Assurance Commands

```bash
uv run ruff check . --select=E501     # Line length
uv run ruff check . --select=F401     # Unused imports
uv run ruff check . --select=PL       # Pylint rules

grep -r "Path(__file__)" tests/ || echo "No fragile test paths"
grep -r "= True" src/ --include="*.py" | grep -v "def " | head -10

uv run pytest -m unit          # Fast feedback during development
uv run pytest -m integration   # Before committing
uv run pytest -m e2e           # Before release

grep -n "def test_" tests/ | cut -d: -f3 | sort | uniq -d  # Duplicate test names
```
