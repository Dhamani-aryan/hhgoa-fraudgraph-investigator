"""The single write path and its read-back receipt.

The challenge requires each case to be written to the graph, and the answer
contract only permits written_to_graph=true after a successful read-back. These
tests exercise that round trip against the live graph and clean up after
themselves, so the benchmark memory epoch is never polluted by a fixture.
"""

from __future__ import annotations

import pytest

from graph.client import TigerGraphConfigError, connect, load_config
from graph.result_normalizers import rows, scalar

WRITE = "write_investigation_case_v1"
READ = "read_investigation_case_v1"

#: Deliberately outside the benchmark memory epoch.
TEST_CASE_ID = "TEST-CASE-WRITE-ROUNDTRIP"
TEST_EPOCH = "test_epoch_not_the_benchmark"


def payload(**overrides) -> dict:
    base = {
        "case_id": TEST_CASE_ID,
        "memory_epoch": TEST_EPOCH,
        "status": "closed_fraud",
        "verdict": "fraud",
        "fraud_probability": 0.86,
        "pattern": "card_testing",
        "pattern_description": "",
        "exposure_usd": 300.14,
        "first_suspicious_txn_id": "3450436",
        "summary": "Round trip fixture.",
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
        "memory_text": "round trip fixture memory",
        "affected_txn_ids": ["3450436", "3450503", "3450629"],
        "connected_card_ids": ["C00877-K1"],
        "device_profile_ids": ["8ea57628c8afc1b3"],
        "similar_case_ids": ["CC-0137"],
        "policy_chunk_ids": ["policy:R2"],
        "on_card_id": "C04570-K1",
    }
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def connection():
    try:
        return connect(load_config())
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")


@pytest.fixture
def written(connection):
    """Write the fixture case, yield the connection, then remove it."""
    connection.runInstalledQuery(WRITE, params=payload(), usePost=True)
    yield connection
    connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


def read_back(connection):
    return connection.runInstalledQuery(READ, params={"case_id": TEST_CASE_ID})


# --- the round trip --------------------------------------------------------


def test_the_case_reads_back_with_the_values_it_was_given(written):
    result = read_back(written)
    assert scalar(result, "found") is True

    stored = rows(result, "investigation_case")[0]
    assert stored["case_id"] == TEST_CASE_ID
    assert stored["memory_epoch"] == TEST_EPOCH
    assert stored["verdict"] == "fraud"
    assert stored["fraud_probability"] == pytest.approx(0.86)
    assert stored["exposure_usd"] == pytest.approx(300.14)
    assert stored["policy_version"] == "1.0"


def test_every_evidence_relationship_reads_back(written):
    result = read_back(written)
    assert scalar(result, "affected_txn_edge_count") == 3
    assert scalar(result, "connected_card_edge_count") == 1
    assert scalar(result, "on_card_edge_count") == 1
    assert scalar(result, "device_edge_count") == 1
    assert scalar(result, "similar_case_edge_count") == 1
    assert scalar(result, "policy_chunk_edge_count") == 1


def test_retrieval_provenance_is_findable_in_the_graph(written):
    """Validator rule R09 checks a citation against the graph, not the answer."""
    result = read_back(written)
    assert [item["case_id"] for item in rows(result, "similar_prior_cases")] == ["CC-0137"]
    assert [item["chunk_id"] for item in rows(result, "cited_policy_chunks")] == ["policy:R2"]


def test_an_absent_case_reads_back_as_not_found(connection):
    result = connection.runInstalledQuery(READ, params={"case_id": "NO-SUCH-CASE"})
    assert scalar(result, "found") is False
    assert rows(result, "investigation_case") == []


# --- unmatched identifiers -------------------------------------------------


def test_unmatched_identifiers_are_reported_not_swallowed(connection):
    """An answer citing an id the graph lacks must fail validation, not lose an edge."""
    result = connection.runInstalledQuery(
        WRITE,
        params=payload(
            affected_txn_ids=["3450436", "9999999999"],
            similar_case_ids=["CC-0137", "CC-9999999"],
        ),
        usePost=True,
    )
    try:
        assert "9999999999" in scalar(result, "unmatched_txn_ids")
        assert "CC-9999999" in scalar(result, "unmatched_case_ids")
        assert scalar(result, "affected_txn_edges_written") == 1
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


# --- idempotence -----------------------------------------------------------


def test_rewriting_the_same_case_does_not_duplicate(written):
    """A retried or resumed run must converge, not accumulate."""
    before = read_back(written)
    for _ in range(3):
        written.runInstalledQuery(WRITE, params=payload(), usePost=True)
    after = read_back(written)

    for count in (
        "affected_txn_edge_count",
        "connected_card_edge_count",
        "device_edge_count",
        "similar_case_edge_count",
        "policy_chunk_edge_count",
    ):
        assert scalar(after, count) == scalar(before, count), count


def test_rewriting_updates_the_vertex_in_place(written):
    written.runInstalledQuery(
        WRITE, params=payload(verdict="uncertain", fraud_probability=0.5), usePost=True
    )
    stored = rows(read_back(written), "investigation_case")[0]
    assert stored["verdict"] == "uncertain"
    assert stored["fraud_probability"] == pytest.approx(0.5)


def test_edges_are_additive_on_a_reduced_rewrite(written):
    """The documented limit, pinned so it cannot be forgotten.

    An upsert asserts what it is given and cannot know what was withdrawn, so a
    rewrite with fewer identifiers leaves the earlier edges. A corrected rerun
    that removes evidence must delete the case vertex first.
    """
    written.runInstalledQuery(WRITE, params=payload(affected_txn_ids=["3450436"]), usePost=True)
    assert scalar(read_back(written), "affected_txn_edge_count") == 3


def test_the_benchmark_epoch_is_left_clean(connection):
    """No fixture may survive into the epoch the benchmark retrieves from."""
    connection.delVerticesById("InvestigationCase", TEST_CASE_ID)
    result = connection.runInstalledQuery(READ, params={"case_id": TEST_CASE_ID})
    assert scalar(result, "found") is False


# --- retrieval attributes on INV_SIMILAR_TO --------------------------------


def test_similarity_and_reasons_persist_and_read_back(connection):
    """An edge with no similarity and no reasons cannot say WHY a case was cited."""
    from graph.case_writer import read_case, write_case

    receipt = write_case(
        connection,
        payload(similar_case_ids=["CC-0137", "CC-0003"]),
        similarity={"CC-0137": 0.82, "CC-0003": 0.41},
        reasons={"CC-0137": "same_new_device,similar_velocity", "CC-0003": "opposite_outcome"},
    )
    try:
        assert receipt.ok is True
        assert receipt.similarity_edges_attributed == 2

        stored = {
            item["case_id"]: item
            for item in rows(read_case(connection, TEST_CASE_ID), "similar_prior_cases")
        }
        assert stored["CC-0137"]["similarity"] == pytest.approx(0.82)
        assert stored["CC-0137"]["reasons"] == "same_new_device,similar_velocity"
        assert stored["CC-0003"]["similarity"] == pytest.approx(0.41)
        assert stored["CC-0003"]["reasons"] == "opposite_outcome"
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


def test_attributes_are_only_applied_to_matched_cases(connection):
    from graph.case_writer import write_case

    receipt = write_case(
        connection,
        payload(similar_case_ids=["CC-0137", "CC-9999999"]),
        similarity={"CC-0137": 0.5, "CC-9999999": 0.9},
        reasons={"CC-0137": "r", "CC-9999999": "r"},
    )
    try:
        assert receipt.similarity_edges_attributed == 1
        assert "CC-9999999" in receipt.unmatched["unmatched_case_ids"]
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


# --- partial writes are failures -------------------------------------------


def test_a_complete_write_reports_complete(connection):
    from graph.case_writer import write_case

    receipt = write_case(connection, payload())
    try:
        assert receipt.complete is True
        assert receipt.ok is True
        assert all(not ids for ids in receipt.unmatched.values())
        assert receipt.unmatched_on_card_id == ""
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


@pytest.mark.parametrize(
    ("field_name", "override"),
    [
        ("unmatched_txn_ids", {"affected_txn_ids": ["3450436", "9999999999"]}),
        ("unmatched_card_ids", {"connected_card_ids": ["C99999-K9"]}),
        ("unmatched_case_ids", {"similar_case_ids": ["CC-9999999"]}),
        ("unmatched_device_ids", {"device_profile_ids": ["nosuchdevice"]}),
        ("unmatched_policy_chunk_ids", {"policy_chunk_ids": ["policy:NOPE"]}),
    ],
)
def test_every_identifier_kind_is_reported_when_unmatched(connection, field_name, override):
    """Device, policy and on-card ids were previously dropped in silence."""
    from graph.case_writer import write_case

    receipt = write_case(connection, payload(**override))
    try:
        assert receipt.unmatched[field_name], f"{field_name} was not reported"
        assert receipt.complete is False
        assert receipt.ok is False
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


def test_an_unmatched_on_card_id_is_reported(connection):
    from graph.case_writer import write_case

    receipt = write_case(connection, payload(on_card_id="C99999-K9"))
    try:
        assert receipt.unmatched_on_card_id == "C99999-K9"
        assert receipt.ok is False
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


# --- independent read-back -------------------------------------------------


def test_a_verified_write_reads_back_and_sets_the_answer_fields(connection):
    """written_to_graph and graph_case_id come from the receipt, and only after read-back."""
    from graph.case_writer import write_case

    receipt = write_case(connection, payload())
    try:
        assert receipt.read_back_mismatches == []
        assert receipt.read_back_verified is True
        assert receipt.ok is True
        assert receipt.written_to_graph is True
        assert receipt.graph_case_id == TEST_CASE_ID
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


def test_a_stale_edge_from_an_earlier_write_fails_the_read_back(connection):
    """The write query reports complete; only the read-back sees the old edges.

    Edges are additive, so rewriting with fewer transactions leaves the earlier
    ones. The graph then does not mirror the answer and must not be a receipt
    for it.
    """
    from graph.case_writer import write_case

    write_case(connection, payload())
    try:
        receipt = write_case(connection, payload(affected_txn_ids=["3450436"]))
        assert receipt.complete is True, "the write query alone cannot see this"
        assert receipt.read_back_verified is False
        assert receipt.ok is False
        assert receipt.written_to_graph is False
        assert receipt.graph_case_id == ""
        assert any("stored but not requested" in item for item in receipt.read_back_mismatches)
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


def test_the_read_back_detects_a_value_changed_after_the_write(connection):
    """The comparison reads the graph, not the write query's own report."""
    from graph.case_writer import read_case, verify_read_back, write_case

    receipt = write_case(connection, payload())
    try:
        assert receipt.ok is True
        connection.upsertVertex("InvestigationCase", TEST_CASE_ID, {"verdict": "legitimate"})
        mismatches = verify_read_back(payload(), read_case(connection, TEST_CASE_ID))
        assert any("verdict" in item for item in mismatches), mismatches
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)


def test_a_partial_write_describes_what_was_missing(connection):
    """The caller must be able to act on the receipt, not just see a boolean."""
    from graph.case_writer import write_case

    receipt = write_case(
        connection,
        payload(device_profile_ids=["nosuchdevice"], policy_chunk_ids=["policy:NOPE"]),
    )
    try:
        description = receipt.describe()
        assert "PARTIAL" in description
        assert "nosuchdevice" in description
        assert "policy:NOPE" in description
    finally:
        connection.delVerticesById("InvestigationCase", TEST_CASE_ID)
