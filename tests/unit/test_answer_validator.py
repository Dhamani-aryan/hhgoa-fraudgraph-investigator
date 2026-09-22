"""Cross-field validator tests.

These use a hand-built dataset index rather than the supplied 675 MB files, so
they run anywhere. ``tests/integration/test_validator_against_dataset.py``
runs the same validator against the real index when the data is present.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from domain.answer_models import CaseAnswer
from validation.answer_validator import validate_answer
from validation.cross_field_rules import Outcome, RunContext
from validation.dataset_ids import DatasetIndex

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
VALID = FIXTURES / "valid_answer.json"

DEVICE = "Windows | Windows 10 | chrome 65.0 | 1920x1080"


@pytest.fixture
def payload() -> dict:
    return json.loads(VALID.read_text(encoding="utf-8"))


@pytest.fixture
def index() -> DatasetIndex:
    """A small index holding exactly the identifiers the fixture uses."""
    return DatasetIndex(
        transaction_amounts={
            "3450436": 100.09,
            "3450503": 99.96,
            "3450629": 100.09,
            "3403833": 99.94,
            "3342306": 288.86,
        },
        card_ids=frozenset({"C04570-K1", "C04570-K2", "C00877-K1"}),
        customer_ids=frozenset({"C04570", "C00877"}),
        closed_case_ids=frozenset({"CC-0137", "CC-0003", "CC-9999"}),
        benchmark_case_ids=frozenset({"HHG-017", "HHG-001"}),
        device_profiles=frozenset({DEVICE}),
        closed_case_closed_at={
            "CC-0137": "2016-07-11 03:33:41",
            "CC-0003": "2016-07-05 13:34:01",
            "CC-9999": "2016-12-01 00:00:00",
        },
        benchmark_anchor_ts={"HHG-017": "2016-11-11 23:46:24"},
        benchmark_flagged_txn={"HHG-017": "3450629"},
    )


def outcomes(report) -> dict[str, str]:
    return {rule["rule_id"]: rule["outcome"] for rule in report.rules}


def failures_for(report, rule_id: str) -> list[str]:
    return next(rule["failures"] for rule in report.rules if rule["rule_id"] == rule_id)


def report_for(payload: dict, index: DatasetIndex, run: RunContext | None = None):
    return validate_answer(CaseAnswer.model_validate(payload), index, run)


# --- the fixture itself ----------------------------------------------------


def test_valid_fixture_passes_every_dataset_rule(payload, index):
    report = report_for(payload, index)
    failed = [rule["rule_id"] for rule in report.rules if rule["outcome"] == Outcome.FAILED]
    assert failed == []
    assert report.valid is True


def test_valid_fixture_is_not_submission_ready_without_a_trace(payload, index):
    """Rules needing a run trace must be skipped, not silently passed."""
    report = report_for(payload, index)
    assert report.skipped_rules, "rules needing a trace should be reported as skipped"
    assert report.ready_for_submission is False


# --- identifier existence --------------------------------------------------


def test_unknown_transaction_id_fails(payload, index):
    payload["case"]["affected_txn_ids"] = ["3450436", "9999999", "3450629"]
    payload["case"]["first_suspicious_txn_id"] = "3450436"
    report = report_for(payload, index)
    assert "9999999" in " ".join(failures_for(report, "R02"))


def test_unknown_card_id_fails(payload, index):
    payload["case"]["connected_card_ids"] = ["C99999-K1"]
    report = report_for(payload, index)
    assert "C99999-K1" in " ".join(failures_for(report, "R02"))


def test_unknown_device_profile_fails(payload, index):
    payload["case"]["connected_device_profiles"] = ["Nokia | Symbian | opera | 240x320"]
    report = report_for(payload, index)
    assert "Nokia" in " ".join(failures_for(report, "R02"))


def test_unknown_prior_case_fails(payload, index):
    payload["case"]["similar_prior_cases"] = ["CC-0137", "CC-4242"]
    report = report_for(payload, index)
    assert "CC-4242" in " ".join(failures_for(report, "R02"))


def test_case_id_absent_from_pack_fails(payload, index):
    payload["case_id"] = "HHG-999"
    report = report_for(payload, index)
    assert failures_for(report, "R01")


# --- exposure --------------------------------------------------------------


def test_exposure_must_equal_the_sum(payload, index):
    payload["case"]["exposure_usd"] = 500.00
    report = report_for(payload, index)
    assert "300.14" in " ".join(failures_for(report, "R07"))


def test_exposure_within_rounding_tolerance_passes(payload, index):
    payload["case"]["exposure_usd"] = 300.15
    report = report_for(payload, index)
    assert failures_for(report, "R07") == []


# --- routing ---------------------------------------------------------------


def test_block_card_above_threshold_must_be_l2(payload, index):
    """Routing depends on exposure, so the same action can be misrouted."""
    payload["case"]["affected_txn_ids"] = ["3450436", "3450503", "3450629", "3342306", "3403833"]
    payload["case"]["first_suspicious_txn_id"] = "3450436"
    payload["case"]["exposure_usd"] = 688.94
    payload["next_best_actions"]["final"][0]["route"] = "L2"
    report = report_for(payload, index)
    assert "requires L1" in " ".join(failures_for(report, "R10"))


def test_auto_action_marked_l1_fails(payload, index):
    payload["next_best_actions"]["final"][1]["route"] = "L1"
    report = report_for(payload, index)
    assert "CREATE_CASE" in " ".join(failures_for(report, "R10"))


def test_correct_routes_pass(payload, index):
    report = report_for(payload, index)
    assert failures_for(report, "R10") == []


# --- prior-case temporal rules ---------------------------------------------


def test_prior_case_closed_after_anchor_fails(payload, index):
    payload["case"]["similar_prior_cases"] = ["CC-0137", "CC-9999"]
    report = report_for(payload, index)
    assert "CC-9999" in " ".join(failures_for(report, "R25b"))


def test_benchmark_case_as_prior_case_fails(payload, index):
    payload["case"]["similar_prior_cases"] = ["HHG-001"]
    report = report_for(payload, index)
    assert failures_for(report, "R25a")


# --- rules that need the run trace -----------------------------------------


def test_prior_case_not_actually_retrieved_fails(payload, index):
    run = RunContext(retrieved_case_ids=frozenset({"CC-0137"}))
    report = report_for(payload, index, run)
    assert "CC-0003" in " ".join(failures_for(report, "R09"))


def test_prior_cases_retrieved_passes(payload, index):
    run = RunContext(retrieved_case_ids=frozenset({"CC-0137", "CC-0003"}))
    report = report_for(payload, index, run)
    assert failures_for(report, "R09") == []


def test_written_to_graph_without_receipt_is_skipped_not_passed(payload, index):
    report = report_for(payload, index)
    assert outcomes(report)["R17"] == Outcome.SKIPPED


def test_written_to_graph_with_failed_readback_fails(payload, index):
    run = RunContext(graph_write_confirmed=False)
    report = report_for(payload, index, run)
    assert failures_for(report, "R17")


def test_written_to_graph_with_confirmed_readback_passes(payload, index):
    run = RunContext(graph_write_confirmed=True)
    report = report_for(payload, index, run)
    assert failures_for(report, "R17") == []


def test_unwritten_case_needs_no_receipt(payload, index):
    payload["case"]["written_to_graph"] = False
    payload["case"]["graph_case_id"] = ""
    report = report_for(payload, index)
    assert outcomes(report)["R17"] == Outcome.PASSED


def test_evidence_ref_not_in_ledger_fails(payload, index):
    run = RunContext(ledger_refs=frozenset({"query:get_transaction_window_v1"}))
    report = report_for(payload, index, run)
    assert failures_for(report, "R21")


def test_future_evidence_fails(payload, index):
    run = RunContext(
        evidence_max_ts={
            "__anchor__": "2016-11-11 23:46:24",
            "ev-1": "2016-11-11 22:00:00",
            "ev-2": "2016-11-20 09:00:00",
        }
    )
    report = report_for(payload, index, run)
    assert "ev-2" in " ".join(failures_for(report, "R22"))


def test_simulated_response_may_postdate_the_anchor(payload, index):
    run = RunContext(
        evidence_max_ts={
            "__anchor__": "2016-11-11 23:46:24",
            "evidence_request:1": "2016-11-12 10:00:00",
        },
        simulated_refs=frozenset({"evidence_request:1"}),
    )
    report = report_for(payload, index, run)
    assert failures_for(report, "R22") == []


def test_decisive_probability_needs_two_independence_groups(payload, index):
    refs = [item["ref"] for item in payload["case"]["evidence"]]
    run = RunContext(independence_groups=dict.fromkeys(refs, "device_network"))
    report = report_for(payload, index, run)
    assert failures_for(report, "R23")


def test_two_independence_groups_satisfy_the_stopping_rule(payload, index):
    refs = [item["ref"] for item in payload["case"]["evidence"]]
    groups = dict(
        zip(refs, ["temporal_sequence", "device_network", "customer_response"], strict=True)
    )
    run = RunContext(independence_groups=groups)
    report = report_for(payload, index, run)
    assert failures_for(report, "R23") == []


def test_block_all_cards_needs_r10_evidence(payload, index):
    payload["next_best_actions"]["final"].append(
        {"action": "BLOCK_ALL_CARDS", "route": "L2", "reason": "R10"}
    )
    run = RunContext(
        customer_confirmed_fraud_cards=frozenset({"C04570-K1"}),
        credentials_confirmed_compromised=False,
    )
    report = report_for(payload, index, run)
    assert failures_for(report, "R15")


def test_block_all_cards_with_two_compromised_cards_passes(payload, index):
    payload["next_best_actions"]["final"].append(
        {"action": "BLOCK_ALL_CARDS", "route": "L2", "reason": "R10"}
    )
    run = RunContext(
        customer_confirmed_fraud_cards=frozenset({"C04570-K1", "C04570-K2"}),
        credentials_confirmed_compromised=False,
    )
    report = report_for(payload, index, run)
    assert failures_for(report, "R15") == []


def test_shared_origin_claim_without_coordination_fails(payload, index):
    payload["case"]["connected_card_ids"] = ["C00877-K1"]
    run = RunContext(shared_origin_supported=False)
    report = report_for(payload, index, run)
    assert failures_for(report, "R24")


def test_memory_epoch_leak_fails(payload, index):
    payload["case"]["similar_prior_cases"] = ["CC-0137", "CC-0003"]
    run = RunContext(active_memory_epoch_case_ids=frozenset({"CC-0003"}))
    report = report_for(payload, index, run)
    assert "CC-0003" in " ".join(failures_for(report, "R25c"))


# --- fully checked answer --------------------------------------------------


def test_answer_with_a_complete_trace_is_submission_ready(payload, index):
    refs = [item["ref"] for item in payload["case"]["evidence"]]
    run = RunContext(
        ledger_refs=frozenset(refs),
        policy_refs=frozenset({"policy:R1", "policy:R2"}),
        retrieved_case_ids=frozenset({"CC-0137", "CC-0003"}),
        independence_groups=dict(
            zip(refs, ["temporal_sequence", "device_network", "customer_response"], strict=True)
        ),
        graph_write_confirmed=True,
        active_memory_epoch_case_ids=frozenset(),
        evidence_max_ts={"__anchor__": "2016-11-11 23:46:24"}
        | dict.fromkeys(refs, "2016-11-11 23:46:24"),
        simulated_refs=frozenset({"evidence_request:1"}),
        shared_origin_supported=True,
        customer_confirmed_fraud_cards=frozenset(),
        credentials_confirmed_compromised=False,
    )
    report = report_for(payload, index, run)
    assert report.failed_rules == []
    assert report.skipped_rules == []
    assert report.ready_for_submission is True


def test_mutating_one_field_breaks_submission_readiness(payload, index):
    """Guards against the readiness check being trivially true."""
    broken = copy.deepcopy(payload)
    broken["case"]["exposure_usd"] = 1.0
    report = report_for(broken, index)
    assert report.ready_for_submission is False
