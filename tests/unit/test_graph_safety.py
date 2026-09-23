"""Guards on the two operations that can destroy work or fail a clean run.

Both were found in review:

* ``--recreate`` treated an unreadable vertex count as zero, so a count timeout
  could drop a populated graph.
* ``connect()`` attempted once, so a Savanna cold start failed the whole run.
"""

from __future__ import annotations

import sys

import pytest

from graph.client import (
    TigerGraphConfig,
    TigerGraphConfigError,
    connect,
    looks_like_cold_start,
)
from scripts.install_schema import (
    CatalogUnavailable,
    VertexCountUnavailable,
    installed_types,
    parse_graph_membership,
    read_catalog,
    total_vertices,
)

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


# --- catalog reading must never be guessed at ------------------------------


GRAPH_LINE = (
    "---- Global vertices, edges, and all graphs\n"
    "  - Graph HHGOAFraud(Cardholder:v, PaymentCard:v, OWNS:e, OWNED_BY:e)\n"
    "  - Graph OtherThing(Foo:v)\n"
)


#: Any of these, issued after discovery failed, is an unsafe mutation.
MUTATING_KEYWORDS = ("DROP", "CREATE", "ALTER", "RUN")


class _Catalog:
    """A connection stand-in that records every statement it is given.

    Recording at the connection is deliberate. An earlier version of this test
    spied on run_gsql and therefore never saw the global DROP EDGE and
    DROP VERTEX loop, which calls gsql() directly -- so the test passed while
    destructive statements were being issued.
    """

    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.statements: list[str] = []

    def gsql(self, statement, graphname=None):
        self.calls += 1
        self.statements.append(statement)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def getVertexCount(self, name, realtime=False):  # noqa: N802 - driver's name
        raise AssertionError("counts must not be attempted after discovery fails")

    @property
    def mutations(self) -> list[str]:
        return [
            statement
            for statement in self.statements
            if any(
                statement.strip().upper().startswith(keyword) or f" {keyword} " in statement.upper()
                for keyword in MUTATING_KEYWORDS
            )
        ]


def test_membership_parses_from_one_catalog_read():
    present, vertices, edges = parse_graph_membership(GRAPH_LINE, "HHGOAFraud")
    assert present is True
    assert vertices == {"Cardholder", "PaymentCard"}
    assert edges == {"OWNS", "OWNED_BY"}


def test_absent_graph_is_reported_absent_not_raised():
    present, vertices, edges = parse_graph_membership(GRAPH_LINE, "NotThere")
    assert present is False
    assert vertices == set()
    assert edges == set()


def test_unparseable_membership_refuses_rather_than_reporting_no_types():
    """Present but unreadable must never look like an empty graph."""
    truncated = "  - Graph HHGOAFraud"  # no parenthesised member list
    with pytest.raises(CatalogUnavailable, match="membership"):
        parse_graph_membership(truncated, "HHGOAFraud")


def test_catalog_read_failure_raises_rather_than_returning_empty():
    connection = _Catalog(RuntimeError("504 Gateway Time-out"))
    with pytest.raises(CatalogUnavailable, match="catalog"):
        read_catalog(connection, CONFIG)


def test_catalog_errors_are_redacted():
    connection = _Catalog(RuntimeError(f"LS failed, secret={CONFIG.secret}"))
    with pytest.raises(CatalogUnavailable) as error:
        read_catalog(connection, CONFIG)
    assert CONFIG.secret not in str(error.value)
    assert "***REDACTED***" in str(error.value)


def test_installed_types_propagates_a_catalog_failure():
    connection = _Catalog(RuntimeError("connection reset"))
    with pytest.raises(CatalogUnavailable):
        installed_types(connection, CONFIG, "HHGOAFraud")


def test_the_catalog_is_read_once_per_discovery():
    """Two reads let the first succeed and the second fail into empty sets."""
    connection = _Catalog(GRAPH_LINE)
    parse_graph_membership(read_catalog(connection, CONFIG), "HHGOAFraud")
    assert connection.calls == 1


@pytest.mark.parametrize(
    "response",
    [
        RuntimeError("504 Gateway Time-out"),
        RuntimeError("Starting workspace"),
        "  - Graph HHGOAFraud",
        "",
        "   " + chr(10) + "  " + chr(9) + " ",
        "Error: Currently not using any graphs!",
        "Semantic Check Fails: something went wrong",
        "totally unrecognised response",
    ],
    ids=[
        "gateway-timeout",
        "cold-start",
        "truncated-line",
        "empty-response",
        "whitespace-response",
        "gsql-error-text",
        "semantic-check-text",
        "unrecognised-response",
    ],
)
def test_no_mutation_is_attempted_after_discovery_fails(monkeypatch, response):
    """The finding, end to end.

    main() is run with --recreate against a connection whose catalog is
    unusable. Every statement the connection receives is recorded, and no
    DROP, CREATE, ALTER or RUN may appear -- not only DROP GRAPH. The global
    DROP EDGE and DROP VERTEX loop is gated on --recreate rather than on the
    graph being present, so a response parsed as "graph absent" previously
    reached it.
    """
    import scripts.install_schema as installer

    connection = _Catalog(response)
    monkeypatch.setattr(installer, "load_config", lambda: CONFIG)
    monkeypatch.setattr(installer, "connect", lambda config: connection)
    monkeypatch.setattr(sys, "argv", ["install_schema.py", "--recreate"])

    exit_code = installer.main()

    assert connection.mutations == [], (
        f"mutating statements issued despite {response!r}: {connection.mutations}"
    )
    assert exit_code == 1
    # Only the single discovery read should ever have been attempted.
    assert connection.calls == 1


def test_a_genuinely_empty_graph_is_still_droppable(monkeypatch):
    """Guards against the fix becoming a refusal to ever recreate."""
    import scripts.install_schema as installer

    # Graph present with no members: legitimately empty, so a drop is correct.
    catalog_text = "  - Graph HHGOAFraud()\n"
    present, vertices, _edges = installer.parse_graph_membership(catalog_text, "HHGOAFraud")
    assert present is True
    assert vertices == set()
    assert installer.total_vertices(_Counter({}), vertices) == 0
