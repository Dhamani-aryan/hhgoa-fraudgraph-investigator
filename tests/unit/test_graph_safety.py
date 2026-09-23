"""Guards on the two operations that can destroy work or fail a clean run.

Both were found in review:

* ``--recreate`` treated an unreadable vertex count as zero, so a count timeout
  could drop a populated graph.
* ``connect()`` attempted once, so a Savanna cold start failed the whole run.
"""

from __future__ import annotations

import pytest

from graph.client import (
    TigerGraphConfig,
    TigerGraphConfigError,
    connect,
    looks_like_cold_start,
)
from scripts.install_schema import VertexCountUnavailable, total_vertices

CONFIG = TigerGraphConfig(
    host="https://ws.tgcloud.io",
    graphname="HHGOAFraud",
    tg_cloud=True,
    secret="abcd1234efgh5678ijkl9012mnop3456",
)


# --- the recreate guard ----------------------------------------------------


class _Counter:
    """A connection stand-in whose counts can be made to fail."""

    def __init__(self, counts: dict[str, object]):
        self.counts = counts

    def getVertexCount(self, name, realtime=False):  # noqa: N802 - driver's name
        value = self.counts[name]
        if isinstance(value, Exception):
            raise value
        return value


def test_counts_sum_when_every_type_answers():
    connection = _Counter({"A": 3, "B": 4})
    assert total_vertices(connection, {"A", "B"}) == 7


def test_empty_graph_counts_zero():
    connection = _Counter({"A": 0, "B": 0})
    assert total_vertices(connection, {"A", "B"}) == 0


def test_a_failed_count_refuses_rather_than_reporting_zero():
    """The finding: a timeout must not read as an empty graph."""
    connection = _Counter({"A": 0, "B": TimeoutError("read timed out after 60s")})
    with pytest.raises(VertexCountUnavailable, match="B"):
        total_vertices(connection, {"A", "B"})


def test_a_non_numeric_count_refuses():
    connection = _Counter({"A": None})
    with pytest.raises(VertexCountUnavailable):
        total_vertices(connection, {"A"})


def test_failure_on_a_populated_type_still_refuses():
    """Refusal must not depend on which type failed."""
    connection = _Counter({"A": 590_742, "B": RuntimeError("gateway timeout")})
    with pytest.raises(VertexCountUnavailable):
        total_vertices(connection, {"A", "B"})


# --- cold start detection --------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Starting workspace, please wait",
        "<html>Workspace is starting</html>",
        "502 Bad Gateway",
        "504 Gateway Time-out",
        "503 Service Unavailable",
        "('Connection aborted.', RemoteDisconnected(...))",
        "HTTPSConnectionPool: Max retries exceeded",
        "Read timed out",
    ],
)
def test_transient_failures_are_recognised(message: str):
    assert looks_like_cold_start(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "Invalid secret",
        "token is not valid",
        "The graph HHGOAFraud does not exist",
        "Semantic Check Fails",
    ],
)
def test_real_errors_are_not_treated_as_transient(message: str):
    assert looks_like_cold_start(message) is False


# --- connect retry behaviour -----------------------------------------------


@pytest.fixture
def fake_driver(monkeypatch):
    """Install a fake pyTigerGraph whose behaviour the test controls."""
    state = {"attempts": 0, "fail_times": 0, "message": "Starting workspace"}

    class FakeConnection:
        def __init__(self, **kwargs):
            state["attempts"] += 1
            if state["attempts"] <= state["fail_times"]:
                raise RuntimeError(state["message"])

        def getToken(self, secret):  # noqa: N802 - driver's name
            return "token"

    module = type("FakeModule", (), {"TigerGraphConnection": FakeConnection})
    monkeypatch.setitem(__import__("sys").modules, "pyTigerGraph", module)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    return state


def test_connect_succeeds_first_time_when_the_workspace_is_awake(fake_driver):
    connect(CONFIG)
    assert fake_driver["attempts"] == 1


def test_connect_retries_through_a_cold_start(fake_driver):
    """The finding: a resuming workspace must not fail the run."""
    fake_driver["fail_times"] = 3
    retries: list[int] = []

    connect(CONFIG, on_retry=lambda attempt, delay, message: retries.append(attempt))

    assert fake_driver["attempts"] == 4
    assert retries == [1, 2, 3]


def test_backoff_grows_between_attempts(fake_driver):
    fake_driver["fail_times"] = 3
    delays: list[float] = []

    connect(CONFIG, on_retry=lambda attempt, delay, message: delays.append(delay))

    assert delays == sorted(delays)
    assert delays[-1] > delays[0]


def test_connect_gives_up_after_the_attempt_limit(fake_driver):
    fake_driver["fail_times"] = 99
    with pytest.raises(TigerGraphConfigError, match="attempt"):
        connect(CONFIG, max_attempts=3, on_retry=lambda *_: None)
    assert fake_driver["attempts"] == 3


def test_a_real_error_fails_immediately_without_retrying(fake_driver):
    """A wrong secret must not hang a batch run behind five minutes of backoff."""
    fake_driver["fail_times"] = 99
    fake_driver["message"] = "Invalid secret"

    with pytest.raises(TigerGraphConfigError):
        connect(CONFIG, on_retry=lambda *_: None)

    assert fake_driver["attempts"] == 1


def test_the_secret_never_appears_in_a_retry_failure(fake_driver):
    fake_driver["fail_times"] = 99
    fake_driver["message"] = f"Starting workspace; secret={CONFIG.secret}"

    with pytest.raises(TigerGraphConfigError) as error:
        connect(CONFIG, max_attempts=2, on_retry=lambda *_: None)

    assert CONFIG.secret not in str(error.value)
    assert "***REDACTED***" in str(error.value)
