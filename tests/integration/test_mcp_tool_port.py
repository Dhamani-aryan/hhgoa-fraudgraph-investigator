"""The official TigerGraph MCP server, live, behind the restricted surface.

These tests start the real ``tigergraph-mcp`` server over stdio. Nothing here is
mocked: the inventory is what the server actually served, and every result
came through a live MCP tool call against the workspace.
"""

from __future__ import annotations

import pytest

from graph.client import TigerGraphConfigError, connect, load_config
from graph.mcp_client import (
    MCP_SERVED_TOOLS,
    MCPSession,
    MCPSurfaceError,
    MCPUnavailableError,
)
from graph.tool_port import (
    CallBudget,
    DirectGraphToolPort,
    ForbiddenQueryError,
    GraphUnavailableError,
    MCPGraphToolPort,
    canonical,
)
from retrieval.embeddings import embed

ANCHOR = "2016-11-11 23:46:24"
FLAGGED_TXN = "3450629"
CARD = "C04570-K1"

EQUIVALENCE_CALLS = [
    ("get_case_context_v1", {"flagged_txn_id": FLAGGED_TXN, "as_of_ts": ANCHOR}),
    ("get_card_baseline_v1", {"card_id": CARD, "as_of_ts": ANCHOR}),
    ("extract_temporal_graph_features_v1", {"flagged_txn_id": FLAGGED_TXN, "as_of_ts": ANCHOR}),
    (
        "wcc_shared_origin_v1",
        {"seed_card_id": CARD, "anchor_ts": ANCHOR, "as_of_ts": ANCHOR, "max_hops": 2},
    ),
    (
        "find_similar_closed_cases_v1",
        {
            "query_vector": embed("online purchase burst from a device"),
            "as_of_ts": ANCHOR,
            "k": 3,
            "related_card_ids": [],
        },
    ),
    ("find_policy_chunks_v1", {"query_vector": embed("card testing"), "k": 4}),
]


@pytest.fixture(scope="module")
def config():
    try:
        return load_config()
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")


@pytest.fixture(scope="module")
def session(config, tmp_path_factory):
    stderr = tmp_path_factory.mktemp("mcp") / "stderr.log"
    live = MCPSession(config, stderr_path=stderr).start()
    yield live
    live.close()


@pytest.fixture
def mcp(session):
    return MCPGraphToolPort(session, budget=CallBudget(50))


@pytest.fixture(scope="module")
def direct(config):
    return DirectGraphToolPort(connect(config), config=config, budget=CallBudget(50))


# --- the served surface -------------------------------------------------------


def test_the_server_serves_exactly_the_restricted_surface(session):
    assert sorted(tool.name for tool in session.inventory) == sorted(MCP_SERVED_TOOLS)


def test_only_run_installed_query_is_not_read_only(session):
    """The server marks it destructive because it runs whatever query is named.

    That is why the read-query allowlist is enforced in application code.
    """
    hints = {tool.name: tool.read_only_hint for tool in session.inventory}
    assert hints.pop("tigergraph__run_installed_query") is False
    assert all(hints.values()), hints


def test_the_server_identifies_itself(session):
    assert session.server_info["name"] == "TigerGraph-MCP"


def test_a_tool_outside_the_surface_is_refused_before_it_is_sent(session):
    with pytest.raises(MCPSurfaceError):
        session.call_tool("tigergraph__gsql", {"command": "LS"})


def test_a_server_serving_a_forbidden_tool_fails_startup(config):
    """Fail closed: a wider surface than the restricted one never starts."""
    widened = MCPSession(config, tools=(*MCP_SERVED_TOOLS, "tigergraph__gsql"))
    with pytest.raises(MCPSurfaceError, match="mutating or free-form"):
        widened.start()


# --- a live call ----------------------------------------------------------------


def test_a_live_mcp_query_call_succeeds_and_is_recorded(mcp):
    result = mcp.run_query(
        "get_case_context_v1", {"flagged_txn_id": FLAGGED_TXN, "as_of_ts": ANCHOR}
    )
    assert result.refused is False
    assert result.values["flagged_transaction"][0]["txn_id"] == FLAGGED_TXN
    record = result.record
    assert record.adapter == "mcp"
    assert record.tool == "tigergraph__run_installed_query"
    assert record.ok is True
    assert len(record.trace_id) == 16
    assert record.duration_ms > 0
    assert record.result_bytes > 0


def test_the_server_writes_its_own_call_log(session, mcp):
    mcp.run_query("get_card_baseline_v1", {"card_id": CARD, "as_of_ts": ANCHOR})
    text = session.stderr_path.read_text(encoding="utf-8")
    assert "tool call tool=tigergraph__run_installed_query" in text


def test_the_write_query_cannot_be_reached_through_mcp(mcp, session):
    with pytest.raises(ForbiddenQueryError):
        mcp.run_query("write_investigation_case_v1", {"case_id": "X"})


def test_a_query_refusal_comes_back_as_data(mcp):
    result = mcp.run_query(
        "get_case_context_v1", {"flagged_txn_id": "9999999999", "as_of_ts": ANCHOR}
    )
    assert result.refused is True
    assert result.values["refusal_reason"]


# --- equivalence with the direct fallback --------------------------------------------


@pytest.mark.parametrize(
    ("name", "params"), EQUIVALENCE_CALLS, ids=[c[0] for c in EQUIVALENCE_CALLS]
)
def test_mcp_and_direct_return_the_same_normalized_result(mcp, direct, name, params):
    through_mcp = mcp.run_query(name, params)
    through_direct = direct.run_query(name, params)
    assert through_mcp.record.adapter == "mcp"
    assert through_direct.record.adapter == "direct"
    assert canonical(through_mcp.values) == canonical(through_direct.values)


# --- timeouts -------------------------------------------------------------------------


def test_a_timed_out_mcp_call_is_unavailable_and_the_session_survives(session):
    port = MCPGraphToolPort(session, budget=CallBudget(5), timeout_s=0.001)
    with pytest.raises(GraphUnavailableError, match="timed out"):
        port.run_query("get_card_baseline_v1", {"card_id": CARD, "as_of_ts": ANCHOR})
    # The session keeps serving after a timeout.
    healthy = MCPGraphToolPort(session, budget=CallBudget(5))
    assert (
        healthy.run_query("get_card_baseline_v1", {"card_id": CARD, "as_of_ts": ANCHOR}).refused
        is False
    )


def test_a_closed_session_is_unavailable(config):
    closed = MCPSession(config).start()
    closed.close()
    with pytest.raises(MCPUnavailableError):
        closed.call_tool("tigergraph__list_graphs", {})
