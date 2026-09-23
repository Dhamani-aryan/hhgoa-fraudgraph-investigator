"""The GraphRAG evidence package and its citation validation, without a graph.

A fake adapter built on the real port base class answers every installed query
from fixed results, so the package is built by exactly the code the live path
uses -- parameter validation, budget and call records included.
"""

from __future__ import annotations

import pytest

from evidence.citations import validate_package
from evidence.collector import CaseTrigger
from evidence.context_builder import build_evidence_package
from evidence.ledger import verify_chain
from evidence.models import SECTIONS
from graph.tool_port import CallBudget, _BasePort
from tests.unit.test_feature_assembler import ANCHOR, results
from tests.unit.test_retrievers import CANDIDATES, POLICY_HITS

TRIGGER = CaseTrigger(
    case_id="HHG-900",
    flagged_txn_id="T9",
    card_id="C1-K1",
    customer_id="C1",
    trigger_type="risk_score",
    trigger_text="fixture",
    opened_at="2016-12-01 22:28:53",
    risk_score=0.9,
)


class FakeAdapter(_BasePort):
    adapter = "mcp"
    tool = "fake"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        data = results()
        data["context"]["card"] = [{"card_id": "C1-K1", "customer_id": "C1"}]
        data["context"]["cardholder"] = [{"customer_id": "C1"}]
        data["features"]["fraud_neighbour_card_ids"] = ["C2-K1"]
        data["shared_device"]["cards_in_window"] = ["C2-K1"]
        data["region"]["flagged_region"] = "204.0"
        data["region"]["region_code"] = "204.0"
        self.data = data

    def _execute(self, name, params):
        by_query = {
            "get_case_context_v1": "context",
            "get_card_baseline_v1": "baseline",
            "get_transaction_window_v1": "window",
            "extract_temporal_graph_features_v1": "features",
            "find_region_anomalies_v1": "region",
            "wcc_shared_origin_v1": "wcc",
            "calculate_case_exposure_v1": "exposure",
        }
        if name == "find_shared_origin_activity_v1":
            values = self.data[
                "shared_device" if params["entity_kind"] == "device" else "shared_region"
            ]
        elif name == "find_similar_closed_cases_v1":
            values = {
                "admissible": CANDIDATES,
                "admissibility_cutoff": params["as_of_ts"],
                "admissible_pool_size": 5565,
                "fraud_pool_size": 10,
                "cleared_pool_size": 5,
                "shared_origin_pool_size": 1,
            }
        elif name == "find_policy_chunks_v1":
            values = {"hits": POLICY_HITS}
        else:
            values = self.data[by_query[name]]
        return [{key: value} for key, value in values.items()]


def build(**kwargs):
    return build_evidence_package(
        FakeAdapter(budget=CallBudget(12)), TRIGGER, created_at="2026-09-23T00:00:00Z", **kwargs
    )


@pytest.fixture(scope="module")
def package():
    return build()


def replace_item(package, target_id, **update):
    sections = {
        section: [
            item.model_copy(update=update) if item.evidence_id == target_id else item
            for item in items
        ]
        for section, items in package.sections.items()
    }
    return package.model_copy(update={"sections": sections})


def first(package, predicate):
    return next(item for item in package.items() if predicate(item))


def failing(report):
    return {check.name for check in report.failed()}


# --- the package ---------------------------------------------------------------------------


def test_a_well_formed_package_validates(package):
    report = validate_package(package)
    assert report.passed, [(c.name, c.failures) for c in report.failed()]


def test_the_package_has_four_separated_sections(package):
    assert tuple(package.sections) == SECTIONS
    assert all(package.sections[section] for section in SECTIONS)


def test_the_package_holds_supporting_contradicting_and_neutral_evidence(package):
    counts = package.counts()["strength"]
    assert counts["supporting"] and counts["contradicting"] and counts["neutral"]


def test_withheld_sections_are_neutral_and_named(package):
    withheld = [item for item in package.items() if item.availability == "withheld"]
    assert withheld
    assert all(item.strength == "neutral" for item in withheld)
    assert "region_degree_to_anchor" in package.metadata.withheld_or_unavailable["withheld"]


def test_every_item_carries_full_provenance(package):
    for item in package.items():
        assert item.evidence_id.startswith("EV-HHG-900-")
        assert item.ref and item.query_bundle_version == "v1"
        assert item.anchor_time == ANCHOR
        assert item.independence_group
        assert len(item.content_hash) == 64 and len(item.previous_hash) == 64


def test_the_ledger_chain_is_intact(package):
    assert verify_chain(package.items()) == []
    assert package.ledger_final_hash == package.items()[-1].content_hash


def test_the_wcc_claim_carries_its_segments(package):
    wcc = first(package, lambda item: item.query_name == "wcc_shared_origin_v1")
    assert wcc.path_segments and wcc.strength == "supporting"


def test_metadata_records_the_port_and_every_call(package):
    meta = package.metadata
    assert meta.primary_adapter == "mcp" and meta.fallback_occurred is False
    assert meta.graph_call_count == len(meta.calls) == 11
    assert len(meta.mcp_trace_ids) == 11
    assert meta.anchor_time == ANCHOR and meta.data_max_time <= ANCHOR


def test_building_twice_gives_the_same_package(package):
    again = build()
    assert again.package_id == package.package_id
    assert again.ledger_final_hash == package.ledger_final_hash
    assert [i.claim for i in again.items()] == [i.claim for i in package.items()]


def test_the_trigger_risk_score_is_never_supporting_evidence(package):
    trigger = first(package, lambda item: item.independence_group == "trigger_model")
    assert trigger.strength == "neutral"


# --- every validator failure ---------------------------------------------------------------


def test_a_missing_evidence_id_fails(package):
    target = package.items()[0].evidence_id
    report = validate_package(replace_item(package, target, evidence_id=""))
    assert "evidence_ids_present_unique_and_well_formed" in failing(report)


def test_an_unresolvable_entity_fails(package):
    target = package.items()[1]
    report = validate_package(
        replace_item(package, target.evidence_id, entity_ids=[*target.entity_ids, "C99999-K9"])
    )
    assert "every_entity_id_resolves" in failing(report)


def test_a_missing_policy_anchor_fails(package):
    target = first(package, lambda item: item.section == "policy_context")
    report = validate_package(replace_item(package, target.evidence_id, ref="policy:R99"))
    assert "policy_anchors_resolve" in failing(report)


def test_a_prior_case_that_was_not_retrieved_fails(package):
    target = first(package, lambda item: item.section == "case_memory")
    report = validate_package(
        replace_item(package, target.evidence_id, entity_ids=["CC-7777", target.entity_ids[1]])
    )
    assert "cited_prior_cases_were_retrieved_with_score_and_reasons" in failing(report)


def test_a_similar_case_without_reasons_fails(package):
    retrieval = package.prior_case_retrieval
    stripped = retrieval.model_copy(
        update={
            "cases": [retrieval.cases[0].model_copy(update={"reasons": []}), *retrieval.cases[1:]]
        }
    )
    report = validate_package(package.model_copy(update={"prior_case_retrieval": stripped}))
    assert "cited_prior_cases_were_retrieved_with_score_and_reasons" in failing(report)


def test_a_similar_case_without_a_positive_score_fails(package):
    retrieval = package.prior_case_retrieval
    zeroed = retrieval.model_copy(
        update={
            "cases": [
                retrieval.cases[0].model_copy(update={"composite_retrieval_score": 0.0}),
                *retrieval.cases[1:],
            ]
        }
    )
    report = validate_package(package.model_copy(update={"prior_case_retrieval": zeroed}))
    assert "cited_prior_cases_were_retrieved_with_score_and_reasons" in failing(report)


def test_a_claim_after_the_anchor_fails(package):
    target = package.items()[2].evidence_id
    report = validate_package(replace_item(package, target, data_max_time="2016-12-02 00:00:00"))
    assert "no_claim_crosses_the_anchor" in failing(report)


def test_a_resource_precheck_in_evidence_fails(package):
    target = package.items()[1].evidence_id
    report = validate_package(
        replace_item(package, target, value={"device_precheck_lifetime_transactions": 621})
    )
    assert "no_resource_precheck_in_evidence" in failing(report)


def test_exceeding_a_cap_fails(package):
    report = validate_package(package, caps={**package.metadata.caps, "prior_cases": 1})
    assert "package_is_within_caps_with_all_sections" in failing(report)


def test_a_claim_without_a_source_reference_fails(package):
    target = package.items()[0].evidence_id
    report = validate_package(replace_item(package, target, ref=""))
    assert "every_claim_has_a_source_reference" in failing(report)


def test_a_wcc_claim_without_segments_fails(package):
    target = first(package, lambda item: item.query_name == "wcc_shared_origin_v1")
    report = validate_package(replace_item(package, target.evidence_id, path_segments=None))
    assert "wcc_claims_rest_on_returned_path_segments" in failing(report)


def test_a_wcc_segment_through_an_unreturned_device_fails(package):
    target = first(package, lambda item: item.query_name == "wcc_shared_origin_v1")
    forged = [dict(target.path_segments[0], device_id="nosuchdevice")]
    report = validate_package(replace_item(package, target.evidence_id, path_segments=forged))
    assert "wcc_claims_rest_on_returned_path_segments" in failing(report)


def test_an_unavailable_item_marked_negative_fails(package):
    target = first(package, lambda item: item.availability == "withheld")
    report = validate_package(replace_item(package, target.evidence_id, strength="contradicting"))
    assert "unavailable_evidence_is_never_negative" in failing(report)


def test_an_edited_claim_breaks_the_hash_chain(package):
    target = package.items()[3].evidence_id
    report = validate_package(replace_item(package, target, claim="rewritten after the fact"))
    assert "hash_chain_is_intact" in failing(report)


def test_an_empty_section_fails(package):
    sections = dict(package.sections, policy_context=[])
    report = validate_package(package.model_copy(update={"sections": sections}))
    assert "package_is_within_caps_with_all_sections" in failing(report)
