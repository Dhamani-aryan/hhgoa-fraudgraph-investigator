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

#: Lifetime volumes of the fixture's shared entities, the resource prechecks.
#: Region 204.0 holds 42,035 transactions and anonymous.com 57,572, both above
#: the 20,000 default, so by default both sections are withheld.
REGION_LIFETIME = 42035
EMAIL_LIFETIME = 57572

#: A budget large enough to admit every section of the fixture, passed
#: explicitly by tests that need the region and email values.
GENEROUS = 100000

#: The keys each gated section returns only when its scan ran.
SECTION_KEYS = {
    "device": (
        "device_degree_to_cutoff",
        "device_degree_1h",
        "device_degree_24h",
        "device_degree_7d",
        "device_distinct_cards_in_window",
        "device_distinct_customers_in_window",
        "device_fraud_neighbour_cards",
        "device_cleared_neighbour_cards",
    ),
    "region": (
        "region_degree_to_cutoff",
        "region_degree_1h",
        "region_degree_24h",
        "region_degree_7d",
        "region_transactions_in_window",
        "region_distinct_cards_in_window",
    ),
    "email": (
        "email_degree_to_cutoff",
        "email_degree_1h",
        "email_degree_24h",
        "email_degree_7d",
        "email_distinct_cards_in_window",
    ),
}


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
    result = features(connection, max_scan_rows=GENEROUS)
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


# --- coverage against the plan's feature list -------------------------------


def test_all_three_shared_entities_report_degree_at_four_scales(connection):
    """The plan asks for device, email AND region degree; email was missing."""
    result = features(connection, max_scan_rows=GENEROUS)
    for entity in ("device", "email", "region"):
        for scale in ("to_cutoff", "1h", "24h", "7d"):
            key = f"{entity}_degree_{scale}"
            assert scalar(result, key) is not None, f"{key} is missing"


def test_both_neighbour_outcomes_report_recency(connection):
    """A fraud neighbour from last week is not the same evidence as one from May.

    The same is true of a neighbour that was investigated and cleared, and only
    the fraud side carried a recency before.
    """
    result = features(connection)
    assert scalar(result, "latest_fraud_neighbour_closure")
    assert scalar(result, "latest_cleared_neighbour_closure")


def test_neighbour_recencies_respect_the_cutoff(connection):
    result = features(connection, as_of="2016-12-31 23:59:59")
    effective = scalar(result, "effective_cutoff")
    for key in ("latest_fraud_neighbour_closure", "latest_cleared_neighbour_closure"):
        value = scalar(result, key)
        if value:
            assert value <= effective


def test_burst_count_is_reported_and_bounded_by_the_gap(connection):
    """Bursts are a different signal from a high hourly count."""
    tight = features(connection, burst_gap_seconds=60)
    loose = features(connection, burst_gap_seconds=86400)
    assert scalar(tight, "burst_transitions") <= scalar(loose, "burst_transitions")
    assert scalar(loose, "burst_transitions") > 0


def test_email_reach_exposes_a_common_domain(connection):
    """anonymous.com is a free-mail equivalent and must be discountable."""
    result = features(connection, max_scan_rows=GENEROUS)
    assert scalar(result, "email_distinct_cards_in_window") > 100


def test_the_vector_is_substantial(connection):
    """Guards against a feature silently disappearing from the payload."""
    from graph.result_normalizers import normalize_result

    assert len(normalize_result(features(connection))) >= 40


# --- every shared-entity section is budgeted, not only the device ----------


def test_by_default_the_region_and_email_supernodes_are_withheld(connection):
    """Measured before the fix: 31,813 region and 28,793 email rows at a 20,000 budget."""
    result = features(connection)
    for entity, lifetime in (("region", REGION_LIFETIME), ("email", EMAIL_LIFETIME)):
        assert scalar(result, f"{entity}_precheck_lifetime_transactions") == lifetime
        assert scalar(result, f"{entity}_scan_skipped") is True
        assert scalar(result, f"{entity}_rows_scanned") == 0, f"{entity} was scanned"
        assert scalar(result, f"{entity}_features_withheld_reason")
        for key in SECTION_KEYS[entity]:
            assert scalar(result, key) is None, f"{key} returned for a skipped section"


def test_each_section_is_gated_independently(connection):
    """A budget between the two volumes admits the region and withholds the email."""
    result = features(connection, max_scan_rows=50000)
    assert scalar(result, "region_scan_skipped") is False
    assert scalar(result, "region_degree_to_cutoff") == 31813
    assert scalar(result, "email_scan_skipped") is True
    assert scalar(result, "email_rows_scanned") == 0
    assert scalar(result, "email_degree_to_cutoff") is None
    # The device is small enough for every budget used here.
    assert scalar(result, "device_degree_to_cutoff") == 299


@pytest.mark.parametrize("budget", [1, 20000, 50000, GENEROUS])
def test_no_section_ever_returns_partial_statistics(connection, budget):
    """Either the whole section, read to the cutoff, or none of it."""
    result = features(connection, max_scan_rows=budget)
    for entity, keys in SECTION_KEYS.items():
        lifetime = scalar(result, f"{entity}_precheck_lifetime_transactions")
        skipped = scalar(result, f"{entity}_scan_skipped")
        assert skipped is (lifetime > budget), entity
        if skipped:
            assert scalar(result, f"{entity}_rows_scanned") == 0, entity
            assert all(scalar(result, key) is None for key in keys), entity
        else:
            assert all(scalar(result, key) is not None for key in keys), entity
            assert scalar(result, f"{entity}_rows_scanned") == scalar(
                result, f"{entity}_degree_to_cutoff"
            ), f"{entity} scanned a different number of rows than it reported"


def test_an_over_budget_section_performs_no_scan(connection):
    """rows_scanned counts the traversal's own ACCUM, so 0 means it never ran."""
    result = features(connection, max_scan_rows=1)
    for entity in SECTION_KEYS:
        assert scalar(result, f"{entity}_scan_skipped") is True
        assert scalar(result, f"{entity}_rows_scanned") == 0
    # The ungated card history is still there: skipping is per section.
    assert scalar(result, "card_degree_to_cutoff") == 53


def test_lifetime_prechecks_are_resource_figures_never_evidence(connection):
    """The lifetime count includes activity after the anchor, so it cannot be evidence."""
    from graph.result_normalizers import evidence_values

    result = features(connection, max_scan_rows=GENEROUS)
    # Lifetime and cutoff-bounded differ: the precheck sees the future.
    assert scalar(result, "region_precheck_lifetime_transactions") > scalar(
        result, "region_degree_to_cutoff"
    )
    assert scalar(result, "email_precheck_lifetime_transactions") > scalar(
        result, "email_degree_to_cutoff"
    )
    evidence = evidence_values(result)
    assert not [key for key in evidence if "lifetime" in key]
    assert "region_degree_to_cutoff" in evidence


@pytest.mark.parametrize("later", LATER_CUTOFFS)
def test_admitted_region_and_email_features_are_identical_at_a_later_review(connection, later):
    at_anchor = comparable(features(connection, max_scan_rows=GENEROUS))
    reviewed = comparable(features(connection, as_of=later, max_scan_rows=GENEROUS))
    assert reviewed == at_anchor, {
        key for key in set(at_anchor) | set(reviewed) if at_anchor.get(key) != reviewed.get(key)
    }
