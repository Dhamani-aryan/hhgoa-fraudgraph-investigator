"""The feature assembler and the robust amount statistics, without a graph."""

from __future__ import annotations

import copy
import math

import pytest

from evidence.feature_assembler import assemble_features, episode_rows
from scoring.robust_baselines import (
    amount_stats,
    empirical_percentile,
    history_without_flagged,
    mad,
    median,
)

ANCHOR = "2016-12-01 17:28:53"
FLAGGED = {
    "txn_id": "T9",
    "ts": ANCHOR,
    "amount": 99.92,
    "channel": "online",
    "risk_score": 0.9,
    "addr1": "204.0",
    "card_id": "C1-K1",
}


def results() -> dict:
    """A complete, admissible set of normalized results for one case."""
    return {
        "context": {
            "refused": False,
            "flagged_transaction": [FLAGGED],
            "device": [{"device_id": "d1", "new_or_found": "New", "proxy_category": ""}],
            "prior_cases_on_card": [
                {
                    "case_id": "CC-1",
                    "outcome": "confirmed_fraud",
                    "pattern": "x",
                    "closed_at": "2016-08-17 00:00:00",
                }
            ],
            "device_precheck_lifetime_transactions": 999999,
        },
        "baseline": {
            "refused": False,
            "scan_skipped": False,
            "last_seen": ANCHOR,
            "amounts_to_anchor": [50.0, 100.0, 150.0, 99.92],
            "precheck_lifetime_transactions": 5,
        },
        "window": {
            "refused": False,
            "window_truncated": False,
            "window_transactions": [
                {"txn_id": "T7", "ts": "2016-12-01 10:00:00", "amount": 10.0, "channel": "online"},
                {
                    "txn_id": "T8",
                    "ts": "2016-12-01 11:00:00",
                    "amount": 20.0,
                    "channel": "in_person",
                },
                {"txn_id": "T9", "ts": ANCHOR, "amount": 99.92, "channel": "online"},
            ],
        },
        "features": {
            "refused": False,
            "effective_cutoff": ANCHOR,
            "card_degree_1h": 1,
            "card_degree_24h": 3,
            "card_degree_7d": 4,
            "card_degree_to_cutoff": 220,
            "burst_transitions": 0,
            "burst_gap_seconds": 600,
            "device": [{"device_id": "d1"}],
            "device_scan_skipped": False,
            "device_is_novel_for_card": True,
            "device_degree_1h": 1,
            "device_degree_24h": 1,
            "device_degree_7d": 2,
            "device_degree_to_cutoff": 2,
            "device_distinct_cards_in_window": 2,
            "device_distinct_customers_in_window": 2,
            "device_fraud_neighbour_cards": 1,
            "device_cleared_neighbour_cards": 0,
            "latest_fraud_neighbour_closure": "2016-10-27 23:00:00",
            "latest_cleared_neighbour_closure": "1970-01-01 00:00:00",
            "region_scan_skipped": True,
            "region_features_withheld_reason": "over budget",
            "region_precheck_lifetime_transactions": 42035,
            "email_scan_skipped": False,
            "email_degree_1h": 0,
            "email_degree_24h": 0,
            "email_degree_7d": 5,
            "email_degree_to_cutoff": 90,
            "email_distinct_cards_in_window": 7,
        },
        "shared_device": {
            "refused": False,
            "effective_cutoff": ANCHOR,
            "entity_cards_to_cutoff": 2,
            "refused_as_supernode": False,
            "refused_over_scan_budget": False,
            "refused_unknown_entity": False,
            "supernode_threshold": 100,
            "distinct_cards_in_window": 1,
            "fraud_enriched_card_count": 1,
            "cards_with_confirmed_fraud": ["C2-K1"],
            "prior_fraud_cases": [{"case_id": "CC-2", "closed_at": "2016-10-27 23:00:00"}],
            "shared_transactions": [{"txn_id": "T5", "ts": "2016-11-30 00:00:00"}],
        },
        "shared_region": {
            "refused": True,
            "refused_over_scan_budget": True,
            "refused_unknown_entity": False,
            "effective_cutoff": ANCHOR,
            "refusal_reason": "entity volume exceeds the scan budget",
        },
        "region": {
            "refused": False,
            "flagged_region": "204.0",
            "flagged_ts": ANCHOR,
            "region_is_new_for_card": False,
            "flagged_region_prior_count": 5,
            "flagged_region_last_seen": "2016-11-30 00:00:00",
            "other_region_activity_in_window": 0,
            "concurrent_other_region_activity": [],
        },
        "wcc": {
            "refused": False,
            "seed_card_id": "C1-K1",
            "effective_cutoff": ANCHOR,
            "component_size": 4,
            "fraud_enriched_cards": ["C1-K1", "C2-K1", "C4-K1"],
            "component_prior_fraud_cases": [
                {"case_id": "CC-2", "closed_at": "2016-10-27 23:00:00"}
            ],
            "path_segments_truncated": False,
            "path_segments": [
                {"from_card": "C1-K1", "device_id": "d1", "to_card": "C2-K1", "hop": 1},
                {"from_card": "C2-K1", "device_id": "d2", "to_card": "C3-K1", "hop": 2},
                {"from_card": "C3-K1", "device_id": "d3", "to_card": "C4-K1", "hop": 3},
            ],
        },
        "exposure": {
            "refused": False,
            "exposure_usd": 109.92,
            "missing_txn_ids": [],
            "excluded_after_cutoff": [],
            "transactions": [
                {"txn_id": "T7", "ts": "2016-12-01 10:00:00"},
                {"txn_id": "T9", "ts": ANCHOR},
            ],
        },
    }


def assemble(data=None):
    return assemble_features("CASE", ANCHOR, data or results())


# --- robust statistics -----------------------------------------------------------


def test_median_and_mad():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 2, 3]) == 2.5
    assert mad([1, 2, 3, 4, 100]) == 1


def test_percentile_counts_ties_half():
    assert empirical_percentile([5, 5, 5], 5) == 0.5
    assert empirical_percentile([1, 2, 3, 4], 10) == 1.0
    assert empirical_percentile([1, 2, 3, 4], 0) == 0.0


def test_a_zero_mad_leaves_the_deviation_undefined_not_zero():
    stats = amount_stats([9.99, 9.99, 9.99], 250.0)
    assert stats.deviation_state == "zero_mad"
    assert stats.robust_deviation is None
    assert stats.amount_equals_constant_history is False
    assert amount_stats([9.99, 9.99], 9.99).amount_equals_constant_history is True


def test_the_deviation_is_scaled_mad():
    stats = amount_stats([10, 20, 30, 40, 50], 130)
    assert stats.deviation_state == "defined"
    assert math.isclose(stats.robust_deviation, 0.6745 * (130 - 30) / 10)


def test_no_history_is_its_own_state():
    assert amount_stats([], 10).deviation_state == "no_history"


def test_the_flagged_amount_is_removed_once_from_its_own_history():
    assert history_without_flagged([5.0, 10.0, 10.0], 10.0) == [5.0, 10.0]


# --- the assembled vector ------------------------------------------------------------


def test_features_from_every_source_are_present():
    vector = assemble()
    for name in (
        "card_velocity_1h",
        "device_degree_to_anchor",
        "email_degree_7d",
        "amount_robust_deviation",
        "region_is_new_for_card",
        "shared_device_rarity",
        "wcc_component_size",
        "two_hop_reachable_cards",
        "candidate_episode_exposure_usd",
        "trigger_risk_score",
    ):
        assert vector.state(name) == "available", name


def test_a_withheld_scan_is_withheld_not_zero():
    vector = assemble()
    for name in ("region_degree_1h", "region_degree_to_anchor", "region_distinct_cards_in_window"):
        assert vector.state(name) == "withheld"
        assert vector.value(name) is None
    assert vector.features["region_degree_1h"].reason == "over budget"


def test_a_budget_refused_shared_entity_is_withheld():
    vector = assemble()
    assert vector.state("shared_region_fraud_enrichment_ratio") == "withheld"


def test_a_supernode_is_a_finding_and_its_coordination_features_are_refused():
    data = results()
    data["shared_device"].update(
        refused=True,
        refused_as_supernode=True,
        refusal_reason="shared too widely",
        entity_cards_to_cutoff=164,
    )
    vector = assemble(data)
    assert vector.value("shared_device_is_supernode") is True
    assert vector.value("shared_device_cards_to_anchor") == 164
    assert vector.state("shared_device_fraud_enrichment_ratio") == "refused"


def test_unavailable_zero_and_false_are_distinct():
    vector = assemble()
    assert vector.value("burst_transitions") == 0  # a real zero
    assert vector.value("region_is_new_for_card") is False  # a real false
    assert vector.value("region_degree_1h") is None  # withheld
    assert vector.state("region_degree_1h") != vector.state("burst_transitions")


def test_a_case_without_a_device_marks_device_features_not_applicable():
    data = results()
    data["context"]["device"] = []
    data["features"]["device"] = []
    data.pop("shared_device")
    vector = assemble(data)
    assert vector.state("device_degree_to_anchor") == "not_applicable"
    assert vector.state("shared_device_rarity") == "not_applicable"


def test_a_refused_query_marks_its_features_refused():
    data = results()
    data["wcc"] = {"refused": True, "refusal_reason": "no PaymentCard has this seed_card_id"}
    vector = assemble(data)
    assert vector.state("wcc_component_size") == "refused"
    assert "seed_card_id" in vector.features["wcc_component_size"].reason


def test_a_query_that_did_not_run_is_unavailable():
    data = results()
    data.pop("baseline")
    assert assemble(data).state("amount_median_usd") == "unavailable"


def test_zero_mad_history_in_the_vector():
    data = results()
    data["baseline"]["amounts_to_anchor"] = [99.92, 99.92, 99.92, 99.92]
    vector = assemble(data)
    assert vector.value("amount_deviation_state") == "zero_mad"
    assert vector.state("amount_robust_deviation") == "not_applicable"
    assert vector.value("amount_equals_constant_history") is True


def test_resource_prechecks_never_become_features():
    vector = assemble()
    assert not [name for name in vector.features if "lifetime" in name or "precheck" in name]


# --- two-hop reach and WCC provenance --------------------------------------------------


def test_two_hop_reach_is_derived_only_from_returned_segments():
    vector = assemble()
    assert vector.value("two_hop_reachable_cards") == ["C2-K1", "C3-K1"]
    assert vector.value("two_hop_fraud_reachable_cards") == ["C2-K1"]
    # C4-K1 is three hops away: in the component, not within two.
    assert "C4-K1" in vector.value("wcc_fraud_enriched_members")


def test_the_seed_is_not_counted_as_its_own_fraud_neighbour():
    assert "C1-K1" not in assemble().value("wcc_fraud_enriched_members")


def test_path_segments_are_ordered_deterministically():
    data = results()
    data["wcc"]["path_segments"] = list(reversed(data["wcc"]["path_segments"]))
    assert assemble(data).value("wcc_path_segments") == assemble().value("wcc_path_segments")


# --- exposure ---------------------------------------------------------------------------


def test_the_candidate_episode_is_same_channel_plus_the_flagged_transaction():
    rows = results()["window"]["window_transactions"]
    assert [item["txn_id"] for item in episode_rows(rows, FLAGGED)] == ["T7", "T9"]


def test_exposure_agrees_with_the_local_sum():
    vector = assemble()
    assert vector.value("candidate_episode_exposure_usd") == 109.92
    assert vector.value("candidate_episode_local_sum_usd") == 109.92
    assert vector.value("candidate_episode_exposure_agrees") is True


def test_an_exposure_disagreement_is_reported():
    data = results()
    data["exposure"]["exposure_usd"] = 500.0
    assert assemble(data).value("candidate_episode_exposure_agrees") is False


def test_a_truncated_window_withholds_the_episode():
    data = results()
    data["window"]["window_truncated"] = True
    assert assemble(data).state("candidate_episode_exposure_usd") == "withheld"


# --- leakage ------------------------------------------------------------------------------


def test_an_admissible_case_passes_the_leakage_check():
    vector = assemble()
    assert vector.leakage_check_passed is True
    assert vector.data_max_time == ANCHOR


@pytest.mark.parametrize(
    ("role", "path", "value"),
    [
        ("window", ("window_transactions", 0, "ts"), "2016-12-02 00:00:00"),
        ("shared_device", ("prior_fraud_cases", 0, "closed_at"), "2016-12-05 00:00:00"),
        ("wcc", ("effective_cutoff",), "2016-12-09 00:00:00"),
        ("context", ("prior_cases_on_card", 0, "closed_at"), "2016-12-30 00:00:00"),
    ],
)
def test_any_future_source_timestamp_fails_the_leakage_check(role, path, value):
    data = copy.deepcopy(results())
    target = data[role]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    vector = assemble(data)
    assert vector.leakage_check_passed is False
    assert vector.leakage_violations


def test_the_anchor_must_be_a_timestamp():
    with pytest.raises(ValueError):
        assemble_features("CASE", "yesterday", results())
