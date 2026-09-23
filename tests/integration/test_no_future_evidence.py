"""The temporal contract, enforced against the live graph.

The build plan requires this test by name: it must fail if any runtime evidence
crosses its cutoff. Leakage is the failure mode that makes an evaluation look
impressive and the investigation impossible, so it is checked at the source --
the installed queries themselves -- rather than filtered afterwards in Python.

Skipped when TigerGraph is not configured, so the suite still runs on a clean
clone without credentials.
"""

from __future__ import annotations

import pytest

from graph.client import TigerGraphConfigError, connect, load_config
from graph.result_normalizers import rows

#: Benchmark case HHG-017: the flagged transaction and its anchor.
FLAGGED_TXN = "3450629"
CARD = "C04570-K1"
ANCHOR = "2016-11-11 23:46:24"

#: Every closed case shuts by 2016-11-06, so an early cutoff must admit none.
BEFORE_ALL_HISTORY = "2016-07-01 00:00:00"


def _connection():
    try:
        return connect(load_config())
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")


@pytest.fixture(scope="module")
def connection():
    return _connection()


def test_window_never_returns_activity_after_the_cutoff(connection):
    """Asking for a month of lookahead must still stop at the anchor."""
    result = connection.runInstalledQuery(
        "get_transaction_window_v1",
        params={
            "card_id": CARD,
            "anchor_ts": ANCHOR,
            "as_of_ts": ANCHOR,
            "hours_before": 0,
            "hours_after": 720,
        },
    )
    returned = rows(result, "window_transactions")
    assert returned, "the anchor transaction itself should be returned"
    assert all(item["ts"] <= ANCHOR for item in returned), [
        item["ts"] for item in returned if item["ts"] > ANCHOR
    ]


def test_case_context_adjacent_transactions_respect_the_cutoff(connection):
    result = connection.runInstalledQuery(
        "get_case_context_v1",
        params={"flagged_txn_id": FLAGGED_TXN, "as_of_ts": ANCHOR},
    )
    adjacent = rows(result, "adjacent_transactions")
    assert adjacent, "the card has earlier activity, so this must not be empty"
    assert all(item["ts"] <= ANCHOR for item in adjacent)


def test_case_context_prior_cases_closed_before_the_cutoff(connection):
    result = connection.runInstalledQuery(
        "get_case_context_v1",
        params={"flagged_txn_id": FLAGGED_TXN, "as_of_ts": ANCHOR},
    )
    for prior in rows(result, "prior_cases_on_card"):
        assert prior["closed_at"] <= ANCHOR


def test_prior_case_retrieval_admits_nothing_before_the_history_exists(connection):
    """A cutoff before every closure must return no memory at all."""
    from retrieval.embeddings import embed

    result = connection.runInstalledQuery(
        "find_similar_closed_cases_v1",
        params={
            "query_vector": embed("card testing small authorizations"),
            "as_of_ts": BEFORE_ALL_HISTORY,
            "k": 6,
        },
    )
    assert rows(result, "admissible") == []


def test_prior_case_retrieval_respects_a_mid_history_cutoff(connection):
    from retrieval.embeddings import embed

    cutoff = "2016-08-01 00:00:00"
    result = connection.runInstalledQuery(
        "find_similar_closed_cases_v1",
        params={
            "query_vector": embed("card testing small authorizations"),
            "as_of_ts": cutoff,
            "k": 6,
        },
    )
    admitted = rows(result, "admissible")
    assert admitted, "cases closed in July should still be admissible"
    assert all(item["closed_at"] <= cutoff for item in admitted)


def test_a_case_cannot_retrieve_itself(connection):
    from retrieval.embeddings import embed

    late = "2016-12-31 23:59:59"
    unfiltered = connection.runInstalledQuery(
        "find_similar_closed_cases_v1",
        params={
            "query_vector": embed("card testing small authorizations"),
            "as_of_ts": late,
            "k": 6,
        },
    )
    top = rows(unfiltered, "admissible")
    assert top, "the query should return something to exclude"
    excluded_id = top[0]["case_id"]

    filtered = connection.runInstalledQuery(
        "find_similar_closed_cases_v1",
        params={
            "query_vector": embed("card testing small authorizations"),
            "as_of_ts": late,
            "k": 6,
            "exclude_case_id": excluded_id,
        },
    )
    assert excluded_id not in [item["case_id"] for item in rows(filtered, "admissible")]


def test_exposure_reports_unknown_identifiers_rather_than_dropping_them(connection):
    """An omitted id would understate exposure and could move a policy threshold."""
    result = connection.runInstalledQuery(
        "calculate_case_exposure_v1",
        params={"txn_ids": ["3450436", "3450503", "3450629", "9999999999"]},
    )
    from graph.result_normalizers import scalar

    assert scalar(result, "transactions_found") == 3
    assert scalar(result, "transactions_requested") == 4
    assert "9999999999" in scalar(result, "missing_txn_ids")
    assert scalar(result, "exposure_usd") == pytest.approx(300.14, abs=0.01)
