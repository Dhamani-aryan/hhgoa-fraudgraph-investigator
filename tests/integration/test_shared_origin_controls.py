"""The shared-origin controls, against the live graph.

This is the query most able to invent a fraud ring that is not there, so its
guards are tested directly rather than inferred from a passing investigation.

The Gate 0 audit measured the supernodes these tests assert on: gmail.com
touches 9,332 cards and billing region 299.0 touches 2,075, while a strong
device signature has a median of 1-2 cards.
"""

from __future__ import annotations

import pytest

from graph.client import TigerGraphConfigError, connect, load_config
from graph.result_normalizers import rows, scalar

QUERY = "find_shared_origin_activity_v1"

#: A device with a genuine time-local multi-card cluster, found from the
#: prepared files: 40 cards overall, active only in July 2016.
CLUSTER_DEVICE = "8cccc8f01f55e75b"
CLUSTER_ANCHOR = "2016-07-15 12:00:00"

#: The device on benchmark case HHG-017's flagged transaction. A generic
#: Windows 10 / chrome 65 signature that ends the dataset on 299 cards.
FIXTURE_DEVICE = "8ea57628c8afc1b3"


@pytest.fixture(scope="module")
def connection():
    try:
        return connect(load_config())
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")


def probe(connection, kind: str, entity: str, anchor: str, **overrides):
    params = {
        "entity_kind": kind,
        "entity_id": entity,
        "anchor_ts": anchor,
        "as_of_ts": anchor,
    }
    params.update(overrides)
    return connection.runInstalledQuery(QUERY, params=params)


# --- supernode refusal -----------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "entity"),
    [
        ("recipient_email", "gmail.com"),
        ("region", "299.0"),
        ("region", "204.0"),
    ],
)
def test_supernodes_are_refused(connection, kind, entity):
    """Sharing a supernode says nothing about coordination.

    These are refused by the scan-budget precheck before the rarity gate is
    reached, because their lifetime volume alone is too large to scan. Either
    refusal is correct, so the umbrella flag is what this asserts.
    """
    result = probe(connection, kind, entity, CLUSTER_ANCHOR)
    assert scalar(result, "refused") is True
    assert scalar(result, "refusal_reason")


def test_a_refused_entity_returns_no_shared_activity(connection):
    """Refusal must withhold the evidence, not merely label it."""
    result = probe(connection, "recipient_email", "gmail.com", CLUSTER_ANCHOR)
    assert rows(result, "shared_transactions") == []
    assert scalar(result, "cards_in_window") is None


def test_the_threshold_is_what_decides_refusal(connection):
    """Raising the cap admits the same entity, so the control is the threshold."""
    strict = probe(connection, "device", CLUSTER_DEVICE, CLUSTER_ANCHOR, max_entity_cards=2)
    permissive = probe(connection, "device", CLUSTER_DEVICE, CLUSTER_ANCHOR, max_entity_cards=250)
    assert scalar(strict, "refused_as_supernode") is True
    assert scalar(permissive, "refused_as_supernode") is False


def test_rarity_is_counted_as_of_the_cutoff_not_from_stored_totals(connection):
    """The stored n_cards attribute is a lifetime figure and must not decide this.

    The fixture device ends the dataset on 299 cards. Counted to an August
    cutoff it has none, and to the November anchor 164, so an entity's rarity
    grows with the cutoff instead of being fixed by the future.
    """
    early = probe(connection, "device", FIXTURE_DEVICE, "2016-08-01 00:00:00")
    anchor = probe(connection, "device", FIXTURE_DEVICE, "2016-11-11 23:46:24")
    late = probe(connection, "device", FIXTURE_DEVICE, "2016-12-31 23:59:59")

    early_cards = scalar(early, "entity_cards_to_cutoff")
    anchor_cards = scalar(anchor, "entity_cards_to_cutoff")
    late_cards = scalar(late, "entity_cards_to_cutoff")

    assert early_cards < anchor_cards < late_cards
    assert late_cards == 299, "the lifetime total should only be reached at the end"


# --- the admitted path -----------------------------------------------------


def test_a_rare_device_returns_a_time_local_cluster(connection):
    result = probe(connection, "device", CLUSTER_DEVICE, CLUSTER_ANCHOR, window_hours=336)
    assert scalar(result, "refused_as_supernode") is False
    assert scalar(result, "transactions_in_window") > 0
    assert scalar(result, "distinct_cards_in_window") > 1
    assert rows(result, "shared_transactions")


def test_fraud_enrichment_is_reported_separately_from_degree(connection):
    """Degree and fraud enrichment are different questions, answered separately."""
    result = probe(connection, "device", CLUSTER_DEVICE, CLUSTER_ANCHOR, window_hours=336)
    assert scalar(result, "fraud_enriched_card_count") > 0
    for case in rows(result, "prior_fraud_cases"):
        assert case["closed_at"] <= CLUSTER_ANCHOR


def test_a_narrow_window_excludes_distant_activity(connection):
    """Time locality is what separates a ring from a device shared over months."""
    wide = probe(connection, "device", CLUSTER_DEVICE, CLUSTER_ANCHOR, window_hours=336)
    narrow = probe(connection, "device", CLUSTER_DEVICE, CLUSTER_ANCHOR, window_hours=1)
    assert scalar(narrow, "transactions_in_window") < scalar(wide, "transactions_in_window")


def test_activity_after_the_cutoff_is_excluded(connection):
    """The temporal contract holds here too."""
    result = probe(connection, "device", CLUSTER_DEVICE, CLUSTER_ANCHOR, window_hours=336)
    for item in rows(result, "shared_transactions"):
        assert item["ts"] <= CLUSTER_ANCHOR


def test_prior_fraud_after_the_cutoff_is_not_counted(connection):
    """A case closed after the anchor is not evidence the investigator had."""
    early = probe(
        connection,
        "device",
        CLUSTER_DEVICE,
        CLUSTER_ANCHOR,
        window_hours=336,
        as_of_ts="2016-07-03 00:00:00",
    )
    for case in rows(early, "prior_fraud_cases"):
        assert case["closed_at"] <= "2016-07-03 00:00:00"


def test_the_case_own_card_can_be_excluded(connection):
    """A card sharing a device with itself is not a connected card."""
    result = probe(connection, "device", CLUSTER_DEVICE, CLUSTER_ANCHOR, window_hours=336)
    cards = scalar(result, "cards_in_window") or []
    assert cards, "the cluster should contain cards to exclude"

    excluded = probe(
        connection,
        "device",
        CLUSTER_DEVICE,
        CLUSTER_ANCHOR,
        window_hours=336,
        exclude_card_id=cards[0],
    )
    assert cards[0] not in (scalar(excluded, "cards_in_window") or [])
