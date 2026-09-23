"""The case writer's receipt, exercised without a graph.

The live round trip is in tests/integration/test_investigation_case_write.py.
These tests pin the decision the receipt makes: it is ``ok`` only when the
write was complete AND an independent read-back agreed with the payload, and
every kind of disagreement is named rather than collapsed into a boolean.
"""

from __future__ import annotations

import copy

import pytest

from graph.case_writer import READ_QUERY, WRITE_QUERY, verify_read_back, write_case

PAYLOAD = {
    "case_id": "UNIT-CASE",
    "memory_epoch": "unit_epoch",
    "status": "closed_fraud",
    "verdict": "fraud",
    "fraud_probability": 0.86,
    "pattern": "card_testing",
    "pattern_description": "",
    "exposure_usd": 300.14,
    "first_suspicious_txn_id": "T1",
    "summary": "Unit fixture.",
    "stop_reason": "fixture",
    "initial_actions": "VERIFY_WITH_CUSTOMER",
    "final_actions": "BLOCK_CARD|CREATE_CASE",
    "sar_filed": False,
    "sar_narrative": "",
    "opened_at": "2016-11-12 00:46:24",
    "anchor_time": "2016-11-11 23:46:24",
    "query_bundle_version": "v1",
    "scoring_version": "v1",
    "policy_version": "1.0",
    "prompt_version": "v1",
    "code_commit": "fixture",
    "answer_json": "{}",
    "memory_text": "memory",
    "affected_txn_ids": ["T1", "T2"],
    "connected_card_ids": ["C2-K1"],
    "device_profile_ids": ["dev1"],
    "similar_case_ids": ["CC-1", "CC-2"],
    "policy_chunk_ids": ["policy:R2"],
    "on_card_id": "C1-K1",
}
SIMILARITY = {"CC-1": 0.82, "CC-2": 0.41}
REASONS = {"CC-1": "same_new_device", "CC-2": "opposite_outcome"}


def vertex(attributes: dict) -> dict:
    return {"v_id": next(iter(attributes.values())), "attributes": attributes}


def id_block(name: str, key: str, ids: list[str]) -> dict:
    return {name: [vertex({key: item}) for item in ids]}


def check(payload: dict, result) -> list[str]:
    return verify_read_back(payload, result, similarity=SIMILARITY, reasons=REASONS)


def read_result(payload: dict, similarity=SIMILARITY, reasons=REASONS) -> list[dict]:
    """What read_investigation_case_v1 returns for a faithful write of payload."""
    stored = {name: payload[name] for name in payload if not name.endswith("_ids")}
    stored.pop("on_card_id", None)
    stored["written_at"] = "2026-09-23 12:00:00"
    stored = {f"stored.{name}": value for name, value in stored.items()}
    return [
        {"found": True},
        {"investigation_case": [vertex(stored)]},
        id_block("affected_transactions", "affected.txn_id", payload["affected_txn_ids"]),
        id_block("connected_cards", "connected.card_id", payload["connected_card_ids"]),
        id_block("on_card", "on_card.card_id", [payload["on_card_id"]]),
        id_block("device_profiles", "devices.device_id", payload["device_profile_ids"]),
        {
            "similar_prior_cases": [
                vertex(
                    {
                        "similar.case_id": k,
                        "similarity": similarity.get(k, 0.0),
                        "reasons": reasons.get(k, ""),
                    }
                )
                for k in payload["similar_case_ids"]
            ]
        },
        id_block("cited_policy_chunks", "cited.chunk_id", payload["policy_chunk_ids"]),
        {"affected_txn_edge_count": len(payload["affected_txn_ids"])},
        {"connected_card_edge_count": len(payload["connected_card_ids"])},
        {"on_card_edge_count": 1},
        {"device_edge_count": len(payload["device_profile_ids"])},
        {"similar_case_edge_count": len(payload["similar_case_ids"])},
        {"policy_chunk_edge_count": len(payload["policy_chunk_ids"])},
    ]


def write_result(complete: bool = True) -> list[dict]:
    return [
        {"write_complete": complete},
        {"unmatched_txn_ids": []},
        {"unmatched_card_ids": []},
        {"unmatched_case_ids": []},
        {"unmatched_device_ids": []},
        {"unmatched_policy_chunk_ids": []},
        {"unmatched_on_card_id": ""},
    ]


def set_block(result: list[dict], name: str, value) -> list[dict]:
    result = copy.deepcopy(result)
    for block in result:
        if name in block:
            block[name] = value
    return result


class FakeConnection:
    """Answers the write with ``written`` and the read with ``read``."""

    def __init__(self, written, read, *, read_raises: Exception | None = None):
        self.written, self.read, self.read_raises = written, read, read_raises
        self.calls: list[str] = []
        self.upserts: list[tuple] = []

    def runInstalledQuery(self, name, params=None, usePost=False):  # noqa: N802
        self.calls.append(name)
        if name == WRITE_QUERY:
            return self.written
        if name == READ_QUERY:
            if self.read_raises:
                raise self.read_raises
            return self.read
        raise AssertionError(f"unexpected query {name}")

    def upsertEdge(self, *args):  # noqa: N802
        self.upserts.append(args)


def run(read, *, written=None, read_raises=None, payload=PAYLOAD):
    connection = FakeConnection(written or write_result(), read, read_raises=read_raises)
    receipt = write_case(connection, payload, similarity=SIMILARITY, reasons=REASONS)
    return receipt, connection


# --- the verified path -----------------------------------------------------


def test_a_faithful_read_back_verifies():
    receipt, connection = run(read_result(PAYLOAD))
    assert receipt.read_back_mismatches == []
    assert receipt.read_back_verified is True
    assert receipt.ok is True
    assert receipt.written_to_graph is True
    assert receipt.graph_case_id == "UNIT-CASE"


def test_the_read_back_is_a_separate_query_after_the_write():
    _, connection = run(read_result(PAYLOAD))
    assert connection.calls == [WRITE_QUERY, READ_QUERY]


# --- ok needs all three conditions -----------------------------------------


def test_an_incomplete_write_is_not_ok_even_when_the_read_agrees():
    receipt, _ = run(read_result(PAYLOAD), written=write_result(complete=False))
    assert receipt.read_back_verified is True
    assert receipt.ok is False
    assert receipt.written_to_graph is False
    assert receipt.graph_case_id == ""


def test_a_failed_read_is_a_failed_verification():
    receipt, _ = run(None, read_raises=RuntimeError("timeout"))
    assert receipt.read_back_verified is False
    assert receipt.ok is False
    assert "failed" in receipt.read_back_mismatches[0]


def test_a_case_that_is_not_found_is_not_verified():
    receipt, _ = run(set_block(read_result(PAYLOAD), "found", False))
    assert receipt.ok is False
    assert "not found" in receipt.read_back_mismatches[0]


def test_describe_names_the_read_back_disagreement():
    tampered = copy.deepcopy(read_result(PAYLOAD))
    tampered[1]["investigation_case"][0]["attributes"]["stored.summary"] = "other"
    receipt, _ = run(tampered)
    assert "NOT VERIFIED" in receipt.describe()
    assert "summary" in receipt.describe()


# --- each kind of disagreement is caught -----------------------------------


@pytest.mark.parametrize(
    ("attribute", "stored_value"),
    [
        ("verdict", "legitimate"),
        ("fraud_probability", 0.5),
        ("exposure_usd", 300.15),
        ("sar_filed", True),
        ("memory_epoch", "hhgoa_2026_benchmark_v1"),
        ("anchor_time", "2016-11-11 23:46:25"),
        ("answer_json", '{"truncated"'),
    ],
)
def test_an_attribute_that_differs_is_a_mismatch(attribute, stored_value):
    tampered = copy.deepcopy(read_result(PAYLOAD))
    tampered[1]["investigation_case"][0]["attributes"][f"stored.{attribute}"] = stored_value
    mismatches = check(PAYLOAD, tampered)
    assert any(attribute in item for item in mismatches), mismatches


def test_datetimes_compare_by_value_not_by_spelling():
    tampered = copy.deepcopy(read_result(PAYLOAD))
    tampered[1]["investigation_case"][0]["attributes"]["stored.opened_at"] = "2016-11-12T00:46:24"
    assert check(PAYLOAD, tampered) == []


def test_a_requested_edge_that_was_not_stored_is_a_mismatch():
    short = dict(PAYLOAD, affected_txn_ids=["T1"])
    mismatches = check(PAYLOAD, read_result(short))
    assert any("requested but not stored ['T2']" in item for item in mismatches)
    assert any("affected_txn_edge_count" in item for item in mismatches)


def test_a_stale_edge_left_by_an_earlier_write_is_a_mismatch():
    """Edges are additive, so a reduced rewrite leaves the old ones behind."""
    reduced = dict(PAYLOAD, connected_card_ids=[])
    mismatches = check(reduced, read_result(PAYLOAD))
    assert any("stored but not requested ['C2-K1']" in item for item in mismatches)


def test_a_count_that_disagrees_with_the_rows_is_a_mismatch():
    tampered = set_block(read_result(PAYLOAD), "device_edge_count", 2)
    mismatches = check(PAYLOAD, tampered)
    assert any("device_edge_count" in item for item in mismatches)


@pytest.mark.parametrize(
    "relationship",
    ["connected_card_ids", "device_profile_ids", "policy_chunk_ids", "similar_case_ids"],
)
def test_every_relationship_kind_is_compared(relationship):
    missing = dict(PAYLOAD, **{relationship: []})
    mismatches = check(PAYLOAD, read_result(missing))
    assert any(relationship in item for item in mismatches), mismatches


def test_the_on_card_relationship_is_compared():
    tampered = set_block(read_result(PAYLOAD), "on_card", [vertex({"on_card.card_id": "C9-K9"})])
    mismatches = check(PAYLOAD, tampered)
    assert any("on_card" in item for item in mismatches)


def test_a_lost_similarity_is_a_mismatch():
    lost = read_result(PAYLOAD, similarity={"CC-1": 0.82, "CC-2": 0.0})
    mismatches = check(PAYLOAD, lost)
    assert any("similarity of CC-2" in item for item in mismatches)


def test_a_lost_reason_is_a_mismatch():
    lost = read_result(PAYLOAD, reasons={"CC-1": "same_new_device", "CC-2": ""})
    mismatches = check(PAYLOAD, lost)
    assert any("reasons of CC-2" in item for item in mismatches)


# --- provenance is mandatory -----------------------------------------------


@pytest.mark.parametrize(
    ("similarity", "reasons", "complaint"),
    [
        ({"CC-1": 0.82}, REASONS, "CC-2 is cited with no similarity"),
        ({"CC-1": 0.82, "CC-2": 0.0}, REASONS, "not a finite value above 0"),
        ({"CC-1": 0.82, "CC-2": float("nan")}, REASONS, "not a finite value above 0"),
        ({"CC-1": 0.82, "CC-2": True}, REASONS, "not a finite value above 0"),
        (SIMILARITY, {"CC-1": "same_new_device"}, "CC-2 is cited with no retrieval reason"),
        (SIMILARITY, {"CC-1": "same_new_device", "CC-2": ""}, "no retrieval reason"),
        (dict(SIMILARITY, **{"CC-9": 0.3}), REASONS, "CC-9, which is not cited"),
    ],
)
def test_missing_or_placeholder_provenance_is_refused_before_any_write(
    similarity, reasons, complaint
):
    connection = FakeConnection(write_result(), read_result(PAYLOAD))
    receipt = write_case(connection, PAYLOAD, similarity=similarity, reasons=reasons)
    assert connection.calls == [], "nothing may reach the graph"
    assert connection.upserts == []
    assert receipt.write_attempted is False
    assert receipt.ok is False
    assert receipt.written_to_graph is False
    assert any(complaint in item for item in receipt.errors), receipt.errors
    assert "REFUSED" in receipt.describe()


def test_a_case_with_no_citations_needs_no_provenance():
    body = dict(PAYLOAD, similar_case_ids=[])
    connection = FakeConnection(write_result(), read_result(body))
    receipt = write_case(connection, body)
    assert receipt.ok is True


def test_every_cited_case_is_attributed_with_its_own_values():
    receipt, connection = run(read_result(PAYLOAD))
    attributed = {args[4]: args[5] for args in connection.upserts}
    assert attributed == {
        "CC-1": {"similarity": 0.82, "reasons": "same_new_device"},
        "CC-2": {"similarity": 0.41, "reasons": "opposite_outcome"},
    }
    assert receipt.similarity_edges_attributed == 2


def test_the_read_back_rejects_a_stored_placeholder_even_if_it_was_sent():
    """Belt and braces: the stored edge is judged on its own, not only against the payload."""
    placeholder = {"CC-1": 0.0, "CC-2": 0.41}
    empty = {"CC-1": "", "CC-2": "opposite_outcome"}
    stored = read_result(PAYLOAD, similarity=placeholder, reasons=empty)
    mismatches = verify_read_back(PAYLOAD, stored, similarity=placeholder, reasons=empty)
    assert any("CC-1 is stored with placeholder similarity" in item for item in mismatches)
    assert any("CC-1 is stored with no retrieval reason" in item for item in mismatches)
