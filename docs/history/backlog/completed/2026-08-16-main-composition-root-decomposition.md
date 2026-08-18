# Backlog: Decompose `_main` into a thin composition root + injectable orchestrator

Status: backlog idea (pre-plan; promote via the `plans` skill when scheduled).
Workflow: when the implementing plan completes, move this file to `docs/history/backlog/completed/`.

## Problem

`_main` (`src/tax_reporting/main.py:114-396`) is a ~280-line god-orchestrator carrying suppressed
complexity lints (`noqa: PLR0912, PLR0915`, too many branches / too many statements). It owns config
loading, the IB pipeline, the crypto pipeline, report writing, the DI-3 env gate
(`os.getenv("BERA_CHAIN_API_KEY")` at `main.py:358`), and a broad `except Exception` degrade template.
Every test that drives it must monkeypatch 5–6 internals (`load_configuration_from_file`,
`_resolve_koinly_directory`, `_infer_tax_year_hint_from_ib_data`, `load_contracts`, `load_lp_snapshot`,
`os.getenv`); `tests/end_to_end/test_on_chain_bera_opted_in.py` alone carries 22 patch sites.

This is the structural root cause of the 2026-08-16 environment-leak incident: tests patched every
seam EXCEPT the env gate, so in a shell exporting `BERA_CHAIN_API_KEY` the suite performed live
Etherscan V2 fetches + gitignored `resources/source/<year>/chains.json` reads at ~9s per test
(incident write-up: `development_lessons.md` entry from plan `2026-08-16-test-hermeticity-guards`;
guards land separately and stay as tripwires).

## Target design (Functional Core, Imperative Shell)

1. **Thin composition root**: `main()` / a reduced `_main()`:
   - reads argv/env/`config.ini` at the edge, exactly once each;
   - decides `fetcher = OnChainFetcher(api_key=...)` if `BERA_CHAIN_API_KEY` is set else `None`
     (emits the existing "not set" WARNING here, at construction time);
   - calls `run_report(source_file=..., output_dir=..., config=..., fetcher=..., now=...)`.
2. **Injectable orchestrator**: `run_report(...)`:
   - takes every collaborator as a parameter (config object, fetcher, clock, report writer);
   - contains NO `os.getenv`, no config-file reads, no argv parsing;
   - `fetcher=None` means skip the on-chain fetch (single policy, testable without env tricks).
3. **Tests retarget**:
   - pipeline-behavior tests call `run_report` with explicit fakes: hermetic by construction,
     no module-attribute patching;
   - a small e2e set exercises `main()` itself with the env pinned
     (guards from `2026-08-16-test-hermeticity-guards` remain as regression tripwires);
   - `test_main_on_chain_wiring.py`'s `_Recorder` pattern becomes a plain injected fake.

## Sequencing / constraints

- Execute `2026-08-16-test-hermeticity-guards` FIRST (staged replacement per
  `plan_quality_guidelines.md`: make the suite safe, then refactor).
- Byte-identical characterization protection: the Koinly byte-identical invariants and the full
  suite green-before/green-after are the safety net; behavior must not drift (same log lines,
  same degrade semantics, same outputs).
- AGENTS.md already mandates thin orchestration (~500 lines): this brings `main.py` (603 lines)
  into compliance rather than waiving it.
- The broad `except Exception` degrade template (DI-1) is preserved but moves into `run_report`;
  the composition root itself fails fast on config errors.

## Acceptance sketch

- `grep -rn "getenv\|environ" src/tax_reporting/main.py` shows reads ONLY in the composition root.
- `_main`/`main` each < ~80 lines; `PLR0912`/`PLR0915` noqa removed from the orchestrator.
- `_main`-calling tests' module-attribute patch count drops to ~0 for `run_report` tests.
- Full suite green before/after; extract.xlsx + rollover CSVs byte-identical on the example
  fixtures; hermeticity validation commands from the guards plan still pass.

## References

- Incident + guards plan: `docs/history/plans/2026-08-16-test-hermeticity-guards.md` and reviews r1–r4.
- Review finding "god-method maybe_substitute" (same family, already fixed) for extraction style.
- Best-practice anchors: Functional Core / Imperative Shell; composition root; env read once at the edge.
