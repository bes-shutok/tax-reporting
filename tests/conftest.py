"""Shared fixtures and configuration for pytest tests."""

import socket
from decimal import Decimal
from pathlib import Path

import pytest


def pytest_configure(config) -> None:
    """Configure custom pytest markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "e2e: mark test as an end-to-end test")


@pytest.fixture(autouse=True)
def _pin_hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete ``BERA_CHAIN_API_KEY`` before every test (2026-08-16 incident).

    Production ``_main`` enables the optional on-chain fetch when the DI-3 env
    gate ``os.getenv("BERA_CHAIN_API_KEY")`` returns a value. The developer's
    interactive shell exports that key, so ``_main``-calling tests inherited a
    live Etherscan V2 fetch (plus the gitignored real wallet registry) at ~9s
    per test while the agent shell (no key) stayed green and fast.
    ``delenv(..., raising=False)`` handles both the "never set" (agent/CI
    shell) and "set" (user shell) paths. Tests that deliberately need the key
    opt in via ``monkeypatch.setenv`` in the test body, which runs after this
    autouse fixture and therefore wins.
    """
    monkeypatch.delenv("BERA_CHAIN_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _forbid_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail outbound DNS resolution and socket connects during every test (2026-08-16 plan).

    Tripwire hermeticity guard: an unmarked test that accidentally reaches the
    network (e.g. a live Etherscan V2 fetch behind a broad ``except``) must
    fail loudly instead of silently burning API quota and reading gitignored
    data. Deliberately-live tests opt out with ``@pytest.mark.network``
    (registered in ``pyproject.toml``); there is deliberately no
    environment-variable bypass. This is a tripwire, not the primary gate for
    the ``_main`` fetch path: ``_main`` swallows the ``AssertionError`` into a
    warning (DI-1 degrade template), so ``_pin_hermetic_env`` above is what
    actually prevents that fetch.
    """
    if "network" in request.keywords:
        return

    def _guard(address: object) -> AssertionError:
        return AssertionError(f"test attempted outbound network to {address}; mark @pytest.mark.network to allow")

    def _blocked_getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> None:
        raise _guard((host, port))

    def _blocked_gethostbyname(host: str, *args: object, **kwargs: object) -> None:
        raise _guard(host)

    def _blocked_gethostbyname_ex(host: str, *args: object, **kwargs: object) -> None:
        raise _guard(host)

    def _blocked_connect(self: socket.socket, address: object) -> None:
        raise _guard(address)

    def _blocked_connect_ex(self: socket.socket, address: object) -> None:
        raise _guard(address)

    def _blocked_sendto(self: socket.socket, *args: object) -> None:
        # sendto(data[, flags], address): the destination is always the last positional.
        raise _guard(args[-1] if args else None)

    def _blocked_sendmsg(self: socket.socket, *args: object) -> None:
        # sendmsg(buffers[, ancdata[, flags[, address]]]): a literal destination
        # can be supplied without connect()/DNS, so block it too; when the full
        # 4-arg positional form is used, the address is the last positional.
        raise _guard(args[-1] if len(args) == 4 else "<connected-socket sendmsg>")

    def _blocked_send_fds(
        sock: socket.socket,
        buffers: object,
        fds: object,
        flags: int = 0,
        address: object = None,
    ) -> None:
        # socket.send_fds(sock, buffers, fds, flags=0, address=None) forwards to
        # sock.sendmsg with the same positional layout.
        raise _guard(address)

    # Module-level DNS stubs (socket.create_connection resolves via these), the
    # connect/connect_ex/sendto/sendmsg methods on the socket class (self is
    # not part of the address), and the send_fds module-level helper (forwards
    # to sendmsg). Any remaining send paths (send/sendall/write) require a
    # prebuilt connected socket, unreachable without connect/DNS (already
    # blocked).
    monkeypatch.setattr(socket, "getaddrinfo", _blocked_getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", _blocked_gethostbyname)
    monkeypatch.setattr(socket, "gethostbyname_ex", _blocked_gethostbyname_ex)
    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", _blocked_sendto)
    monkeypatch.setattr(socket.socket, "sendmsg", _blocked_sendmsg)
    monkeypatch.setattr(socket, "send_fds", _blocked_send_fds, raising=False)


@pytest.fixture
def sample_csv_content() -> str:
    """Provide a sample IB-style CSV content for testing."""
    return (
        "Financial Instrument Information,Header,Asset Category,Symbol,Description,Conid,Security ID,Multiplier\n"
        "Financial Instrument Information,Data,Stocks,AAPL,Apple Inc.,123456,US0378331005,1\n"
        "Financial Instrument Information,Data,Stocks,MSFT,Microsoft Corp.,234567,US5949181045,1\n"
        "Dividends,Header,Currency,Date,Description,Amount\n"
        "Dividends,Data,USD,2023-03-15,AAPL(US0378331005) CASH DIVIDEND 0.24 USD,24.00\n"
        "Dividends,Data,USD,2023-06-15,AAPL(US0378331005) CASH DIVIDEND 0.24 USD,24.00\n"
        "Dividends,Data,USD,2023-03-15,MSFT(US5949181045) CASH DIVIDEND 0.68 USD,68.00\n"
        "Withholding Tax,Header,Currency,Date,Description,Amount,Code\n"
        "Withholding Tax,Data,USD,2023-03-15,AAPL(US0378331005) US TAX,-3.60,,\n"
        "Withholding Tax,Data,USD,2023-03-15,MSFT(US5949181045) US TAX,-10.20,,\n"
        "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,"
        "Date/Time,Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code\n"
        'Trades,Data,Order,Stocks,USD,AAPL,"2023-01-15, 10:30:00",100,150.25,-15025.00,1.00,15026.00,0,O\n'
        'Trades,Data,Order,Stocks,USD,AAPL,"2023-12-15, 15:30:00",-100,160.50,16050.00,1.00,-16051.00,1000.00,C\n'
    )


@pytest.fixture
def sample_csv_file(tmp_path: Path, sample_csv_content: str) -> Path:
    """Create a temporary CSV file with sample content."""
    csv_file = tmp_path / "test_ib_export.csv"
    csv_file.write_text(sample_csv_content)
    return csv_file


@pytest.fixture
def malformed_csv_content() -> str:
    """Provide a malformed CSV content for error testing."""
    return (
        "Financial Instrument Information,Header,Asset Category,Symbol,Description,Conid,Security ID,Multiplier\n"
        "Financial Instrument Information,Data,Stocks,AAPL,Apple Inc.,123456,US0378331005,1\n"
        "Dividends,Header,Currency,Date,Description,Amount\n"
        "Dividends,Data,USD,invalid-date,AAPL - INVALID DATE,10.00\n"
        "Dividends,Data,,2023-06-15,AAPL - MISSING CURRENCY,15.00\n"
        "Withholding Tax,Header,Currency,Date,Description,Amount,Code\n"
        "Withholding Tax,Data,USD,2023-03-15,INVALID SYMBOL US TAX,-5.00,,\n"
    )


@pytest.fixture
def csv_with_missing_isin() -> str:
    """CSV content with missing ISIN for testing error handling."""
    return (
        "Financial Instrument Information,Header,Asset Category,Symbol,Description,Conid,Security ID,Multiplier\n"
        "Financial Instrument Information,Data,Stocks,MISSING,Missing ISIN Security,123456,,1\n"
        "Dividends,Header,Currency,Date,Description,Amount\n"
        "Dividends,Data,USD,2023-03-15,MISSING() CASH DIVIDEND,100.00\n"
        "Withholding Tax,Header,Currency,Date,Description,Amount,Code\n"
        "Withholding Tax,Data,USD,2023-03-15,MISSING US TAX,-15.00,,\n"
        "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,"
        "Date/Time,Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code\n"
        'Trades,Data,Order,Stocks,USD,MISSING,"2023-01-15, 10:30:00",10,100.00,-1000.00,1.00,1001.00,0,O\n'
        'Trades,Data,Order,Stocks,USD,MISSING,"2023-12-15, 15:30:00",-10,110.00,1100.00,1.00,-1101.00,100.00,C\n'
    )


@pytest.fixture
def multi_currency_csv_content() -> str:
    """CSV content with multiple currencies for testing currency conversion."""
    return (
        "Financial Instrument Information,Header,Asset Category,Symbol,Description,Conid,Security ID,Multiplier\n"
        "Financial Instrument Information,Data,Stocks,AAPL,Apple Inc.,123456,US0378331005,1\n"
        "Financial Instrument Information,Data,Stocks,ASML,ASML Holding N.V.,345678,NL0010273215,1\n"
        "Dividends,Header,Currency,Date,Description,Amount\n"
        "Dividends,Data,USD,2023-03-15,AAPL(US0378331005) CASH DIVIDEND USD,24.00\n"
        "Dividends,Data,EUR,2023-03-15,ASML(NL0010273215) CASH DIVIDEND EUR,22.00\n"
        "Withholding Tax,Header,Currency,Date,Description,Amount,Code\n"
        "Withholding Tax,Data,USD,2023-03-15,AAPL(US0378331005) US TAX,-3.60,,\n"
        "Withholding Tax,Data,EUR,2023-03-15,ASML(NL0010273215) TAX,-3.30,,\n"
        "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,"
        "Date/Time,Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code\n"
        'Trades,Data,Order,Stocks,USD,AAPL,"2023-01-15, 10:30:00",10,150.00,-1500.00,1.00,1501.00,0,O\n'
        'Trades,Data,Order,Stocks,EUR,ASML,"2023-01-15, 10:30:00",10,400.00,-4000.00,1.00,4001.00,0,O\n'
    )


# Helper functions for tests
def create_csv_file(tmp_path: Path, content: str) -> Path:
    """Helper to create a CSV file with given content."""
    csv_file = tmp_path / "test_data.csv"
    csv_file.write_text(content)
    return csv_file


def assert_excel_file_exists_and_valid(report_path: Path) -> None:
    """Helper to verify Excel file was created and is valid."""
    assert report_path.exists(), f"Excel report not created at {report_path}"

    import openpyxl

    workbook = openpyxl.load_workbook(report_path)
    assert workbook.active is not None, "Workbook should have an active worksheet"
    workbook.close()


# Test data constants
SAMPLE_DIVIDEND_AMOUNT = Decimal("24.00")
SAMPLE_TAX_AMOUNT = Decimal("3.60")
SAMPLE_QUANTITY = 100
SAMPLE_PRICE = Decimal("150.25")


@pytest.fixture
def operator_origin_defaults():
    """Provide default OperatorOrigin values for crypto sheet tests.

    Returns a dict of defaults that can be updated with overrides.
    Tests can call OperatorOrigin(**operator_origin_defaults()) or
    update the dict before passing to OperatorOrigin().
    """
    return {
        "platform": "TestPlatform",
        "service_scope": "crypto",
        "operator_entity": "Test Entity",
        "operator_country": "US",
        "source_url": "https://example.com",
        "source_checked_on": "2026-01-01",
        "confidence": "high",
        "review_required": False,
    }


# Module-level helper for creating OperatorOrigin objects in crypto sheet tests
_OPERATOR_ORIGIN_DEFAULTS = {
    "platform": "TestPlatform",
    "service_scope": "crypto",
    "operator_entity": "Test Entity",
    "operator_country": "US",
    "source_url": "https://example.com",
    "source_checked_on": "2026-01-01",
    "confidence": "high",
    "review_required": False,
}


def make_operator_origin(**overrides: object):
    """Create OperatorOrigin with defaults plus any overrides.

    This is a module-level helper (not a fixture) for use in crypto sheet tests.
    Import as: from tests.conftest import make_operator_origin

    Note: Import is deferred to avoid circular dependency at conftest load time.
    """
    from tax_reporting.application.crypto_reporting import OperatorOrigin

    defaults = _OPERATOR_ORIGIN_DEFAULTS.copy()
    defaults.update(overrides)
    return OperatorOrigin(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Committed synthetic Koinly 2025 example fixture directories.
#
# Crypto e2e/unit tests read these committed synthetic exports (never the
# gitignored personal ``resources/source/<year>/koinly/``). Each directory is
# isolated to one scenario family (derivatives separation / zero-basis
# materiality / payment-proceeds) per Design Invariant #8 of the
# 2026-06-22-crypto-tests-off-local-fixtures plan.
# ---------------------------------------------------------------------------
KOINLY_2025_EXAMPLE_DIR = Path("resources/source/example/2025/koinly")
KOINLY_2025_ZERO_BASIS_EXAMPLE_DIR = Path("resources/source/example/2025/koinly/zero_basis")
KOINLY_2025_PAYMENT_EXAMPLE_DIR = Path("resources/source/example/2025/koinly/payment")


def build_koinly_jurisdiction(**overrides: object):
    """Build a PT/2025 TaxJurisdictionConfig for the committed Koinly 2025 examples.

    Produces the standard PT 2025 crypto jurisdiction mirroring the production
    decision-point flags. Callers pass keyword overrides for the flags their
    scenario toggles (``separate_derivatives_reporting``,
    ``use_other_gains_report``, ``infer_payment_proceeds``,
    ``zero_basis_review_threshold``, ``zero_basis_review_min_proceeds``,
    ``exclude_loan_repayment_gains``, ``futures_derivatives_taxable``,
    ``timezone``). This consolidates the per-file ``_build_jurisdiction``
    duplicates across the crypto test suite.

    Import is deferred to avoid circular dependency at conftest load time.

    Args:
        **overrides: Keyword arguments forwarded to ``TaxJurisdictionConfig``;
            unknown keys raise ``TypeError`` from the dataclass constructor.

    Returns:
        A configured ``TaxJurisdictionConfig`` instance.
    """
    from zoneinfo import ZoneInfo

    from tax_reporting.infrastructure.config import TaxJurisdictionConfig

    defaults: dict[str, object] = {
        "country": "PT",
        "fiscal_year": 2025,
        "exclude_loan_repayment_gains": True,
        "zero_basis_review_threshold": Decimal("500"),
        "zero_basis_review_min_proceeds": Decimal("10"),
        "futures_derivatives_taxable": True,
        "use_other_gains_report": True,
        "separate_derivatives_reporting": True,
        "infer_payment_proceeds": False,
        "timezone": ZoneInfo("Europe/Lisbon"),
        "route_derivatives_by_counterparty_residency": True,
        "classify_rewards_with_income_codes": True,
    }
    defaults.update(overrides)
    return TaxJurisdictionConfig(**defaults)  # type: ignore[arg-type]


def build_origin_resolver(path: Path | None):
    """Build a ``TokenOriginResolver`` mirroring the production wiring.

    Phase E Task 6 made ``transactions`` and ``config`` required on
    ``TokenOriginResolver``. Tests that construct the resolver directly from a
    TH path (or ``None``) must now supply a ``transactions`` list built via
    the same construction path as ``load_koinly_crypto_report``. That path is
    centralized in ``crypto_reporting.build_transactions_from_th`` (Family D
    single source of truth); this helper delegates to it. Malformed rows are
    skipped silently (test path passes ``skip_logger=None``). For ``None`` or
    non-existent paths, an empty ``transactions`` list and default
    ``TreatmentConfig()`` are returned so the resolver's graceful-degradation
    path is exercised.
    """
    from tax_reporting.application.crypto.treatment_resolver import TreatmentConfig
    from tax_reporting.application.crypto_reporting import build_transactions_from_th
    from tax_reporting.application.token_origin import TokenOriginResolver
    from tax_reporting.domain.exceptions import FileProcessingError

    if path is None or not path.exists():
        return TokenOriginResolver(path, transactions=[], config=TreatmentConfig())
    try:
        transactions = build_transactions_from_th(path, skip_logger=None)
    except (FileProcessingError, OSError, ValueError):
        # All three failure modes are reachable and must degrade gracefully:
        # FileProcessingError/OSError cover missing-path and IO cases;
        # ValueError covers ``_detect_header_index`` raising on a malformed
        # CSV header (pinned by ``test_malformed_transaction_history_returns_empty_lookup``).
        return TokenOriginResolver(path, transactions=[], config=TreatmentConfig())
    return TokenOriginResolver(path, transactions=transactions, config=TreatmentConfig())
