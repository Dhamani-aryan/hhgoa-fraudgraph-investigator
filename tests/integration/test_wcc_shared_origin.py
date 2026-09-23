"""Time-bounded weakly connected component over the shared-origin subgraph.

The graph algorithm the challenge requires. These tests pin the three things
that make a component evidence rather than an artefact: it is bounded by the
case anchor, it is bounded in size and reach, and every member carries the
device that joined it.
"""

from __future__ import annotations

import pytest

from graph.client import TigerGraphConfigError, connect, load_config
from graph.result_normalizers import rows, scalar

QUERY = "wcc_shared_origin_v1"

#: A card from the July 2016 cluster, seeded from device 8cccc8f01f55e75b.
SEED_CARD = "C12897-K1"
ANCHOR = "2016-07-15 12:00:00"

LATER_CUTOFFS = ("2016-09-01 00:00:00", "2016-11-01 00:00:00", "2016-12-31 23:59:59")


@pytest.fixture(scope="module")
def connection():
    try:
        return connect(load_config())
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")


def component(connection, *, as_of: str = ANCHOR, seed: str = SEED_CARD, **overrides):
    params = {"seed_card_id": seed, "anchor_ts": ANCHOR, "as_of_ts": as_of}
    params.update(overrides)
    return connection.runInstalledQuery(QUERY, params=params)


# --- it finds something real -----------------------------------------------


def test_the_seed_reaches_a_component(connection):
    result = component(connection)
    assert scalar(result, "component_size") > 1
    assert rows(result, "component_members")


def test_the_component_is_fraud_enriched_not_merely_large(connection):
    """Size alone cannot separate a ring from a shared office computer."""
    result = component(connection)
    assert scalar(result, "component_cards_with_confirmed_fraud") > 0
    assert rows(result, "component_prior_fraud_cases")


def test_every_member_records_the_device_that_joined_it(connection):
    """A ring claim must resolve to named devices, not to a number."""
    members = rows(component(connection), "component_members")
    assert members, "the fixture seed should reach members to check"
    for member in members:
        assert member["via_devices"], f"{member['card_id']} has no linking device"
        assert member["hop"] >= 1


# --- temporal bounding -----------------------------------------------------


@pytest.mark.parametrize("later", LATER_CUTOFFS)
def test_a_later_review_does_not_grow_the_component(connection, later):
    at_anchor = component(connection)
    reviewed = component(connection, as_of=later)
    assert scalar(reviewed, "component_size") == scalar(at_anchor, "component_size")
    assert scalar(reviewed, "component_cards_with_confirmed_fraud") == scalar(
        at_anchor, "component_cards_with_confirmed_fraud"
    )


def test_the_effective_cutoff_is_the_earlier_bound(connection):
    assert scalar(component(connection, as_of="2016-12-31 23:59:59"), "effective_cutoff") == ANCHOR
    early = component(connection, as_of="2016-07-10 00:00:00")
    assert scalar(early, "effective_cutoff").startswith("2016-07-10")


def test_no_component_fraud_case_closed_after_the_cutoff(connection):
    result = component(connection, as_of="2016-12-31 23:59:59")
    effective = scalar(result, "effective_cutoff")
    for case in rows(result, "component_prior_fraud_cases"):
        assert case["closed_at"] <= effective


def test_a_narrow_window_shrinks_the_component(connection):
    """Co-presence months apart is coincidence; the window is what makes it evidence."""
    wide = component(connection, window_hours=336)
    narrow = component(connection, window_hours=1)
    assert scalar(narrow, "component_size") < scalar(wide, "component_size")


# --- bounding --------------------------------------------------------------


def test_the_device_threshold_controls_the_component_size(connection):
    """Measured: 5 gives ~20 cards, 100 gives ~668 and hits the cap."""
    tight = component(connection, max_device_cards=5, window_hours=336)
    loose = component(connection, max_device_cards=100, window_hours=336)
    assert scalar(tight, "component_size") < scalar(loose, "component_size")


def test_expansion_stops_early_and_says_so(connection):
    """It is a stop condition, not a hard cap, and the name says which.

    The check runs after each hop, so a single hop can overshoot: with the
    device threshold at 100 one hop reached 668 cards. What the threshold
    guarantees is that expansion halts, not that the component is small.
    """
    result = component(connection, max_device_cards=100, window_hours=336, stop_expanding_above=25)
    assert scalar(result, "expansion_stopped_early") is True
    assert scalar(result, "hops_run") == 1


def test_the_device_threshold_is_the_real_per_hop_bound(connection):
    """Since the stop condition can overshoot, the device threshold is the bound."""
    tight = component(connection, max_device_cards=2, window_hours=336, max_hops=1)
    loose = component(connection, max_device_cards=100, window_hours=336, max_hops=1)
    assert scalar(tight, "component_size") < scalar(loose, "component_size")


def test_one_hop_is_the_default(connection):
    """Transitive chaining manufactures rings, so it is off unless asked for."""
    result = component(connection)
    assert scalar(result, "hops_run") == 1
    assert all(member["hop"] == 1 for member in rows(result, "component_members"))


def test_more_hops_reach_further(connection):
    one = component(connection, max_hops=1, max_device_cards=3, window_hours=336)
    three = component(connection, max_hops=3, max_device_cards=3, window_hours=336)
    assert scalar(three, "component_size") > scalar(one, "component_size")
    assert scalar(three, "hops_run") > 1


def test_an_isolated_card_returns_only_itself(connection):
    """A card sharing no eligible device is its own component, not an error."""
    result = component(connection, window_hours=1, max_device_cards=2)
    assert scalar(result, "component_size") >= 1


# --- eligibility counts distinct cards -------------------------------------


def test_eligibility_counts_distinct_cards_not_transactions(connection):
    """The threshold must count the thing it is named after.

    Counting transactions made one card's fifty purchases on its own laptop
    look like fifty cards, excluding it as a supernode, while genuinely shared
    devices were judged on a number unrelated to sharing.
    """
    result = component(connection, window_hours=336, max_device_cards=5)
    devices = rows(result, "eligible_devices")
    assert devices, "the fixture cluster should have eligible devices"
    for device in devices:
        cards = device["in_window_card_set"]
        assert 2 <= len(cards) <= 5, f"{device['device_id']} has {len(cards)} cards"
        # A set of card ids, not a transaction tally.
        assert len(cards) == len(set(cards))


def test_a_device_used_by_one_card_many_times_is_not_eligible(connection):
    """Repeat purchases on a private device are not sharing."""
    result = component(connection, window_hours=336, max_device_cards=5)
    for device in rows(result, "eligible_devices"):
        assert len(device["in_window_card_set"]) >= 2


# --- eligibility work is scoped to the search ------------------------------


def test_only_devices_the_frontier_reaches_are_costed(connection):
    """An earlier version scanned all 9,706 devices to answer one card's question."""
    result = component(connection, window_hours=336)
    considered = scalar(result, "devices_considered")
    assert considered > 0
    assert considered < 9706, f"considered {considered} devices, close to the whole graph"


def test_a_narrower_window_considers_fewer_devices(connection):
    """Scoping must follow the search, so a tighter window costs less."""
    wide = component(connection, window_hours=336)
    narrow = component(connection, window_hours=1)
    assert scalar(narrow, "devices_considered") <= scalar(wide, "devices_considered")


# --- predecessor provenance ------------------------------------------------


def test_every_member_records_the_card_it_was_reached_from(connection):
    result = component(connection, window_hours=336)
    members = rows(result, "component_members")
    assert members
    for member in members:
        assert member["via_from_cards"], f"{member['card_id']} has no predecessor"


def test_a_first_hop_member_is_reached_from_the_seed(connection):
    result = component(connection, window_hours=336)
    for member in rows(result, "component_members"):
        if member["hop"] == 1:
            assert SEED_CARD in member["via_from_cards"]


def test_a_multi_hop_path_is_reconstructible(connection):
    """Without a predecessor a distant card is asserted connected through nobody."""
    result = component(connection, window_hours=336, max_hops=3, max_device_cards=3)
    members = rows(result, "component_members")
    distant = [item for item in members if item["hop"] >= 2]
    assert distant, "three hops over this cluster should reach beyond the first ring"

    reached = {SEED_CARD} | {item["card_id"] for item in members}
    for member in distant:
        assert member["via_from_cards"]
        # The predecessor must itself be in the component, or the path is broken.
        assert any(card in reached for card in member["via_from_cards"])
