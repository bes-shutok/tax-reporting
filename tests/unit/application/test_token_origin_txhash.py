"""Task 4: TokenOriginResolver reads ``TxHash`` (not ``TxSrc``) as the tx id.

Plan: ``docs/history/plans/2026-08-02-on-chain-tx-tagger.md`` Task 4 (B1; folds
review F4). Pre-migration ``token_origin.py:171,278`` reads
``row.get("TxSrc", "")`` AS the transaction hash, citing a comment
"Real Koinly exports store the transaction hash in TxSrc" which is demonstrably
wrong: measured on the personal Koinly data, withdrawal rows have
``TxHash`` = the per-transaction hash and ``TxSrc`` = the sender's wallet
address (identical across all rows from one wallet). Indexing withdrawals by
``TxSrc`` therefore collapses every withdrawal from one wallet into a single
dict key - a latent per-wallet collision bug that mis-attributes ``from_asset``
for any deposit whose wallet sent >1 LP withdrawal.

These four tests pin the post-migration behavior. They use the SAME production
wiring (``conftest.build_origin_resolver`` -> ``build_transactions_from_th`` ->
``TokenOriginResolver.__init__`` -> ``_build_lookup`` -> ``_index_withdrawal`` /
``_index_row``) so they exercise the real call sites the migration touches
(``_index_withdrawal`` at ``token_origin.py:171`` and ``_index_row`` at
``token_origin.py:278``). Per AGENTS.md crypto-tests rule, TH rows are built
in-test (committed synthetic TH has empty ``TxHash``/``TxSrc``/``TxDest`` by
Design Invariant #1; the migration's delta is observable only on rows with
POPULATED columns, so the committed CSV must NOT be modified).

TDD ordering: all four are written RED first (pre-migration), then the
migration at ``token_origin.py:171,278`` flips them GREEN.
"""

from __future__ import annotations

from pathlib import Path

from tax_reporting.domain.token_origin import AcquisitionMethod
from tests.conftest import build_origin_resolver

# Synthetic TH header matching the real Koinly transaction-history export.
# Column order (indices 16/17/18) is load-bearing: ``TxSrc``=16, ``TxDest``=17,
# ``TxHash``=18 (the bug was reading index 16 as the hash).
_TH_HEADER = (
    "Transaction report 2025\n"
    "\n"
    "Date,Type,Tag,Sending Wallet,Sent Amount,Sent Currency,Sent Cost Basis,"
    "Receiving Wallet,Received Amount,Received Currency,Received Cost Basis,"
    "Fee Amount,Fee Currency,Gain (EUR),Net Value (EUR),Fee Value (EUR),"
    "TxSrc,TxDest,TxHash,Description"
)

# Synthetic values that mirror the real Koinly shape (verified on personal
# data): a 66-char EVM hash in TxHash, a 42-char wallet address in TxSrc.
# These are purely synthetic test values; no real hashes/addresses are used.
_WALLET_A = "0xabcdabcdabcdabcdabcdabcdabcdabcdabcdabcd"
_WALLET_B = "0x1234567890abcdef1234567890abcdef12345678"
_DEST = "0x9b5d0000abcd9b5d0000abcd9b5d0000abcd9b5d"
_TX_HASH_1 = "0x7fceaaaa7fceaaaa7fceaaaa7fceaaaa7fceaaaa7fceaaaa7fceaaaa7fcexao1"
_TX_HASH_2 = "0x7fcebbbb7fcebbbb7fcebbbb7fcebbbb7fcebbbb7fcebbbb7fcebbbb7fcxbo2"


def _write_th(tmp_path: Path, data_rows: str) -> Path:
    """Write a synthetic Koinly TH CSV to ``tmp_path`` and return its Path.

    Rows are written with the production header (incl. the ``TxSrc``/``TxDest``/
    ``TxHash`` columns at indices 16/17/18) so the production reader and the
    resolver's ``_index_withdrawal`` / ``_index_row`` see populated values.
    """
    path = tmp_path / "th_txhash.csv"
    path.write_text(f"{_TH_HEADER}\n{data_rows}", encoding="utf-8")
    return path


def _build_resolver(path: Path):
    """Build a TokenOriginResolver via the production wiring (Family D)."""
    return build_origin_resolver(path)


class TestTokenOriginTxHash:
    """Post-migration, ``_index_withdrawal`` / ``_index_row`` read ``TxHash``.

    Each test writes a synthetic TH where ``TxHash`` carries the per-tx hash and
    ``TxSrc``/``TxDest`` carry wallet addresses (the REAL Koinly shape), then
    asserts the resolver keys/pairs by ``TxHash``.
    """

    def test_koinly_withdrawal_indexed_by_txhash_after_migration(self, tmp_path: Path) -> None:
        """``_index_withdrawal`` keys the withdrawal record by ``TxHash``.

        A single ``crypto_withdrawal`` / ``Liquidity out`` row whose ``TxHash``
        is the per-tx hash and ``TxSrc`` is the wallet address must, after
        migration, appear in ``_withdrawal_by_txhash`` under the ``TxHash`` key
        (NOT under the ``TxSrc`` wallet-address key, as pre-migration).
        """
        path = _write_th(
            tmp_path,
            f"2025-03-09 11:48:47 UTC,crypto_withdrawal,Liquidity out,Cetus,10,WBERA-HONEY-LP,50,"
            f"Cetus,0,,,0,,,0,0,{_WALLET_A},{_DEST},{_TX_HASH_1},remove liquidity\n",
        )
        resolver = _build_resolver(path)

        # Post-migration: keyed by TxHash (the per-tx identifier). Pre-migration
        # this key is absent (the row keyed under the wallet address instead).
        assert _TX_HASH_1 in resolver._withdrawal_by_txhash, (
            f"Withdrawal must be indexed by TxHash ({_TX_HASH_1[:12]}...) after migration; "
            f"got keys: {list(resolver._withdrawal_by_txhash.keys())}"
        )
        # And NOT keyed under the wallet address (the latent collision key).
        assert _WALLET_A not in resolver._withdrawal_by_txhash, (
            f"Withdrawal must NOT be indexed by TxSrc (wallet {_WALLET_A[:12]}...); "
            f"that is the per-wallet collision key the migration removes."
        )
        records = resolver._withdrawal_by_txhash[_TX_HASH_1]
        assert len(records) == 1
        assert records[0].sent_currency == "WBERA-HONEY-LP"

    def test_koinly_deposit_lookup_pairs_correctly_after_migration(self, tmp_path: Path) -> None:
        """A deposit and its withdrawal sharing ``TxHash`` pair correctly.

        ``_resolve_lp_provenance`` looks up the withdrawal by the deposit's
        ``TxHash``; when both share the ``TxHash`` the deposit resolves to the
        withdrawal's ``sent_currency`` (the LP token), with high confidence.
        """
        path = _write_th(
            tmp_path,
            # Withdrawal: LP tokens sent. Hash in TxHash, wallet A in TxSrc.
            f"2025-03-09 11:48:47 UTC,crypto_withdrawal,Liquidity out,Cetus,10,CETUS-LP,50,"
            f"Cetus,0,,,0,,,0,0,{_WALLET_A},{_DEST},{_TX_HASH_1},remove liquidity\n"
            # Deposit: tokens received, sharing TxHash but a DIFFERENT TxSrc
            # (wallet B). Pre-migration the lookup keyed on TxSrc so the deposit
            # would NOT find the withdrawal (falling back to "LP position");
            # post-migration the shared TxHash pairs them.
            f"2025-03-09 11:48:47 UTC,crypto_deposit,Liquidity out,,,,,"
            f"Cetus,100,SSUI,200,,,,,,{_WALLET_B},{_DEST},{_TX_HASH_1},remove liquidity\n",
        )
        resolver = _build_resolver(path)
        origin = resolver.resolve("2025-03-09", "SSUI", "Cetus")

        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        # The deposit's from_asset is the withdrawal's sent LP token, resolved
        # via the shared TxHash (post-migration). High confidence because the
        # deposit carries a non-empty tx_hash.
        assert origin.acquired_from_asset == "CETUS-LP", (
            f"Deposit must pair with the withdrawal sharing TxHash; "
            f"expected from_asset='CETUS-LP', got {origin.acquired_from_asset!r}. "
            f"Pre-migration (keyed on TxSrc) this falls back to 'LP position'."
        )
        assert origin.acquired_from_platform == "Cetus"
        assert origin.confidence == "high"

    def test_multi_withdrawal_per_wallet_no_longer_collide(self, tmp_path: Path) -> None:
        """Two LP withdrawals from ONE wallet (same ``TxSrc``) but DIFFERENT
        ``TxHash``es depositing different pairs resolve to DISTINCT
        ``from_asset`` values.

        This is the load-bearing regression test for the latent per-wallet
        collision bug (review F1-r2 + F3-r3). Pre-migration both withdrawals
        index under the shared ``TxSrc`` wallet-address key, so BOTH deposits
        resolve to the SAME (wrong, merged) ``from_asset``. Post-migration each
        indexes under its own ``TxHash``, so each deposit resolves its own pair.
        Asserts on the observable ``from_asset`` delta, NOT raw dict keying.
        """
        path = _write_th(
            tmp_path,
            # Withdrawal 1: sends WBERA+HONEY LP pair, wallet A, hash 1.
            f"2025-03-09 11:48:47 UTC,crypto_withdrawal,Liquidity out,Cetus,10,WBERA-HONEY-LP,50,"
            f"Cetus,0,,,0,,,0,0,{_WALLET_A},{_DEST},{_TX_HASH_1},remove liquidity 1\n"
            # Withdrawal 2: sends WBTC+WBERA LP pair, SAME wallet A, hash 2.
            f"2025-03-09 11:48:47 UTC,crypto_withdrawal,Liquidity out,Cetus,7,WBTC-WBERA-LP,35,"
            f"Cetus,0,,,0,,,0,0,{_WALLET_A},{_DEST},{_TX_HASH_2},remove liquidity 2\n"
            # Deposit 1: receives WBERA, pairs with withdrawal 1 by TxHash 1.
            f"2025-03-09 11:48:47 UTC,crypto_deposit,Liquidity out,,,,,"
            f"Cetus,100,WBERA,200,,,,,,{_WALLET_A},{_DEST},{_TX_HASH_1},dep1\n"
            # Deposit 2: receives WBTC, pairs with withdrawal 2 by TxHash 2.
            f"2025-03-09 11:48:47 UTC,crypto_deposit,Liquidity out,,,,,"
            f"Cetus,80,WBTC,160,,,,,,{_WALLET_A},{_DEST},{_TX_HASH_2},dep2\n",
        )
        resolver = _build_resolver(path)

        origin_1 = resolver.resolve("2025-03-09", "WBERA", "Cetus")
        origin_2 = resolver.resolve("2025-03-09", "WBTC", "Cetus")

        # Post-migration: each deposit resolves its OWN pair (no collision).
        assert origin_1.acquired_from_asset == "WBERA-HONEY-LP", (
            f"Deposit 1 (TxHash 1) must resolve to its own pair 'WBERA-HONEY-LP'; "
            f"got {origin_1.acquired_from_asset!r}. Pre-migration this collides with "
            f"deposit 2 under the shared wallet key."
        )
        assert origin_2.acquired_from_asset == "WBTC-WBERA-LP", (
            f"Deposit 2 (TxHash 2) must resolve to its own pair 'WBTC-WBERA-LP'; "
            f"got {origin_2.acquired_from_asset!r}. Pre-migration this collides with "
            f"deposit 1 under the shared wallet key."
        )
        assert origin_1.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        assert origin_2.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL

    def test_onchain_row_resolves_via_txhash(self, tmp_path: Path) -> None:
        """An on-chain-derived row (``TxHash``=real hash, ``TxSrc``=from_address)
        resolves its LP provenance via ``TxHash`` and does NOT fall back to the
        ``"LP position"`` sentinel.

        This models the on-chain adapter's projection: ``tx_hash`` carries the
        on-chain tx id, ``TxSrc`` carries the from_address. token_origin must
        find the paired withdrawal under ``TxHash``.
        """
        path = _write_th(
            tmp_path,
            # Withdrawal (on-chain shape): hash in TxHash, from_address (wallet A) in TxSrc.
            f"2025-03-09 11:48:47 UTC,crypto_withdrawal,Liquidity out,Berachain,10,WBERA-HONEY-LP,50,"
            f"Berachain,0,,,0,,,0,0,{_WALLET_A},{_DEST},{_TX_HASH_1},onchain lp out\n"
            # Deposit (on-chain shape): same TxHash, but a DIFFERENT from_address
            # (wallet B) in TxSrc. Pre-migration (TxSrc keying) the deposit would
            # NOT find the withdrawal; post-migration the shared TxHash pairs them.
            f"2025-03-09 11:48:47 UTC,crypto_deposit,Liquidity out,,,,,"
            f"Berachain,100,HONEY,200,,,,,,{_WALLET_B},{_DEST},{_TX_HASH_1},onchain lp out\n",
        )
        resolver = _build_resolver(path)
        origin = resolver.resolve("2025-03-09", "HONEY", "Berachain")

        assert origin.acquisition_method == AcquisitionMethod.LIQUIDITY_WITHDRAWAL
        # Must resolve via TxHash to the withdrawal's LP token - NOT fall back
        # to the "LP position" sentinel (which fires when no withdrawal is found
        # under the lookup key).
        assert origin.acquired_from_asset == "WBERA-HONEY-LP", (
            f"On-chain deposit must resolve via TxHash to 'WBERA-HONEY-LP'; "
            f"got {origin.acquired_from_asset!r}. A 'LP position' fallback here "
            f"means the lookup keyed on the wrong column."
        )
        assert origin.acquired_from_asset != "LP position"
