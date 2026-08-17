"""Hermeticity guards for the pytest suite itself (2026-08-16 plan, Tasks 1-2).

Production ``_main`` reads ``os.getenv("BERA_CHAIN_API_KEY")`` (DI-3 env gate)
to enable the optional on-chain fetch. The developer's interactive shell
exports that key, so ``_main``-calling tests inherited a live Etherscan V2
fetch, read the gitignored wallet registry, and paid ~9s per test. The
``_pin_hermetic_env`` autouse fixture in ``tests/conftest.py`` is the primary
gate that keeps the suite environment-invariant.

The ``_forbid_network`` autouse fixture (also in ``tests/conftest.py``) is the
tripwire gate: any outbound DNS resolution or socket connect during an
unmarked test fails loudly. Deliberately-live tests opt out via
``@pytest.mark.network``; there is no environment-variable bypass.
"""

import os
import socket
from pathlib import Path

import pytest

_PINNED_KEY = "BERA_CHAIN_API_KEY"
_SIMULATED_USER_SHELL_VALUE = "simulated-user-shell-key"

# Simulate the user's interactive shell exporting the key before pytest runs:
# module import happens at collection time, BEFORE any fixture setup, so this
# reaches the test body exactly as an inherited shell variable would.
_ORIGINAL_VALUE = os.environ.get(_PINNED_KEY)
if _ORIGINAL_VALUE is None:
    os.environ[_PINNED_KEY] = _SIMULATED_USER_SHELL_VALUE
# Post-condition capture (NOT a re-derivation of the precondition above): pin
# the EFFECT of the preamble so the guard test below fails if the simulation
# body is deleted while the module otherwise stays importable.
_KEY_PRESENT_AT_IMPORT = os.environ.get(_PINNED_KEY) is not None


def _restore_pre_module_env() -> None:
    """Restore the pre-module environment (remove the simulated key if we set it)."""
    if _ORIGINAL_VALUE is None:
        os.environ.pop(_PINNED_KEY, None)
    else:
        os.environ[_PINNED_KEY] = _ORIGINAL_VALUE


@pytest.fixture(scope="module", autouse=True)
def _schedule_env_restore(request: pytest.FixtureRequest) -> None:
    """Register the env restore on the pytest session config (not module teardown).

    A function-scoped ``simulated_user_shell(monkeypatch)`` fixture is NOT a
    valid replacement for the import-time simulation: pytest instantiates
    autouse fixtures of a scope before non-autouse ones of the same scope, so
    the requested fixture's ``setenv`` would land AFTER ``_pin_hermetic_env``
    deleted the key and the key would be present in the test body, inverting
    the test's meaning. Import-time simulation keeps the key present before
    the autouse pin runs (requirement (a)).

    ``request.config.add_cleanup`` (instead of ``teardown_module``) makes the
    restore robust to teardown ordering and errors once any test in this
    module has run: session-config cleanups execute at session exit even if
    module teardown machinery is skipped or fails. Full-deselection of the
    module via ``-k`` remains bounded by the autouse env pin deleting the key
    before every other test (as the review finding itself notes).
    """
    request.config.add_cleanup(_restore_pre_module_env)


class TestEnvPin:
    def test_import_time_api_key_removed_by_fixture(self):
        assert _PINNED_KEY not in os.environ, (
            "autouse _pin_hermetic_env must delete the import-time (user-shell) "
            "BERA_CHAIN_API_KEY before the test body runs; the suite is not env-invariant"
        )

    def test_import_time_simulation_reached_collection(self):
        assert _KEY_PRESENT_AT_IMPORT, (
            "neither the import-time simulation nor a real user-shell BERA_CHAIN_API_KEY "
            "was present at collection; deleting the module-preamble simulation silently "
            "drops the only always-on exercise of the user-shell delenv branch"
        )

    def test_explicit_setenv_in_body_wins(self, monkeypatch):
        monkeypatch.setenv(_PINNED_KEY, "opt-in")
        assert os.environ[_PINNED_KEY] == "opt-in"

    def test_env_pin_fixture_registered_autouse(self):
        conftest_path = Path(__file__).resolve().parents[1] / "conftest.py"
        source = conftest_path.read_text()
        assert "def _pin_hermetic_env(monkeypatch" in source, (
            "tests/conftest.py must define the _pin_hermetic_env(monkeypatch) fixture"
        )
        assert "@pytest.fixture(autouse=True)\ndef _pin_hermetic_env(monkeypatch" in source, (
            "_pin_hermetic_env must be registered autouse (decorator directly above the "
            "function) so no test can silently disconnect it; the bare decorator substring "
            "would be satisfied by any other autouse fixture (e.g. _forbid_network)"
        )
        assert 'monkeypatch.delenv("BERA_CHAIN_API_KEY", raising=False)' in source, (
            "_pin_hermetic_env must use the exact raising=False delenv so both the "
            "'never set' (agent shell) and 'set' (user shell) paths are handled"
        )


class TestNetworkGuard:
    def test_unmarked_dns_resolution_blocked(self):
        with pytest.raises(AssertionError, match="network"):
            socket.getaddrinfo("example.com", 443)

    def test_unmarked_legacy_dns_blocked(self):
        with pytest.raises(AssertionError, match="network"):
            socket.gethostbyname("example.com")
        with pytest.raises(AssertionError, match="network"):
            socket.gethostbyname_ex("example.com")

    def test_unmarked_socket_connect_blocked(self):
        sock = socket.socket()
        try:
            with pytest.raises(AssertionError, match=r"outbound network to \('127\.0\.0\.1', 1\)"):
                sock.connect(("127.0.0.1", 1))
        finally:
            sock.close()

    def test_unmarked_connect_ex_blocked(self):
        sock = socket.socket()
        try:
            with pytest.raises(AssertionError, match=r"outbound network to \('127\.0\.0\.1', 1\)"):
                sock.connect_ex(("127.0.0.1", 1))
        finally:
            sock.close()

    def test_unmarked_udp_sendto_blocked(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with pytest.raises(AssertionError, match=r"outbound network to \('127\.0\.0\.1', 1\)"):
                sock.sendto(b"x", ("127.0.0.1", 1))
        finally:
            sock.close()

    def test_unmarked_udp_sendmsg_blocked(self):
        # sendmsg can carry a literal destination on an unconnected socket
        # (no connect()/DNS), so the guard must block it and name the address.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with pytest.raises(AssertionError, match=r"outbound network to \('127\.0\.0\.1', 9\)"):
                sock.sendmsg([b"x"], [], 0, ("127.0.0.1", 9))
        finally:
            sock.close()

    def test_unmarked_udp_send_fds_blocked(self):
        # socket.send_fds forwards to sendmsg with the same positional layout;
        # the module-level helper is patched, so no transmission occurs.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with pytest.raises(AssertionError, match=r"outbound network to \('127\.0\.0\.1', 9\)"):
                socket.send_fds(sock, [b"x"], [], 0, ("127.0.0.1", 9))
        finally:
            sock.close()

    @pytest.mark.network
    def test_network_marker_opts_out(self):
        sock = socket.socket()
        sock.settimeout(2)
        try:
            with pytest.raises(OSError, match=r"refused|timed out"):
                sock.connect(("127.0.0.1", 1))
        finally:
            sock.close()
