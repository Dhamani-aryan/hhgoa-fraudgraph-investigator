"""The interpretable graph feature vector, measured to the case anchor.

These features feed the probability engine in Gate 3, so a leak here would
inflate an offline evaluation against a runtime that can never match it. Every
test compares order-insensitively, because GSQL set accumulators come back
unordered and a naive comparison reports a false difference.
"""

from __future__ import annotations

import pytest

from graph.client import TigerGraphConfigError, connect, load_config
from graph.result_normalizers import normalize_result, scalar

QUERY = "extract_temporal_graph_features_v1"

#: Benchmark case HHG-017.
FLAGGED_TXN = "3450629"
CARD = "C04570-K1"
ANCHOR = "2016-11-11 23:46:24"

LATER_CUTOFFS = ("2016-12-01 00:00:00", "2016-12-31 23:59:59")


@pytest.fixture(scope="module")
def connection():
    try:
        return connect(load_config())
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")


def features(connection, *, as_of: str = ANCHOR, txn: str = FLAGGED_TXN, **overrides):
    params = {"flagged_txn_id": txn, "as_of_ts": as_of}
    params.update(overrides)
    return connection.runInstalledQuery(QUERY, params=params)


def comparable(result) -> dict:
    """Normalize for comparison: sort lists, drop the echoed request."""
    merged = normalize_result(result)
    return {
        key: sorted(value) if isinstance(value, list) else value
        for key, value in merged.items()
        if key not in {"as_of_ts"}
    }


# --- the vector is populated -----------------------------------------------


def test_card_velocity_features_match_the_known_card(connection):
    result = features(connection)
    assert scalar(result, "card_degree_to_cutoff") == 53
    assert scalar(result, "card_degree_1h") == 2
    assert scalar(result, "card_degree_24h") == 3


def test_novelty_features_are_present_and_consistent(connection):
    result = features(connection)
    prior_region = scalar(result, "card_prior_transactions_in_flagged_region")
    assert prior_region == 5
    assert scalar(result, "region_is_novel_for_card") is (prior_region == 0)

    prior_device = scalar(result, "card_prior_transactions_on_device")
    assert scalar(result, "device_is_novel_for_card") is (prior_device == 0)


def test_both_neighbour_outcomes_are_returned(connection):
    """A cleared neighbour must be able to lower a score, not only fraud raise it."""
    result = features(connection)
    assert scalar(result, "device_fraud_neighbour_cards") > 0
    assert scalar(result, "device_cleared_neighbour_cards") > 0


def test_distinct_customers_is_reported_beside_distinct_cards(connection):
    """One person's two cards on one device is not a ring."""
    result = features(connection)
    cards = scalar(result, "device_distinct_cards_in_window")
    customers = scalar(result, "device_distinct_customers_in_window")
    assert cards > 0 and customers > 0
    assert customers <= cards


def test_region_reach_exposes_a_supernode(connection):
    """The caller needs this to discount a common billing region."""
    result = features(connection)
    assert scalar(result, "region_distinct_cards_in_window") > 100


# --- temporal invariance ---------------------------------------------------


@pytest.mark.parametrize("later", LATER_CUTOFFS)
def test_features_are_identical_at_a_later_review(connection, later):
    """A feature that moves with the review date would leak into Gate 3 scoring."""
    at_anchor = comparable(features(connection))
    reviewed = comparable(features(connection, as_of=later))
    assert reviewed == at_anchor, {
        key for key in set(at_anchor) | set(reviewed) if at_anchor.get(key) != reviewed.get(key)
    }


def test_the_effective_cutoff_pins_to_the_flagged_transaction(connection):
    assert scalar(features(connection, as_of="2016-12-31 23:59:59"), "effective_cutoff") == ANCHOR


def test_no_fraud_neighbour_closed_after_the_cutoff(connection):
    result = features(connection, as_of="2016-12-31 23:59:59")
    latest = scalar(result, "latest_fraud_neighbour_closure")
    if latest:
        assert latest <= scalar(result, "effective_cutoff")


def test_a_narrower_window_reduces_shared_reach(connection):
    wide = features(connection, shared_window_hours=168)
    narrow = features(connection, shared_window_hours=1)
    assert scalar(narrow, "device_distinct_cards_in_window") <= scalar(
        wide, "device_distinct_cards_in_window"
    )


# --- refusal and bounding --------------------------------------------------


def test_a_future_flagged_transaction_yields_no_features(connection):
    result = features(connection, as_of="2016-08-01 00:00:00")
    assert scalar(result, "refused") is True
    assert scalar(result, "flagged_after_cutoff") is True
    assert scalar(result, "card_degree_to_cutoff") is None


def test_an_unknown_transaction_yields_no_features(connection):
    result = features(connection, txn="9999999999")
    assert scalar(result, "refused") is True
    assert scalar(result, "card_degree_to_cutoff") is None


def test_an_over_budget_device_scan_is_skipped_not_truncated(connection):
    result = features(connection, max_scan_rows=1)
    assert scalar(result, "device_scan_skipped") is True
    assert scalar(result, "device_degree_to_cutoff") is None
    # Card features are unaffected: they carry no device budget.
    assert scalar(result, "card_degree_to_cutoff") == 53


def test_the_precheck_is_a_resource_figure_not_a_feature(connection):
    result = features(connection)
    assert scalar(result, "device_precheck_lifetime_transactions") == 621
    assert scalar(result, "device_degree_to_cutoff") == 299
