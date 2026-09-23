"""Hybrid prior-case retrieval and policy retrieval, live through the MCP server."""

from __future__ import annotations

import dataclasses
import math

import pytest

from evidence.collector import collect_graph_results
from evidence.feature_assembler import assemble_features
from graph.client import TigerGraphConfigError, load_config
from graph.mcp_client import MCPSession
from graph.tool_port import CallBudget, MCPGraphToolPort
from retrieval.case_retriever import case_signals, retrieve_prior_cases
from retrieval.policy_chunks import all_chunks
from retrieval.policy_retriever import retrieve_policy
from tests.integration.test_feature_assembly import HHG_017, HHG_019


@pytest.fixture(scope="module")
def session():
    try:
        config = load_config()
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")
    live = MCPSession(config).start()
    yield live
    live.close()


def investigate(session, trigger, **kwargs):
    port = MCPGraphToolPort(session, budget=CallBudget(12))
    collected = collect_graph_results(port, trigger)
    vector = assemble_features(trigger.case_id, collected.anchor_time, collected.values)
    cases = retrieve_prior_cases(
        port, vector, seed_card=trigger.card_id, trigger_type=trigger.trigger_type, **kwargs
    )
    signals = case_signals(vector, trigger.card_id, trigger.trigger_type)
    policy = retrieve_policy(port, signals, trigger.case_id)
    return vector, cases, policy, port


@pytest.fixture(scope="module")
def hhg019(session):
    return investigate(session, HHG_019)


# --- prior cases ------------------------------------------------------------------------


def test_prior_cases_come_through_tigergraph_vector_search_over_mcp(hhg019):
    _, cases, _, port = hhg019
    assert cases.retrieval_path == "tigergraph_vector"
    record = next(r for r in port.log.records if r.trace_id == cases.trace_id)
    assert record.adapter == "mcp"
    assert record.query_name == "find_similar_closed_cases_v1"


def test_prior_cases_are_capped_contrastive_and_explained(hhg019):
    _, cases, _, _ = hhg019
    assert 0 < len(cases.cases) <= 6
    outcomes = {case.outcome for case in cases.cases}
    assert outcomes == {"confirmed_fraud", "cleared"}
    for case in cases.cases:
        assert case.reasons
        assert math.isfinite(case.composite_retrieval_score) and case.composite_retrieval_score > 0
        assert case.vector_cosine_distance is not None
        assert case.vector_pool_rank >= 1


def test_no_prior_case_closed_after_the_anchor(hhg019):
    vector, cases, _, _ = hhg019
    assert cases.admissibility_cutoff == vector.anchor_time
    for case in cases.cases:
        assert case.closed_at <= vector.anchor_time
        assert case.closed_before_anchor
        assert case.case_id.startswith("CC-")
    assert cases.rejected_inadmissible == {}


def test_the_shared_origin_pool_reaches_cases_on_connected_cards(hhg019):
    _, cases, _, _ = hhg019
    assert cases.pool_sizes["shared_origin"] > 0
    assert any("shared_origin" in case.reasons for case in cases.cases)


def test_a_case_is_excluded_from_its_own_retrieval(session, hhg019):
    _, cases, _, _ = hhg019
    excluded = cases.cases[0].case_id
    _, again, _, _ = investigate(session, HHG_019, exclude_case_id=excluded)
    assert excluded not in again.case_ids


def test_retrieval_is_deterministic(session, hhg019):
    _, cases, _, _ = hhg019
    _, again, _, _ = investigate(session, HHG_019)
    assert again.case_ids == cases.case_ids
    assert [c.composite_retrieval_score for c in again.cases] == [
        c.composite_retrieval_score for c in cases.cases
    ]


def test_a_later_review_retrieves_the_same_memory(session, hhg019):
    _, cases, _, _ = hhg019
    later = dataclasses.replace(HHG_019, opened_at="2016-12-31 23:59:59")
    _, reviewed, _, _ = investigate(session, later)
    assert reviewed.case_ids == cases.case_ids


def test_the_whole_investigation_fits_the_call_budget(hhg019):
    _, _, _, port = hhg019
    assert port.budget.used <= 12
    assert {record.adapter for record in port.log.records} == {"mcp"}


# --- policy -----------------------------------------------------------------------------


def test_policy_chunks_come_through_tigergraph_and_resolve_to_real_chunks(hhg019):
    _, _, policy, port = hhg019
    known = {chunk.chunk_id for chunk in all_chunks()}
    assert 0 < len(policy.chunks) <= 4
    assert set(policy.chunk_ids) <= known
    assert set(policy.retrieved_ranked) <= known
    record = next(r for r in port.log.records if r.trace_id == policy.trace_id)
    assert record.adapter == "mcp" and record.query_name == "find_policy_chunks_v1"


def test_the_shared_device_fixture_retrieves_the_shared_origin_rule(hhg019):
    _, _, policy, _ = hhg019
    assert "policy:R6" in policy.chunk_ids


def test_the_card_testing_fixture_retrieves_its_pattern_and_rule(session, hhg019):
    """Signals of a card-testing sequence, searched live through TigerGraph."""
    vector, _, _, _ = hhg019
    testing = dataclasses.replace(
        case_signals(vector, HHG_019.card_id, "risk_score"),
        small_amount_burst=True,
        shared_origin_fraud=False,
        connected_component=False,
    )
    port = MCPGraphToolPort(session, budget=CallBudget(2))
    policy = retrieve_policy(port, testing, "CARD-TESTING-FIXTURE")
    assert "policy:R5" in policy.chunk_ids
    assert "pattern:card_testing" in policy.chunk_ids


def test_hhg017_retrieves_without_shared_origin_rules(session):
    """A supernode device and an isolated component make no shared-origin claim."""
    _, cases, policy, _ = investigate(session, HHG_017)
    assert "policy:R6" not in policy.chunk_ids
    assert {case.outcome for case in cases.cases} == {"confirmed_fraud", "cleared"}
