# Plan: Rename to tax-reporting and Reduce Review Flags

## Context

The project has evolved from a shares-only reporting tool to a comprehensive tax reporting tool that includes shares, dividends, and crypto. However, several naming and usability issues remain:

1. **Command naming**: The main entry point is still `shares-reporting` but the project folder is `tax-reporting`, creating confusion
2. **Documentation**: Multiple files still reference "shares-reporting" that need updating
3. **Review flags**: The generated Excel report has excessive review flags that can be automated or better explained

### Current Review Flag Analysis

From analyzing the code and Koinly source data, the following conditions trigger review flags:

**CAPITAL GAINS review flags:**
1. **ByBit platform** - hardcoded `review_required=True` due to "account-region specific" entities
2. **Starknet platform** - hardcoded `review_required=True`
3. **Unknown platforms** - `UNKNOWN_OPERATOR_REVIEW_REQUIRED`
4. **Temporal invalidity** - transactions outside platform's service period
5. **Missing cost basis** - only when cost=0, proceeds>0 (tax impact)

**TAXABLE-NOW - SUPPORT DETAIL review flags:**
1. **ByBit rewards** - inherited from operator origin
2. **Starknet rewards** - inherited from operator origin
3. **Unknown platform rewards** - inherited from operator origin
4. **Foreign tax parsing failure** - when tax field cannot be parsed

### Key Observations

1. **ByBit** is a major exchange with clear operator information (Dubai, UAE). The "account-region specific" concern is valid but we can provide better context.
2. **Starknet** has a known operator (Cayman Islands) with clear service dates - the review flag may be overly conservative.
3. Most other platforms (Kraken, Binance, Gate.io, Wirex) have proper operator origins and don't trigger review flags.

## Validation Commands

```bash
# After renaming, verify the command works
uv run tax-reporting --help 2>/dev/null || uv run tax-reporting

# Verify no remaining references to "shares-reporting" in documentation
grep -r "shares-reporting" --include="*.md" --include="*.py" --include="*.txt" . 2>/dev/null | grep -v ".venv" | grep -v "__pycache__" | grep -v ".git"

# Run tests to ensure nothing broke
uv run pytest -xvs

# Verify the generated report
uv run tax-reporting
# Check resources/result/extract.xlsx for review flags
```

## Task 1: Rename Command Entry Point

**Files:**
- `pyproject.toml`
- `src/shares_reporting/main.py`

- [ ] Update `pyproject.toml`:
  - Change package name from `shares-reporting` to `tax-reporting` (line 2)
  - Change entry point from `shares-reporting` to `tax-reporting` (line 34)
  - Update description to reflect comprehensive tax reporting
  - Update homepage/repository URLs if needed

- [ ] Update `src/shares_reporting/main.py`:
  - Change log file name from `shares-reporting.log` to `tax-reporting.log` (line 39)
  - Update log messages that mention "shares reporting" to "tax reporting"
  - Update module docstring to reflect comprehensive tax reporting

- [ ] Update `CLAUDE.md` and `AGENTS.md`:
  - Replace all `shares-reporting` references with `tax-reporting`
  - Update quick start commands
  - Update development workflow commands
  - Ensure both files remain synchronized

- [ ] Update `README.md`:
  - Replace `shares-reporting` with `tax-reporting` in all examples
  - Update installation and usage instructions
  - Update project description to reflect comprehensive tax reporting

- [ ] Update other documentation files:
  - `docs/domain/shares_reporting_guidelines.md` - consider renaming to `tax_reporting_guidelines.md`
  - `docs/plans/completed/*.md` - update historical references where appropriate
  - Update any remaining references in comments or docstrings

## Task 2: Improve Review Flag Specificity

**Files:**
- `src/shares_reporting/application/crypto_reporting.py`
- `src/shares_reporting/application/persisting.py`

- [ ] **Add specific review reasons** to `CryptoCapitalEntry` and `CryptoRewardIncomeEntry`:
  - Add `review_reason: str | None` field to store the specific reason for review
  - Populate this field when setting `review_required=True` with actionable context

- [ ] **Update ByBit handling**:
  - Keep `review_required=True` but add specific reason: "Bybit uses account-region specific entities; verify your account region matches the operator entity"
  - This preserves the review requirement while making it actionable

- [ ] **Update Starknet handling**:
  - Consider removing `review_required=True` since:
    - Operator is known (Starknet Foundation, Cayman Islands)
    - Service start date is documented (2021-11-16)
    - Chain derivation is reliable
  - If keeping review flag, add specific reason

- [ ] **Improve temporal invalidity messages**:
  - Instead of generic review flag, add specific reason: "Transaction date X is outside known service period [Y, Z] for platform"
  - Include the service period in the reason

- [ ] **Improve missing cost basis handling**:
  - Already well-targeted (only when tax impact exists)
  - Add specific reason when flagged: "Missing cost basis with tax impact - verify cost calculation"

- [ ] **Improve foreign tax parsing failure**:
  - Add specific reason: "Foreign tax field could not be parsed - verify tax credit manually"

- [ ] **Update Excel output** (`persisting.py`):
  - Modify the review flag column to include the specific reason
  - Instead of just "TRUE", show "TRUE: [specific reason]"
  - This makes manual review more efficient

## Task 3: Automate Resolvable Review Flags

**Files:**
- `src/shares_reporting/application/crypto_reporting.py`

- [ ] **ByBit account-region specific**: Consider if we can:
  - Detect the account region from Koinly export (if available)
  - Or document that UAE (Dubai) is the default/primary entity
  - Current approach (review flag) is acceptable given the complexity

- [ ] **Temporal validity edge cases**: Review if the temporal checks are too strict:
  - For long-running platforms (Ethereum, Bitcoin), the lower bound check may be inappropriate
  - Already handled: "When service_start_date is None, skip lower-bound check"
  - Verify this is working correctly for historical transactions

- [ ] **Zero-value disposals**: Ensure these are filtered out:
  - Already done: `if cost_eur == ZERO and proceeds_eur == ZERO and gain_loss_eur == ZERO: continue`
  - Verify no zero-value entries are reaching the report

## Task 4: Update Tests

**Files:**
- `tests/unit/application/test_crypto_reporting.py`
- `tests/integration/test_crypto_reporting_integration.py`
- `tests/end_to_end/test_full_workflow.py`

- [ ] Update tests that reference `shares-reporting` command:
  - Change to `tax-reporting`
  - Update log file references
  - Update any assertions checking command output

- [ ] Add tests for new `review_reason` field:
  - Verify specific reasons are set correctly
  - Verify review flags with reasons appear correctly in Excel output

- [ ] Verify all tests pass after changes:
  - `uv run pytest -xvs`

## Task 5: Documentation and Cleanup

- [ ] Update `docs/domain/crypto_rules.md` if needed to reflect review flag improvements

- [ ] Update `docs/domain/crypto_implementation_guidelines.md` with lessons learned about review flags

- [ ] Update `CLAUDE.md` with new command name and any new patterns

- [ ] Verify `AGENTS.md` stays synchronized with `CLAUDE.md`

- [ ] Consider creating a migration guide for users (if this is a published tool)

## Notes

1. **Breaking change**: Renaming the command is a breaking change for existing users. Document this clearly.

2. **Internal package name**: The Python package `shares_reporting` is separate from the command name. We are NOT renaming the package (which would require moving all source files), only the command entry point.

3. **Review flag philosophy**: The goal is not to eliminate all review flags, but to ensure each flag has a specific, actionable reason. Some review flags are necessary for tax compliance.

4. **ByBit specific**: The review flag for ByBit is intentional and correct - ByBit uses different legal entities depending on user account region. We cannot determine this from Koinly exports alone.
