"""The Phase 3 exit conditions, checked across the whole installed query family.

The plan's Phase 3 exit criteria: every query returns a structured result for a
known fixture; missing entities return useful errors rather than unexplained
empty output; exposure matches a local calculation; every query respects its
cutoff, its row bounds and benchmark-memory exclusion. The per-query suites
cover most of this in depth. This file pins the conditions they did not, and
states the family-wide ones in one place.
"""

from __future__ import annotations

import math

import pytest

from graph.client import TigerGraphConfigError, connect, load_config
from graph.result_normalizers import evidence_values, normalize_result, rows, scalar
from retrieval.embeddings import embed

#: Benchmark case HHG-017, the fixture every Gate 2 query is exercised on.
FLAGGED_TXN = "3450629"
CARD = "C04570-K1"
ANCHOR = "2016-11-11 23:46:24"
DEVICE = "8ea57628c8afc1b3"
REVIEW = "2016-12-31 23:59:59"

UNKNOWN_TXN = "9999999999"
UNKNOWN_CARD = "C99999-K9"


def vector(text: str) -> list[float]:
    """Rounded as the tool port sends it, so a GET request stays short."""
    return [round(value, 6) for value in embed(text)]


@pytest.fixture(scope="module")
def connection():
    try:
        return connect(load_config())
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")


def run(connection, name: str, **params):
    return connection.runInstalledQuery(name, params=params)


# --- every read query answers the fixture ----------------------------------

FIXTURE_CALLS = {
    "get_case_context_v1": {"flagged_txn_id": FLAGGED_TXN, "as_of_ts": ANCHOR},
    "get_card_baseline_v1": {"card_id": CARD, "as_of_ts": ANCHOR},
    "get_transaction_window_v1": {"card_id": CARD, "anchor_ts": ANCHOR, "as_of_ts": ANCHOR},
    "extract_temporal_graph_features_v1": {"flagged_txn_id": FLAGGED_TXN, "as_of_ts": ANCHOR},
    "find_shared_origin_activity_v1": {
        "entity_kind": "device",
        "entity_id": DEVICE,
        "anchor_ts": ANCHOR,
        "as_of_ts": ANCHOR,
        "exclude_card_id": CARD,
        "max_entity_cards": 400,
    },
    "find_region_anomalies_v1": {
        "card_id": CARD,
        "flagged_txn_id": FLAGGED_TXN,
        "as_of_ts": ANCHOR,
    },
    "calculate_case_exposure_v1": {"txn_ids": [FLAGGED_TXN], "as_of_ts": ANCHOR},
    "wcc_shared_origin_v1": {"seed_card_id": CARD, "anchor_ts": ANCHOR, "as_of_ts": ANCHOR},
    "read_investigation_case_v1": {"case_id": "NO-SUCH-CASE"},
}


@pytest.mark.parametrize("name", sorted(FIXTURE_CALLS))
def test_every_read_query_returns_a_structured_result_for_the_fixture(connection, name):
    result = normalize_result(run(connection, name, **FIXTURE_CALLS[name]))
    assert result, f"{name} returned nothing"
    assert result.get("refused") is not True, f"{name} refused the fixture"


def test_both_vector_queries_return_structured_results(connection):
    cases = normalize_result(
        run(
            connection,
            "find_similar_closed_cases_v1",
            query_vector=vector("online purchase burst"),
            as_of_ts=ANCHOR,
            related_card_ids=[],
        )
    )
    assert cases["returned_cases"] > 0
    policy = normalize_result(
        run(connection, "find_policy_chunks_v1", query_vector=vector("card testing"))
    )
    assert policy["hits"]


# --- missing entities are explained, never silently empty ------------------

MISSING = [
    ("get_case_context_v1", {"flagged_txn_id": UNKNOWN_TXN, "as_of_ts": ANCHOR}),
    ("get_card_baseline_v1", {"card_id": UNKNOWN_CARD, "as_of_ts": ANCHOR}),
    (
        "get_transaction_window_v1",
        {"card_id": UNKNOWN_CARD, "anchor_ts": ANCHOR, "as_of_ts": ANCHOR},
    ),
    ("extract_temporal_graph_features_v1", {"flagged_txn_id": UNKNOWN_TXN, "as_of_ts": ANCHOR}),
    (
        "find_shared_origin_activity_v1",
        {
            "entity_kind": "device",
            "entity_id": "nosuchdevice",
            "anchor_ts": ANCHOR,
            "as_of_ts": ANCHOR,
        },
    ),
    (
        "find_shared_origin_activity_v1",
        {"entity_kind": "planet", "entity_id": DEVICE, "anchor_ts": ANCHOR, "as_of_ts": ANCHOR},
    ),
    (
        "find_region_anomalies_v1",
        {"card_id": CARD, "flagged_txn_id": UNKNOWN_TXN, "as_of_ts": ANCHOR},
    ),
    (
        "wcc_shared_origin_v1",
        {"seed_card_id": UNKNOWN_CARD, "anchor_ts": ANCHOR, "as_of_ts": ANCHOR},
    ),
]


@pytest.mark.parametrize(
    ("name", "params"), MISSING, ids=[f"{n}-{i}" for i, (n, _) in enumerate(MISSING)]
)
def test_a_missing_entity_is_refused_with_a_reason(connection, name, params):
    """An empty answer for an unknown id reads as a finding; a refusal does not."""
    result = run(connection, name, **params)
    assert scalar(result, "refused") is True, f"{name} did not refuse"
    assert scalar(result, "refusal_reason"), f"{name} gave no reason"


def test_an_unknown_region_transaction_is_not_reported_as_a_card_mismatch(connection):
    result = run(
        connection,
        "find_region_anomalies_v1",
        card_id=CARD,
        flagged_txn_id=UNKNOWN_TXN,
        as_of_ts=ANCHOR,
    )
    assert scalar(result, "refused_flagged_not_found") is True
    assert scalar(result, "refused_card_mismatch") is False
    assert "does not exist" in scalar(result, "refusal_reason")


def test_exposure_names_unknown_ids(connection):
    result = run(
        connection,
        "calculate_case_exposure_v1",
        txn_ids=[FLAGGED_TXN, UNKNOWN_TXN],
        as_of_ts=ANCHOR,
    )
    assert scalar(result, "missing_txn_ids") == [UNKNOWN_TXN]


def test_an_unknown_case_reads_back_as_not_found(connection):
    assert (
        scalar(run(connection, "read_investigation_case_v1", case_id="NO-SUCH"), "found") is False
    )


# --- exposure agrees with a local calculation -------------------------------


def test_exposure_matches_the_local_sum_of_the_window_amounts(connection):
    window = run(
        connection,
        "get_transaction_window_v1",
        card_id=CARD,
        anchor_ts=ANCHOR,
        as_of_ts=ANCHOR,
        hours_before=2,
    )
    sample = rows(window, "window_transactions")
    assert len(sample) >= 3, "HHG-017 has three purchases in the two hours to the anchor"
    local = round(sum(abs(item["amount"]) for item in sample), 2)

    exposure = run(
        connection,
        "calculate_case_exposure_v1",
        txn_ids=[item["txn_id"] for item in sample],
        as_of_ts=ANCHOR,
    )
    assert math.isclose(scalar(exposure, "exposure_usd"), local, abs_tol=0.005)
    assert scalar(exposure, "transactions_counted") == len(sample)


# --- output caps are honest --------------------------------------------------


def test_a_capped_window_says_it_was_truncated(connection):
    full = run(
        connection,
        "get_transaction_window_v1",
        card_id=CARD,
        anchor_ts=ANCHOR,
        as_of_ts=ANCHOR,
        hours_before=720,
    )
    capped = run(
        connection,
        "get_transaction_window_v1",
        card_id=CARD,
        anchor_ts=ANCHOR,
        as_of_ts=ANCHOR,
        hours_before=720,
        max_rows=2,
    )
    assert scalar(full, "window_truncated") is False
    assert scalar(capped, "returned_rows") == 2
    assert scalar(capped, "window_truncated") is True
    assert scalar(capped, "transactions_in_window") == scalar(full, "transactions_in_window")


def test_shared_origin_enrichment_is_not_understated_by_the_sample_cap(connection):
    """Enrichment is counted over every in-window card, not the capped sample."""
    params = dict(FIXTURE_CALLS["find_shared_origin_activity_v1"])
    full = run(connection, "find_shared_origin_activity_v1", **params)
    capped = run(connection, "find_shared_origin_activity_v1", **params, max_rows=1)
    assert scalar(capped, "shared_transactions_truncated") is True
    assert scalar(capped, "shared_transactions_returned") == 1
    assert scalar(capped, "fraud_enriched_card_count") == scalar(full, "fraud_enriched_card_count")
    assert scalar(full, "fraud_enriched_card_count") > 0


def test_vector_queries_cap_k_whatever_the_caller_asks(connection):
    cases = normalize_result(
        run(
            connection,
            "find_similar_closed_cases_v1",
            query_vector=vector("online purchase"),
            as_of_ts=REVIEW,
            k=500,
            related_card_ids=[],
        )
    )
    assert cases["k_per_pool"] == 20
    assert cases["returned_cases"] <= 60
    policy = normalize_result(
        run(connection, "find_policy_chunks_v1", query_vector=vector("policy"), k=500)
    )
    assert policy["k_returned_cap"] == 10
    assert len(policy["hits"]) <= 10


# --- the vector score is TigerGraph's real cosine distance ------------------


def test_the_vector_distance_is_one_minus_the_cosine_of_the_stored_embeddings(connection):
    """Not a rank dressed up as a similarity: TigerGraph's own distance_map."""
    from retrieval.embeddings import cosine

    query = vector("online card not present purchase from a new device")
    result = normalize_result(
        run(
            connection,
            "find_similar_closed_cases_v1",
            query_vector=query,
            as_of_ts=ANCHOR,
            k=3,
            related_card_ids=[],
        )
    )
    for case in result["admissible"]:
        local = 1.0 - cosine(query, embed(case["memory_text"]))
        assert math.isclose(case["vector_cosine_distance"], local, abs_tol=1e-4), case["case_id"]


# --- prior-case memory cannot leak ------------------------------------------


def test_prior_case_retrieval_returns_only_closed_cases_closed_by_the_cutoff(connection):
    """InvestigationCase vertices, including the benchmark epoch, are never searched."""
    result = normalize_result(
        run(
            connection,
            "find_similar_closed_cases_v1",
            query_vector=vector("fraud"),
            as_of_ts=ANCHOR,
            k=20,
            related_card_ids=[CARD],
        )
    )
    assert result["admissibility_cutoff"] == ANCHOR
    for case in result["admissible"]:
        assert case["case_id"].startswith("CC-"), case["case_id"]
        assert case["closed_at"] <= ANCHOR


def test_prior_case_retrieval_is_contrastive_by_construction(connection):
    result = normalize_result(
        run(
            connection,
            "find_similar_closed_cases_v1",
            query_vector=vector("fraud"),
            as_of_ts=ANCHOR,
            k=3,
            related_card_ids=[],
        )
    )
    outcomes = {case["outcome"] for case in result["admissible"]}
    assert outcomes == {"confirmed_fraud", "cleared"}


def test_an_empty_pool_is_not_widened_into_a_whole_index_search(connection):
    result = normalize_result(
        run(
            connection,
            "find_similar_closed_cases_v1",
            query_vector=vector("fraud"),
            as_of_ts="2016-07-01 00:00:00",
            related_card_ids=[],
        )
    )
    assert result["admissible_pool_size"] == 0
    assert result["returned_cases"] == 0


# --- resource prechecks never become evidence --------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "get_case_context_v1",
        "get_card_baseline_v1",
        "extract_temporal_graph_features_v1",
        "find_shared_origin_activity_v1",
    ],
)
def test_lifetime_prechecks_are_stripped_from_evidence_values(connection, name):
    result = run(connection, name, **FIXTURE_CALLS[name])
    raw = normalize_result(result)
    assert any(key.endswith("precheck_lifetime_transactions") for key in raw)
    assert not [key for key in evidence_values(result) if "lifetime" in key]


# --- temporal cutoffs hold family-wide ---------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "get_case_context_v1",
        "extract_temporal_graph_features_v1",
        "find_shared_origin_activity_v1",
        "wcc_shared_origin_v1",
    ],
)
def test_a_later_review_date_does_not_change_anchor_bounded_answers(connection, name):
    """Queries taking both an anchor and a review date answer as of the anchor."""
    params = dict(FIXTURE_CALLS[name])
    at_anchor = normalize_result(run(connection, name, **params))
    params["as_of_ts"] = REVIEW
    reviewed = normalize_result(run(connection, name, **params))

    def comparable(values):
        drop = {"as_of_ts"}
        return {
            key: sorted(map(str, value)) if isinstance(value, list) else value
            for key, value in values.items()
            if key not in drop
        }

    assert comparable(reviewed) == comparable(at_anchor)
