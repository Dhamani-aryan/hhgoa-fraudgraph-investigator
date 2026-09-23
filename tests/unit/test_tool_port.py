"""GraphToolPort and the MCP client, exercised with controlled fake transports.

The live equivalents are in tests/integration/test_mcp_tool_port.py. These pin
the decisions the port makes without a graph: what may be called, what is
sent, what is logged, how many calls are allowed, and exactly which failures
may fall back from MCP to the direct path.
"""

from __future__ import annotations

import json
import time

import pytest

from graph.client import TigerGraphConfig
from graph.mcp_client import (
    MCP_SERVED_TOOLS,
    MCPSurfaceError,
    MCPToolError,
    MCPUnavailableError,
    check_surface,
    describe_startup,
    parse_tool_text,
    server_arguments,
    server_environment,
)
from graph.tool_port import (
    MAX_GRAPH_CALLS,
    READ_QUERIES,
    CallBudget,
    CallBudgetExceeded,
    DirectGraphToolPort,
    FallbackGraphToolPort,
    ForbiddenQueryError,
    GraphQueryError,
    GraphUnavailableError,
    InvalidParametersError,
    MCPGraphToolPort,
    TemporalParameterError,
    canonical,
    classify_tool_error,
    paths_used,
)

SECRET = "s3cr3t-value-that-must-not-leak"
CONFIG = TigerGraphConfig(
    host="https://example.invalid", graphname="G", tg_cloud=True, secret=SECRET
)

ANCHOR = "2016-11-11 23:46:24"
CONTEXT = ("get_case_context_v1", {"flagged_txn_id": "3450629", "as_of_ts": ANCHOR})
RAW = [
    {"refused": False},
    {"component_cards": ["C3-K1", "C1-K1", "C2-K1"]},
    {"flagged_transaction": [{"v_id": "1", "attributes": {"flagged.txn_id": "1"}}]},
]


def vector(value: float = 0.1234567891) -> list[float]:
    return [value] + [0.0] * 1535


class FakeSession:
    """Stands in for MCPSession: records calls and plays a scripted behaviour."""

    def __init__(self, behaviour=None):
        self.config = CONFIG
        self.calls: list[tuple[str, dict]] = []
        self.behaviour = behaviour or (
            lambda name, args: {"success": True, "data": {"result": RAW}}
        )

    def call_tool(self, name, arguments, *, timeout_s):
        self.calls.append((name, arguments))
        return self.behaviour(name, arguments)


class FakeConnection:
    def __init__(self, behaviour=None):
        self.calls: list[tuple[str, dict]] = []
        self.behaviour = behaviour or (lambda name, params: RAW)

    def runInstalledQuery(self, name, params=None):  # noqa: N802
        self.calls.append((name, params))
        return self.behaviour(name, params)


def mcp_port(behaviour=None, **kwargs):
    session = FakeSession(behaviour)
    return MCPGraphToolPort(session, **kwargs), session


def direct_port(behaviour=None, **kwargs):
    connection = FakeConnection(behaviour)
    return DirectGraphToolPort(connection, config=CONFIG, **kwargs), connection


# --- the allowlist ---------------------------------------------------------


def test_the_write_query_is_forbidden_and_nothing_is_sent():
    port, session = mcp_port()
    with pytest.raises(ForbiddenQueryError, match="write path"):
        port.run_query("write_investigation_case_v1", {"case_id": "X"})
    assert session.calls == []
    assert port.budget.used == 0
    assert port.log.records[-1].error_class == "ForbiddenQueryError"


def test_the_write_query_is_not_on_the_read_allowlist():
    assert "write_investigation_case_v1" not in READ_QUERIES


@pytest.mark.parametrize("name", ["drop_everything", "INTERPRET QUERY () { }", ""])
def test_any_query_outside_the_allowlist_is_forbidden(name):
    port, session = mcp_port()
    with pytest.raises(ForbiddenQueryError):
        port.run_query(name, {})
    assert session.calls == []


def test_every_allowlisted_query_is_an_installed_v1_read_query():
    for name in READ_QUERIES:
        assert name.endswith("_v1")
        assert "write" not in name


# --- parameters ---------------------------------------------------------------


def test_a_missing_required_parameter_is_refused():
    port, session = mcp_port()
    with pytest.raises(InvalidParametersError):
        port.run_query("get_card_baseline_v1", {"as_of_ts": ANCHOR})
    assert session.calls == []


def test_an_unknown_parameter_is_refused():
    port, _ = mcp_port()
    with pytest.raises(InvalidParametersError, match="does not accept"):
        port.run_query(CONTEXT[0], {**CONTEXT[1], "gsql": "DROP ALL"})


def test_an_over_cap_parameter_is_refused_not_clamped():
    port, _ = mcp_port()
    with pytest.raises(InvalidParametersError, match="exceeds the port cap"):
        port.run_query(CONTEXT[0], {**CONTEXT[1], "max_scan_rows": 10**9})


@pytest.mark.parametrize("value", ["2016-11-11", "yesterday", 1478908000, None])
def test_a_malformed_timestamp_is_a_temporal_error(value):
    port, _ = mcp_port()
    with pytest.raises(TemporalParameterError):
        port.run_query(CONTEXT[0], {"flagged_txn_id": "3450629", "as_of_ts": value})


def test_a_missing_timestamp_is_a_temporal_error():
    port, _ = mcp_port()
    with pytest.raises(TemporalParameterError):
        port.run_query(CONTEXT[0], {"flagged_txn_id": "3450629"})


def test_query_vectors_are_rounded_and_logged_only_as_a_fingerprint():
    port, session = mcp_port()
    port.run_query("find_policy_chunks_v1", {"query_vector": vector()})
    sent = session.calls[0][1]["params"]["query_vector"]
    assert sent[0] == 0.123457
    logged = port.log.records[-1].parameters["query_vector"]
    assert set(logged) == {"vector_dims", "sha256"}
    assert logged["vector_dims"] == 1536
    assert "0.123457" not in json.dumps(port.log.records[-1].as_dict())


def test_a_wrong_sized_or_non_finite_vector_is_refused():
    port, _ = mcp_port()
    with pytest.raises(InvalidParametersError):
        port.run_query("find_policy_chunks_v1", {"query_vector": [0.1] * 10})
    with pytest.raises(InvalidParametersError):
        port.run_query("find_policy_chunks_v1", {"query_vector": [float("nan")] * 1536})


# --- the budget ----------------------------------------------------------------


def test_the_budget_allows_exactly_twelve_calls():
    port, session = mcp_port()
    for _ in range(MAX_GRAPH_CALLS):
        port.run_query(*CONTEXT)
    with pytest.raises(CallBudgetExceeded):
        port.run_query(*CONTEXT)
    assert len(session.calls) == MAX_GRAPH_CALLS


def test_a_failed_call_still_consumes_budget():
    def fail(name, args):
        raise MCPToolError("semantic failure", "OPERATION_ERROR")

    port, _ = mcp_port(fail)
    with pytest.raises(GraphQueryError):
        port.run_query(*CONTEXT)
    assert port.budget.used == 1


def test_a_fallback_retry_is_counted_against_the_same_budget():
    def down(name, args):
        raise MCPUnavailableError("connection refused")

    primary, _ = mcp_port(down, budget=CallBudget(3))
    fallback, _ = direct_port()
    port = FallbackGraphToolPort(primary, fallback)
    port.run_query(*CONTEXT)
    assert port.budget.used == 2
    # The primary takes the third unit and fails; the retry needs a fourth.
    with pytest.raises(CallBudgetExceeded):
        port.run_query(*CONTEXT)
    assert port.budget.used == 3


# --- results are canonical --------------------------------------------------------


def test_both_adapters_normalize_to_the_same_structure():
    mcp, _ = mcp_port()
    direct, _ = direct_port()
    assert canonical(mcp.run_query(*CONTEXT).values) == canonical(direct.run_query(*CONTEXT).values)


def test_ordering_differences_do_not_create_false_differences():
    reordered = [RAW[0], {"component_cards": ["C2-K1", "C3-K1", "C1-K1"]}, RAW[2]]
    mcp, _ = mcp_port()
    direct, _ = direct_port(lambda name, params: reordered)
    assert canonical(mcp.run_query(*CONTEXT).values) == canonical(direct.run_query(*CONTEXT).values)


def test_a_refused_result_is_data_not_an_error():
    refused = [{"refused": True}, {"refusal_reason": "unknown"}]
    port, _ = mcp_port(lambda name, args: {"success": True, "data": {"result": refused}})
    result = port.run_query(*CONTEXT)
    assert result.refused is True
    assert port.log.records[-1].refused is True


def test_resource_prechecks_are_removed_from_evidence():
    raw = [{"device_precheck_lifetime_transactions": 621}, {"device_degree_to_cutoff": 299}]
    port, _ = mcp_port(lambda name, args: {"success": True, "data": {"result": raw}})
    assert port.run_query(*CONTEXT).evidence() == {"device_degree_to_cutoff": 299}


# --- fallback classification --------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        MCPUnavailableError("the MCP session is not running"),
        MCPUnavailableError("tigergraph__run_installed_query timed out after 60s"),
        MCPToolError("HTTPSConnectionPool: Max retries exceeded", "OPERATION_ERROR"),
        MCPToolError("anything", "CONNECTION_ERROR"),
        MCPToolError("502 Bad Gateway", "OPERATION_ERROR"),
    ],
)
def test_availability_failures_fall_back_to_direct_and_say_so(failure):
    def fail(name, args):
        raise failure

    primary, _ = mcp_port(fail)
    fallback, connection = direct_port()
    port = FallbackGraphToolPort(primary, fallback)
    result = port.run_query(*CONTEXT)
    assert result.record.adapter == "direct"
    assert port.fallback_occurred is True
    assert port.fallback_events[0].reason
    assert connection.calls
    assert paths_used(port.log) == {"direct": 1}


@pytest.mark.parametrize(
    "failure",
    [
        MCPToolError("Runtime Error: Parameter related_card_ids is NULL.", "OPERATION_ERROR"),
        MCPToolError("semantic check fails: vertex type unknown", "SCHEMA_ERROR"),
        MCPToolError("query not installed", "OPERATION_ERROR"),
    ],
)
def test_semantic_and_parameter_failures_do_not_fall_back(failure):
    def fail(name, args):
        raise failure

    primary, _ = mcp_port(fail)
    fallback, connection = direct_port()
    port = FallbackGraphToolPort(primary, fallback)
    with pytest.raises((GraphQueryError, InvalidParametersError)):
        port.run_query(*CONTEXT)
    assert connection.calls == []
    assert port.fallback_occurred is False


def test_forbidden_and_invalid_requests_do_not_fall_back():
    primary, _ = mcp_port()
    fallback, connection = direct_port()
    port = FallbackGraphToolPort(primary, fallback)
    with pytest.raises(ForbiddenQueryError):
        port.run_query("write_investigation_case_v1", {"case_id": "X"})
    with pytest.raises(TemporalParameterError):
        port.run_query(CONTEXT[0], {"flagged_txn_id": "1", "as_of_ts": "soon"})
    assert connection.calls == []


def test_a_refusal_does_not_fall_back():
    refused = [{"refused": True}]
    primary, _ = mcp_port(lambda name, args: {"success": True, "data": {"result": refused}})
    fallback, connection = direct_port()
    port = FallbackGraphToolPort(primary, fallback)
    assert port.run_query(*CONTEXT).refused is True
    assert connection.calls == []


def test_the_mode_names_the_primary_and_the_fallback():
    primary, _ = mcp_port()
    fallback, _ = direct_port()
    assert FallbackGraphToolPort(primary, fallback).mode == "mcp_primary_with_direct_fallback"


def test_classification_of_tool_errors():
    assert isinstance(classify_tool_error("read timed out"), GraphUnavailableError)
    assert isinstance(classify_tool_error("x", "CONNECTION_ERROR"), GraphUnavailableError)
    assert isinstance(classify_tool_error("Parameter k is NULL"), InvalidParametersError)
    assert isinstance(classify_tool_error("vertex type Foo not found"), GraphQueryError)


# --- timeouts ---------------------------------------------------------------------


def test_a_direct_call_that_hangs_times_out_as_unavailable():
    def hang(name, params):
        time.sleep(2)
        return RAW

    port, _ = direct_port(hang, timeout_s=0.2)
    started = time.perf_counter()
    with pytest.raises(GraphUnavailableError, match="timed out"):
        port.run_query(*CONTEXT)
    assert time.perf_counter() - started < 1.5


def test_an_mcp_timeout_is_classified_unavailable():
    def slow(name, args):
        raise MCPUnavailableError(f"{name} timed out after 1s")

    port, _ = mcp_port(slow)
    with pytest.raises(GraphUnavailableError):
        port.run_query(*CONTEXT)


# --- redaction ----------------------------------------------------------------------


def test_secrets_and_urls_never_reach_the_call_log():
    def leak(name, params):
        raise RuntimeError(f"401 for https://example.invalid/restpp?token={SECRET}")

    port, _ = direct_port(leak)
    with pytest.raises(GraphQueryError):
        port.run_query(*CONTEXT)
    rendered = json.dumps([record.as_dict() for record in port.log.records])
    assert SECRET not in rendered
    assert "example.invalid" not in rendered


def test_string_parameters_are_redacted_in_the_log():
    port, _ = mcp_port()
    port.run_query("read_investigation_case_v1", {"case_id": f"X-{SECRET}"})
    assert SECRET not in json.dumps(port.log.records[-1].as_dict())


def test_the_call_log_writes_jsonl(tmp_path):
    from graph.tool_port import CallLog

    log = CallLog(tmp_path / "calls.jsonl")
    port, _ = mcp_port(log=log)
    port.run_query(*CONTEXT)
    lines = (tmp_path / "calls.jsonl").read_text().splitlines()
    record = json.loads(lines[0])
    assert {"trace_id", "tool", "parameters", "duration_ms", "ok", "result_bytes"} <= set(record)


# --- the MCP client -------------------------------------------------------------------


def test_the_served_surface_must_be_exactly_the_restricted_one():
    check_surface(list(MCP_SERVED_TOOLS))
    with pytest.raises(MCPSurfaceError, match="unexpected"):
        check_surface([*MCP_SERVED_TOOLS, "tigergraph__list_connections"])
    with pytest.raises(MCPSurfaceError, match="not served"):
        check_surface(list(MCP_SERVED_TOOLS[:-1]))


@pytest.mark.parametrize(
    "tool",
    [
        "tigergraph__gsql",
        "tigergraph__install_query",
        "tigergraph__delete_node",
        "tigergraph__search_top_k_similarity",
        "tigergraph__run_query",
        "tigergraph__drop_graph",
    ],
)
def test_a_mutating_or_free_form_tool_fails_the_surface_even_if_allowed(tool):
    with pytest.raises(MCPSurfaceError, match="mutating or free-form"):
        check_surface([*MCP_SERVED_TOOLS, tool], allowed=(*MCP_SERVED_TOOLS, tool))


def test_the_startup_arguments_restrict_the_surface_and_log_calls():
    arguments = server_arguments()
    assert arguments[0] == "--allowed-tools"
    assert set(arguments[1].split(",")) == set(MCP_SERVED_TOOLS)
    assert "--log-tool-calls" in arguments
    assert SECRET not in describe_startup()


def test_credentials_travel_only_in_the_subprocess_environment():
    env = server_environment(CONFIG)
    assert env["TG_SECRET"] == SECRET
    assert env["TG_LOG_TOOL_CALLS"] == "true"
    assert env["TG_LOG_CALLER_IDENTITY"] == "none"
    assert SECRET not in " ".join(server_arguments())


def test_the_structured_response_is_read_from_the_fenced_json():
    payload = {"success": True, "data": {"result": [{"x": 1}]}}
    text = f"```json\n{json.dumps(payload, indent=2)}\n```\n\n**Done**\n```json\n{{}}\n```"
    assert parse_tool_text(text) == payload
    with pytest.raises(MCPToolError):
        parse_tool_text("not json at all")
