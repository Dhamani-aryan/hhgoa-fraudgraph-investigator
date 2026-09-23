"""Tests for the shared query-result normalizer.

Both graph adapters return results through this module, so a change here
changes what every piece of investigation code sees.
"""

from __future__ import annotations

from graph.result_normalizers import (
    first,
    normalize_result,
    normalize_row,
    rows,
    scalar,
    strip_prefix,
)

VERTEX_BLOCK = [
    {
        "window_transactions": [
            {
                "v_id": "3450436",
                "v_type": "Transaction",
                "attributes": {
                    "window.txn_id": "3450436",
                    "window.ts": "2016-11-11 22:36:50",
                    "window.amount": 100.09,
                },
            },
            {
                "v_id": "3450629",
                "v_type": "Transaction",
                "attributes": {
                    "window.txn_id": "3450629",
                    "window.ts": "2016-11-11 23:46:24",
                    "window.amount": 100.09,
                },
            },
        ]
    },
    {"returned_rows": 2, "row_cap": 300},
]


def test_strip_prefix_removes_the_accumulator_alias():
    assert strip_prefix("window.txn_id") == "txn_id"
    assert strip_prefix("txn_id") == "txn_id"
    # Only the first dot is a prefix separator.
    assert strip_prefix("a.b.c") == "b.c"


def test_normalize_row_flattens_a_vertex():
    row = normalize_row(VERTEX_BLOCK[0]["window_transactions"][0])
    assert row["txn_id"] == "3450436"
    assert row["amount"] == 100.09
    assert row["v_id"] == "3450436"


def test_normalize_row_passes_through_a_plain_value():
    assert normalize_row(7) == 7


def test_rows_returns_the_named_block():
    found = rows(VERTEX_BLOCK, "window_transactions")
    assert [item["txn_id"] for item in found] == ["3450436", "3450629"]


def test_rows_falls_back_to_the_first_list_block():
    assert len(rows(VERTEX_BLOCK)) == 2


def test_rows_of_a_missing_block_is_empty_not_an_error():
    assert rows(VERTEX_BLOCK, "not_a_block") == []


def test_scalar_reads_a_printed_number():
    assert scalar(VERTEX_BLOCK, "returned_rows") == 2
    assert scalar(VERTEX_BLOCK, "row_cap") == 300
    assert scalar(VERTEX_BLOCK, "absent", default=-1) == -1


def test_first_returns_one_row_or_none():
    assert first(VERTEX_BLOCK, "window_transactions")["txn_id"] == "3450436"
    assert first(VERTEX_BLOCK, "not_a_block") is None


def test_empty_result_normalizes_to_an_empty_dict():
    assert normalize_result([]) == {}
    assert normalize_result(None) == {}
    assert rows([]) == []


def test_blocks_merge_into_one_dict():
    merged = normalize_result(VERTEX_BLOCK)
    assert set(merged) == {"window_transactions", "returned_rows", "row_cap"}
