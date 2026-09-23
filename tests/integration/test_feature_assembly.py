"""The complete feature vector, assembled live through the official MCP server.

Two benchmark fixtures, chosen for what they exercise:

* HHG-019 -- a shared device joining the card to a six-card WCC component
  whose other members all carry confirmed fraud, with path segments.
* HHG-017 -- a device shared too widely to imply coordination, region and
  email sections withheld by budget, and an isolated WCC component.
"""

from __future__ import annotations

import dataclasses

import pytest

from evidence.collector import CaseCollectionError, CaseTrigger, collect_graph_results
from evidence.feature_assembler import assemble_features
from graph.client import TigerGraphConfigError, load_config
from graph.mcp_client import MCPSession
from graph.tool_port import CallBudget, MCPGraphToolPort, canonical

HHG_019 = CaseTrigger(
    case_id="HHG-019",
    flagged_txn_id="3503878",
    card_id="C07987-K2",
    customer_id="C07987",
    trigger_type="risk_score",
    trigger_text="Real-time model scored transaction 3503878 ($99.92, online) at 0.90.",
    opened_at="2016-12-01 22:28:53",
    risk_score=0.90,
)
HHG_017 = CaseTrigger(
    case_id="HHG-017",
    flagged_txn_id="3450629",
    card_id="C04570-K1",
    customer_id="C04570",
    trigger_type="risk_score",
    trigger_text="Real-time model scored transaction 3450629 ($100.09, online) at 0.57.",
    opened_at="2016-11-12 00:46:24",
    risk_score=0.57,
)


@pytest.fixture(scope="module")
def session():
    try:
        config = load_config()
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")
    live = MCPSession(config).start()
    yield live
    live.close()


def assembled(session, trigger):
    port = MCPGraphToolPort(session, budget=CallBudget(12))
    collected = collect_graph_results(port, trigger)
    return (
        collected,
        assemble_features(trigger.case_id, collected.anchor_time, collected.values),
        port,
    )


@pytest.fixture(scope="module")
def hhg019(session):
    return assembled(session, HHG_019)


@pytest.fixture(scope="module")
def hhg017(session):
    return assembled(session, HHG_017)


# --- the vector through MCP -------------------------------------------------------------


def test_every_structural_call_went_through_mcp_within_budget(hhg019):
    _, _, port = hhg019
    assert {record.adapter for record in port.log.records} == {"mcp"}
    assert all(record.ok for record in port.log.records)
    assert port.budget.used == 9, (
        "context, baseline, window, features, two shared, region, wcc, exposure"
    )


def test_the_anchor_is_the_flagged_transaction_time(hhg019):
    collected, vector, _ = hhg019
    assert vector.anchor_time == "2016-12-01 17:28:53"
    assert collected.anchor_time < HHG_019.opened_at


def test_no_feature_rests_on_data_after_the_anchor(hhg019, hhg017):
    for _, vector, _ in (hhg019, hhg017):
        assert vector.leakage_check_passed, vector.leakage_violations
        assert vector.data_max_time <= vector.anchor_time


def test_hhg019_exercises_the_shared_origin_and_the_component(hhg019):
    _, vector, _ = hhg019
    assert vector.value("device_is_novel_for_card") is True
    assert vector.value("shared_device_is_supernode") is False
    assert vector.value("shared_device_fraud_enrichment_ratio") == 1.0
    assert vector.value("wcc_component_size") == 6
    assert len(vector.value("wcc_fraud_enriched_members")) == 5
    assert vector.value("amount_deviation_state") == "defined"


def test_hhg017_marks_withheld_and_refused_sections_as_unknown(hhg017):
    _, vector, _ = hhg017
    for name in ("region_degree_to_anchor", "email_degree_to_anchor"):
        assert vector.state(name) == "withheld"
        assert vector.value(name) is None
    assert vector.value("shared_device_is_supernode") is True
    assert vector.state("shared_device_fraud_enrichment_ratio") == "refused"
    assert vector.value("wcc_isolated") is True
    assert vector.value("wcc_path_segments") == []


def test_resource_prechecks_never_become_features(hhg019):
    _, vector, _ = hhg019
    assert not [name for name in vector.features if "precheck" in name or "lifetime" in name]


# --- exact WCC provenance --------------------------------------------------------------


def test_every_two_hop_card_is_backed_by_returned_segments(hhg019):
    _, vector, _ = hhg019
    segments = vector.value("wcc_path_segments")
    seed = HHG_019.card_id
    assert segments and vector.value("wcc_path_segments_truncated") is False
    by_target = {item["to_card"]: item for item in segments}
    for card in vector.value("two_hop_reachable_cards"):
        step = by_target[card]
        assert step["hop"] <= 2
        if step["hop"] == 2:
            assert by_target[step["from_card"]]["from_card"] == seed
        else:
            assert step["from_card"] == seed


# --- exposure --------------------------------------------------------------------------


def test_candidate_exposure_agrees_with_the_local_sum(hhg019, hhg017):
    for _, vector, _ in (hhg019, hhg017):
        assert vector.value("candidate_episode_exposure_agrees") is True
    assert hhg017[1].value("candidate_episode_exposure_usd") == pytest.approx(300.14)
    assert hhg017[1].value("candidate_episode_txn_ids") == ["3450436", "3450503", "3450629"]


# --- later reviews ---------------------------------------------------------------------


def test_a_later_review_date_does_not_change_anchor_time_features(session, hhg019):
    later = dataclasses.replace(HHG_019, opened_at="2016-12-31 23:59:59")
    _, reviewed, _ = assembled(session, later)
    _, original, _ = hhg019
    assert canonical(reviewed.model_dump()["features"]) == canonical(
        original.model_dump()["features"]
    )


# --- missing entities --------------------------------------------------------------------


def test_an_unknown_flagged_transaction_is_a_useful_error(session):
    unknown = dataclasses.replace(HHG_019, flagged_txn_id="9999999999")
    port = MCPGraphToolPort(session, budget=CallBudget(12))
    with pytest.raises(CaseCollectionError, match="does not exist"):
        collect_graph_results(port, unknown)


def test_a_card_mismatch_is_a_useful_error(session):
    wrong = dataclasses.replace(HHG_019, card_id=HHG_017.card_id)
    port = MCPGraphToolPort(session, budget=CallBudget(12))
    with pytest.raises(CaseCollectionError, match="belongs to"):
        collect_graph_results(port, wrong)
