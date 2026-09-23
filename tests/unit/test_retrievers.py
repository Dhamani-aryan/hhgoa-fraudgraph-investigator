"""Prior-case and policy retrieval, exercised with a controlled fake port."""

from __future__ import annotations

import math
import random

import pytest

from evidence.feature_assembler import assemble_features
from graph.tool_port import CallRecord, GraphUnavailableError, QueryResult
from retrieval.case_retriever import (
    MAX_RESULTS,
    WEIGHTS,
    case_signals,
    retrieve_prior_cases,
)
from retrieval.policy_retriever import MAX_CHUNKS, relevance, retrieve_policy, select_anchors
from tests.unit.test_feature_assembler import ANCHOR, results


def vector():
    return assemble_features("CASE", ANCHOR, results())


def row(
    case_id,
    outcome="confirmed_fraud",
    pattern="card_not_present_new_device",
    distance=0.7,
    pool="vector_fraud_pool",
    card="C9-K1",
    closed="2016-11-20 00:00:00",
    n_txns=1,
    exposure=100.0,
):
    return {
        "case_id": case_id,
        "outcome": outcome,
        "pattern": pattern,
        "vector_cosine_distance": distance,
        "retrieved_by": [pool],
        "card_id": card,
        "closed_at": closed,
        "n_txns": n_txns,
        "exposure_usd": exposure,
        "memory_text": f"{case_id} {outcome} {pattern}",
    }


CANDIDATES = [
    row("CC-0001"),
    row("CC-0002", distance=0.6),
    row("CC-0003", distance=0.8),
    row("CC-0004", pattern="card_testing"),
    row("CC-0101", "cleared", "none", 0.7, "vector_cleared_pool", exposure=0.0),
    row("CC-0102", "cleared", "none", 0.75, "vector_cleared_pool", exposure=0.0),
    row("CC-0103", "cleared", "none", 0.9, "vector_cleared_pool", exposure=0.0),
    row("CC-0201", distance=0.72, pool="shared_origin_pool", card="C2-K1"),
]


class FakePort:
    mode = "fake"

    def __init__(self, rows=None, hits=None, fail=None):
        self.rows, self.hits, self.fail = rows, hits, fail
        self.calls = []

    def run_query(self, name, params):
        self.calls.append((name, params))
        if self.fail:
            raise self.fail
        record = CallRecord(
            trace_id="trace0000000000",
            adapter="fake",
            tool="t",
            query_name=name,
            parameters={},
            started_at="now",
            ok=True,
        )
        if name == "find_policy_chunks_v1":
            values = {"hits": self.hits}
        else:
            values = {
                "admissible": list(self.rows),
                "admissibility_cutoff": params["as_of_ts"],
                "admissible_pool_size": 5565,
                "fraud_pool_size": 10,
                "cleared_pool_size": 5,
                "shared_origin_pool_size": 1,
            }
        return QueryResult(query_name=name, values=values, record=record)


def retrieve(rows=CANDIDATES, **kwargs):
    return retrieve_prior_cases(
        FakePort(rows), vector(), seed_card="C1-K1", trigger_type="risk_score", **kwargs
    )


# --- the result ------------------------------------------------------------------------


def test_at_most_six_and_contrastive():
    result = retrieve()
    assert len(result.cases) <= MAX_RESULTS
    groups = [case.group for case in result.cases]
    assert groups.count("confirmed_fraud_analogue") == 2
    assert groups.count("cleared_analogue") == 2
    assert groups.count("boundary") <= 2
    assert {case.outcome for case in result.cases} == {"confirmed_fraud", "cleared"}


def test_every_case_has_reasons_and_a_positive_finite_composite():
    for case in retrieve().cases:
        assert case.reasons
        assert math.isfinite(case.composite_retrieval_score)
        assert case.composite_retrieval_score > 0
        assert set(case.component_scores) == set(WEIGHTS)
        assert case.recency_contribution > 0


def test_the_composite_is_not_labelled_a_cosine():
    case = retrieve().cases[0]
    assert case.vector_cosine_similarity == pytest.approx(1 - case.vector_cosine_distance)
    assert case.composite_retrieval_score != case.vector_cosine_similarity


def test_the_vector_weight_is_bounded():
    assert WEIGHTS["vector_cosine_similarity"] <= 0.30
    assert math.isclose(sum(WEIGHTS.values()), 1.0)


def test_ordering_is_deterministic_whatever_order_the_graph_returns():
    shuffled = list(CANDIDATES)
    random.Random(7).shuffle(shuffled)
    assert [c.case_id for c in retrieve(shuffled).cases] == [c.case_id for c in retrieve().cases]


def test_the_tigergraph_path_is_recorded():
    result = retrieve()
    assert result.retrieval_path == "tigergraph_vector"
    assert result.trace_id
    assert result.source_query == "find_similar_closed_cases_v1"
    assert all(
        any(r.startswith("tigergraph_vector_rank:") for r in c.reasons) for c in result.cases
    )


def test_the_query_vector_is_logged_as_a_fingerprint():
    assert set(retrieve().query_vector) == {"vector_dims", "sha256"}


def test_structural_candidates_and_the_band_are_sent_to_the_graph():
    port = FakePort(CANDIDATES)
    retrieve_prior_cases(port, vector(), seed_card="C1-K1", trigger_type="risk_score")
    params = port.calls[0][1]
    assert "C1-K1" in params["related_card_ids"]  # the card's own prior cases
    assert "C2-K1" in params["related_card_ids"]  # a WCC / shared-device neighbour
    assert params["min_exposure"] < params["max_exposure"]
    assert params["as_of_ts"] == ANCHOR


# --- exclusion -----------------------------------------------------------------------------


def test_a_case_closed_after_the_anchor_is_rejected():
    late = row("CC-0999", closed="2016-12-05 00:00:00", distance=0.01)
    result = retrieve([*CANDIDATES, late])
    assert "CC-0999" not in result.case_ids
    assert "after the anchor" in result.rejected_inadmissible["CC-0999"]


def test_the_current_case_is_excluded():
    result = retrieve(exclude_case_id="CC-0001")
    assert "CC-0001" not in result.case_ids
    assert "CC-0001" in result.rejected_inadmissible


def test_a_benchmark_epoch_case_can_never_be_retrieved():
    """InvestigationCase ids (the benchmark epoch) are not ClosedCase history."""
    benchmark = row("HHG-003", distance=0.01, closed="2016-11-01 00:00:00")
    result = retrieve([*CANDIDATES, benchmark])
    assert "HHG-003" not in result.case_ids
    assert "not a ClosedCase" in result.rejected_inadmissible["HHG-003"]


# --- structure outranks narrative overlap ----------------------------------------------


def test_generic_narrative_overlap_does_not_dominate():
    """A near-identical narrative with no structural match loses to a structural match."""
    wordy = row(
        "CC-0500",
        pattern="out_of_region_use",
        distance=0.02,
        closed="2016-07-10 00:00:00",
        n_txns=40,
    )
    structural = row("CC-0501", distance=0.85, pool="shared_origin_pool", card="C2-K1")
    result = retrieve([wordy, structural])
    fraud = [c for c in result.cases if c.group == "confirmed_fraud_analogue"]
    assert fraud[0].case_id == "CC-0501"
    assert fraud[0].composite_retrieval_score > fraud[1].composite_retrieval_score


def test_reasons_name_the_structural_matches():
    result = retrieve()
    shared = next(c for c in result.cases if c.case_id == "CC-0201")
    assert "shared_origin" in shared.reasons
    assert "same_new_device" in shared.reasons
    cleared = next(c for c in result.cases if c.outcome == "cleared")
    assert "opposite_outcome" in cleared.reasons


# --- the marked fallback ------------------------------------------------------------------


def test_vector_unavailable_falls_back_locally_and_says_so():
    port = FakePort(fail=GraphUnavailableError("connection refused"))
    result = retrieve_prior_cases(
        port, vector(), seed_card="C1-K1", trigger_type="risk_score", local_memory=CANDIDATES
    )
    assert result.retrieval_path == "local_fallback_not_tigergraph"
    assert "GraphUnavailableError" in result.fallback_reason
    assert result.cases
    assert not any("tigergraph" in reason for case in result.cases for reason in case.reasons)


def test_without_local_memory_a_vector_failure_is_raised():
    port = FakePort(fail=GraphUnavailableError("connection refused"))
    with pytest.raises(GraphUnavailableError):
        retrieve_prior_cases(port, vector(), seed_card="C1-K1", trigger_type="risk_score")


# --- policy retrieval --------------------------------------------------------------------


def hit(chunk_id, distance):
    return {
        "chunk_id": chunk_id,
        "anchor": chunk_id.split(":")[1],
        "title": chunk_id,
        "body": f"body of {chunk_id}",
        "source_document": "fraud_policy.md",
        "vector_cosine_distance": distance,
    }


POLICY_HITS = [
    hit("policy:R6", 0.5),
    hit("policy:R1", 0.6),
    hit("policy:actions", 0.3),
    hit("pattern:card_not_present_new_device", 0.7),
    hit("pattern:shared-origin-caution", 0.75),
    hit("pattern:none", 0.2),
]


def signals():
    return case_signals(vector(), "C1-K1", "risk_score")


def test_policy_keeps_only_signal_relevant_chunks_and_at_most_four():
    result = retrieve_policy(FakePort(hits=POLICY_HITS), signals(), "CASE")
    assert len(result.chunks) <= MAX_CHUNKS
    assert "policy:actions" not in result.chunk_ids  # broad text, no signal asks for it
    assert "pattern:none" not in result.chunk_ids
    assert "policy:R6" in result.chunk_ids


def test_policy_covers_each_signal_before_repeating_one():
    result = retrieve_policy(FakePort(hits=POLICY_HITS), signals(), "CASE")
    assert {chunk.signal for chunk in result.chunks} >= {
        "shared_origin",
        "new_device_online",
        "risk_score_trigger",
    }


def test_policy_reports_relevant_anchors_the_search_did_not_return():
    result = retrieve_policy(FakePort(hits=POLICY_HITS), signals(), "CASE")
    assert "policy:R9" in result.relevant_not_retrieved
    assert "policy:R9" not in result.chunk_ids


def test_every_policy_chunk_carries_rank_similarity_and_a_reason():
    for chunk in retrieve_policy(FakePort(hits=POLICY_HITS), signals(), "CASE").chunks:
        assert chunk.tigergraph_vector_rank >= 1
        assert chunk.vector_cosine_similarity == pytest.approx(1 - chunk.vector_cosine_distance)
        assert chunk.selection_reason and chunk.excerpt
        assert chunk.source_query == "find_policy_chunks_v1"


def test_a_card_testing_sequence_makes_r5_relevant():
    import dataclasses

    testing = dataclasses.replace(signals(), small_amount_burst=True)
    anchors = [anchor for _, anchor in relevance(testing)]
    assert "policy:R5" in anchors and "pattern:card_testing" in anchors


def test_selection_is_one_per_signal_then_priority():
    wanted = [("a", "x1"), ("a", "x2"), ("a", "x3"), ("b", "y1"), ("c", "z1")]
    retrieved = {key: {} for key in ("x1", "x2", "x3", "y1", "z1")}
    assert select_anchors(wanted, retrieved) == ["x1", "y1", "z1", "x2"]
