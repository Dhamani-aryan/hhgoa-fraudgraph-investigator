"""Live regressions for the Gate 2A query corrections.

Three findings, each pinned against the installed queries rather than the
source files, because a corrected file that was never reinstalled proves
nothing.

Skipped when TigerGraph is not configured, so the suite still runs on a clean
clone without credentials.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from graph.client import TigerGraphConfigError, connect, load_config
from graph.result_normalizers import rows, scalar

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: A device with a genuine time-local multi-card cluster: 40 cards overall,
#: 49 transactions, active only in July 2016.
CLUSTER_DEVICE = "8cccc8f01f55e75b"
CLUSTER_ANCHOR = "2016-07-15 12:00:00"

#: Benchmark case HHG-017.
FLAGGED_TXN = "3450629"
CARD = "C04570-K1"
ANCHOR = "2016-11-11 23:46:24"

#: A different benchmark card, for the mismatch check.
OTHER_CARD = "C11891-K1"

#: Review cutoffs later than the anchor. Evidence must not move between them.
LATER_CUTOFFS = ("2016-09-01 00:00:00", "2016-11-01 00:00:00", "2016-12-31 23:59:59")


@pytest.fixture(scope="module")
def connection():
    try:
        return connect(load_config())
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")


def shared_origin(connection, *, as_of: str, anchor: str = CLUSTER_ANCHOR, **overrides):
    params = {
        "entity_kind": "device",
        "entity_id": CLUSTER_DEVICE,
        "anchor_ts": anchor,
        "as_of_ts": as_of,
        "window_hours": 336,
    }
    params.update(overrides)
    return connection.runInstalledQuery("find_shared_origin_activity_v1", params=params)


def region(connection, *, card: str = CARD, txn: str = FLAGGED_TXN, as_of: str = ANCHOR):
    return connection.runInstalledQuery(
        "find_region_anomalies_v1",
        params={"card_id": card, "flagged_txn_id": txn, "as_of_ts": as_of},
    )


# --- finding 1: effective evidence cutoff ----------------------------------


def test_a_later_review_does_not_change_evidence_at_the_anchor(connection):
    """The whole finding in one assertion: reviewing later reveals nothing new."""
    baseline = shared_origin(connection, as_of=CLUSTER_ANCHOR)
    expected = (
        scalar(baseline, "entity_cards_to_cutoff"),
        scalar(baseline, "transactions_in_window"),
        scalar(baseline, "fraud_enriched_card_count"),
    )
    assert expected[1] > 0, "the fixture cluster should return evidence to compare"

    for later in LATER_CUTOFFS:
        result = shared_origin(connection, as_of=later)
        actual = (
            scalar(result, "entity_cards_to_cutoff"),
            scalar(result, "transactions_in_window"),
            scalar(result, "fraud_enriched_card_count"),
        )
        assert actual == expected, f"evidence moved at as_of={later}: {actual} != {expected}"


def test_the_effective_cutoff_is_the_earlier_bound(connection):
    later = shared_origin(connection, as_of="2016-12-31 23:59:59")
    assert scalar(later, "effective_cutoff").startswith("2016-07-15")

    earlier = shared_origin(connection, as_of="2016-07-10 00:00:00")
    assert scalar(earlier, "effective_cutoff").startswith("2016-07-10")


@pytest.mark.parametrize("as_of", LATER_CUTOFFS)
def test_no_shared_transaction_exceeds_the_effective_cutoff(connection, as_of):
    result = shared_origin(connection, as_of=as_of)
    effective = scalar(result, "effective_cutoff")
    for item in rows(result, "shared_transactions"):
        assert item["ts"] <= effective, f"{item['txn_id']} at {item['ts']} > {effective}"


@pytest.mark.parametrize("as_of", LATER_CUTOFFS)
def test_no_prior_fraud_case_closed_after_the_effective_cutoff(connection, as_of):
    result = shared_origin(connection, as_of=as_of)
    effective = scalar(result, "effective_cutoff")
    for case in rows(result, "prior_fraud_cases"):
        assert case["closed_at"] <= effective, (
            f"{case['case_id']} closed {case['closed_at']} > {effective}"
        )


def test_an_earlier_review_cutoff_still_narrows_evidence(connection):
    """min() must bite in both directions, not just clamp the later one."""
    early = shared_origin(connection, as_of="2016-07-08 00:00:00")
    full = shared_origin(connection, as_of=CLUSTER_ANCHOR)
    assert scalar(early, "entity_cards_to_cutoff") < scalar(full, "entity_cards_to_cutoff")


# --- finding 2: inadmissible region requests -------------------------------

#: Everything a refused region request must withhold.
REGION_DATA_KEYS = (
    "flagged_region",
    "flagged_ts",
    "region_history",
    "flagged_region_prior_count",
    "region_is_new_for_card",
    "other_region_activity_in_window",
)


def test_region_refuses_a_flagged_transaction_after_the_cutoff(connection):
    result = region(connection, as_of="2016-08-01 00:00:00")
    assert scalar(result, "refused") is True
    assert scalar(result, "refused_flagged_after_cutoff") is True
    assert scalar(result, "refusal_reason")


def test_a_refused_future_request_returns_no_transaction_detail(connection):
    """Refusing must withhold the data, including the region and the timestamp."""
    result = region(connection, as_of="2016-08-01 00:00:00")
    for key in REGION_DATA_KEYS:
        assert scalar(result, key) is None, f"{key} leaked on a refused request"
    assert rows(result, "concurrent_other_region_activity") == []


def test_region_refuses_a_card_transaction_mismatch(connection):
    """Answering would attribute one card's history to another card's transaction."""
    result = region(connection, card=OTHER_CARD)
    assert scalar(result, "refused") is True
    assert scalar(result, "refused_card_mismatch") is True


def test_a_refused_mismatch_returns_no_transaction_detail(connection):
    result = region(connection, card=OTHER_CARD)
    for key in REGION_DATA_KEYS:
        assert scalar(result, key) is None, f"{key} leaked on a mismatched request"


def test_region_refuses_an_unknown_transaction(connection):
    result = region(connection, txn="9999999999")
    assert scalar(result, "refused") is True


def test_a_valid_region_request_is_still_answered(connection):
    """The refusals must not have broken the working path."""
    result = region(connection)
    assert scalar(result, "refused") is False
    assert scalar(result, "flagged_region") == "204.0"
    assert scalar(result, "region_is_new_for_card") is False
    assert sum((scalar(result, "region_history") or {}).values()) == 52


# --- finding 3: bounding that actually bounds ------------------------------


def test_an_over_budget_entity_is_not_scanned_at_all(connection):
    """LIMIT bounded the result set, not the work: gmail.com scanned 45,521 rows.

    The precheck now refuses before any traversal, so the scan is zero rows.
    """
    result = connection.runInstalledQuery(
        "find_shared_origin_activity_v1",
        params={
            "entity_kind": "recipient_email",
            "entity_id": "gmail.com",
            "anchor_ts": ANCHOR,
            "as_of_ts": ANCHOR,
            "max_scan_rows": 100,
        },
    )
    assert scalar(result, "refused_over_scan_budget") is True
    assert scalar(result, "rarity_rows_scanned") == 0
    assert scalar(result, "precheck_lifetime_transactions") > 100
    assert "scan budget" in scalar(result, "refusal_reason")


def test_the_budget_decides_whether_work_happens(connection):
    """Same entity, two budgets: one scans, the other does not."""
    over = shared_origin(connection, as_of=CLUSTER_ANCHOR, max_scan_rows=1)
    under = shared_origin(connection, as_of=CLUSTER_ANCHOR, max_scan_rows=20000)

    assert scalar(over, "refused_over_scan_budget") is True
    assert scalar(over, "rarity_rows_scanned") == 0

    assert scalar(under, "refused_over_scan_budget") is False
    assert scalar(under, "rarity_rows_scanned") > 0


def test_an_over_budget_refusal_is_fast(connection):
    """A refusal that still walked the graph would not be a budget."""
    started = time.time()
    connection.runInstalledQuery(
        "find_shared_origin_activity_v1",
        params={
            "entity_kind": "recipient_email",
            "entity_id": "gmail.com",
            "anchor_ts": ANCHOR,
            "as_of_ts": ANCHOR,
            "max_scan_rows": 100,
        },
    )
    assert time.time() - started < 10.0


def test_the_precheck_figure_is_labelled_as_a_resource_measure(connection):
    """A lifetime aggregate may gate a scan; it may not be case evidence.

    It is reported under a name that says what it is, and the rarity that
    drives the supernode decision is a separate, cutoff-bounded count.
    """
    result = shared_origin(connection, as_of=CLUSTER_ANCHOR)
    assert scalar(result, "precheck_lifetime_transactions") is not None
    assert scalar(result, "entity_cards_to_cutoff") is not None
    # The two are different questions and must not be the same number here.
    assert scalar(result, "precheck_lifetime_transactions") != scalar(
        result, "entity_cards_to_cutoff"
    )


def test_case_context_reports_its_device_scan_budget(connection):
    result = connection.runInstalledQuery(
        "get_case_context_v1",
        params={"flagged_txn_id": FLAGGED_TXN, "as_of_ts": ANCHOR},
    )
    assert scalar(result, "device_scan_skipped") is False
    assert scalar(result, "device_precheck_lifetime_transactions") > 0
    assert scalar(result, "device_cards_to_anchor") > 0


def test_case_context_skips_an_over_budget_device_scan(connection):
    result = connection.runInstalledQuery(
        "get_case_context_v1",
        params={"flagged_txn_id": FLAGGED_TXN, "as_of_ts": ANCHOR, "max_scan_rows": 1},
    )
    assert scalar(result, "device_scan_skipped") is True
    assert scalar(result, "device_cards_to_anchor") is None
    # The rest of the context is still returned.
    assert rows(result, "flagged_transaction")
    assert scalar(result, "card_transactions_to_anchor") == 53


# --- case context: evidence is a property of the case, not of when we look ---


#: Review cutoffs later than the flagged transaction on HHG-017.
CONTEXT_LATER_CUTOFFS = (
    "2016-11-12 00:46:24",
    "2016-12-01 00:00:00",
    "2016-12-31 23:59:59",
)

#: Keys that legitimately echo the request rather than describing evidence.
REQUEST_ECHO_KEYS = {"as_of_ts", "scan_row_budget"}


def case_context(connection, *, as_of: str, txn: str = FLAGGED_TXN, **overrides):
    params = {"flagged_txn_id": txn, "as_of_ts": as_of}
    params.update(overrides)
    return connection.runInstalledQuery("get_case_context_v1", params=params)


def _evidence(result) -> dict:
    """Everything the query returned except the echoed request parameters."""
    from graph.result_normalizers import normalize_result

    return {
        key: value
        for key, value in normalize_result(result).items()
        if key not in REQUEST_ECHO_KEYS
    }


@pytest.mark.parametrize("later", CONTEXT_LATER_CUTOFFS)
def test_case_context_evidence_is_identical_at_a_later_review(connection, later):
    """Moving as_of_ts past the flagged transaction must change nothing.

    The bound is min(flagged ts, as_of_ts), so a later review cannot widen the
    card, cardholder, device, adjacent or prior-case traversals.
    """
    at_anchor = _evidence(case_context(connection, as_of=ANCHOR))
    reviewed_later = _evidence(case_context(connection, as_of=later))

    assert at_anchor, "the fixture case should return evidence to compare"
    assert reviewed_later == at_anchor, {
        key
        for key in set(at_anchor) | set(reviewed_later)
        if at_anchor.get(key) != reviewed_later.get(key)
    }


def test_case_context_effective_cutoff_pins_to_the_flagged_transaction(connection):
    result = case_context(connection, as_of="2016-12-31 23:59:59")
    assert scalar(result, "effective_cutoff") == ANCHOR


@pytest.mark.parametrize(
    "block",
    ["adjacent_transactions", "prior_cases_on_card"],
)
def test_case_context_rows_never_exceed_the_effective_cutoff(connection, block):
    result = case_context(connection, as_of="2016-12-31 23:59:59")
    effective = scalar(result, "effective_cutoff")
    field = "ts" if block == "adjacent_transactions" else "closed_at"
    for item in rows(result, block):
        assert item[field] <= effective


def test_case_context_refuses_an_unknown_transaction(connection):
    result = case_context(connection, as_of=ANCHOR, txn="9999999999")
    assert scalar(result, "refused") is True
    assert scalar(result, "flagged_not_found") is True
    assert rows(result, "flagged_transaction") == []


# --- card baseline: the amount list has a truthful bound --------------------


def baseline(connection, *, card: str = CARD, as_of: str = ANCHOR, **overrides):
    params = {"card_id": card, "as_of_ts": as_of}
    params.update(overrides)
    return connection.runInstalledQuery("get_card_baseline_v1", params=params)


def test_baseline_amounts_match_the_counted_transactions(connection):
    """A truncated list would give a median and MAD for a half-read card."""
    result = baseline(connection)
    assert scalar(result, "scan_skipped") is False
    amounts = scalar(result, "amounts_to_anchor")
    assert len(amounts) == scalar(result, "n_transactions_to_anchor") == 53


def test_baseline_refuses_rather_than_returning_a_partial_history(connection):
    """Over budget must yield no baseline at all, not a silently short one."""
    result = baseline(connection, max_scan_rows=1)
    assert scalar(result, "scan_skipped") is True
    assert scalar(result, "amounts_to_anchor") is None
    assert scalar(result, "n_transactions_to_anchor") is None
    assert scalar(result, "skip_reason")


def test_baseline_budget_is_what_decides(connection):
    over = baseline(connection, max_scan_rows=1)
    under = baseline(connection, max_scan_rows=20000)
    assert scalar(over, "scan_skipped") is True
    assert scalar(under, "scan_skipped") is False


def test_baseline_precheck_is_a_resource_figure_not_evidence(connection):
    """The lifetime count gates the scan; the as-of count is the evidence."""
    result = baseline(connection)
    assert scalar(result, "precheck_lifetime_transactions") == 59
    assert scalar(result, "n_transactions_to_anchor") == 53


def test_baseline_default_budget_admits_every_card_in_this_dataset(connection):
    """The largest card holds 14,891 transactions against a 20,000 default.

    Asserted on the real maximum so the documented contract cannot drift from
    the data it claims to cover.
    """
    import polars as pl

    cards = pl.read_csv(
        PROJECT_ROOT / "data" / "prepared" / "payment_cards.csv",
        has_header=False,
        infer_schema_length=0,
    )
    largest = cards.select(pl.col("column_9").cast(pl.Int64)).max().item()
    assert largest == 14891
    assert largest < 20000
