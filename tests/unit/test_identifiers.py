"""Unit tests for the derived card identifier.

These run on a small in-memory fixture so they do not need the supplied
675 MB transaction file. ``scripts/prove_card_mapping.py`` proves the same
rule against every labelled link in the real data.
"""

from __future__ import annotations

import polars as pl

from ingestion.identifiers import add_card_type_key, attach_card_ids, build_card_table

SCHEMA = {
    "TransactionID": pl.Utf8,
    "customer_id": pl.Utf8,
    "card6": pl.Utf8,
    "ts": pl.Utf8,
}


def _row(txn: str, customer: str, card_type: str | None, day: int) -> dict:
    return {
        "TransactionID": txn,
        "customer_id": customer,
        "card6": card_type,
        "ts": f"2016-07-{day:02d} 00:00:00",
    }


def _frame(*rows: dict) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema=SCHEMA)


def test_single_card_customer_is_k1():
    frame = _frame(_row("1", "C00001", "debit", 2), _row("2", "C00001", "debit", 3))
    cards = build_card_table(frame)
    assert cards.height == 1
    assert cards["card_id"].to_list() == ["C00001-K1"]
    assert cards["txn_count"].to_list() == [2]


def test_card_type_orders_cards_ascending():
    """credit sorts before debit, so the credit card is K1 regardless of first use."""
    frame = _frame(_row("1", "C00002", "debit", 1), _row("2", "C00002", "credit", 30))
    cards = build_card_table(frame).sort("card_id")
    assert cards.select(["card_id", "card_type_key"]).rows() == [
        ("C00002-K1", "credit"),
        ("C00002-K2", "debit"),
    ]


def test_missing_card_type_sorts_first():
    """A missing card6 is its own card and takes the lowest index."""
    frame = _frame(
        _row("1", "C00003", "credit", 1),
        _row("2", "C00003", "debit", 2),
        _row("3", "C00003", None, 3),
    )
    cards = build_card_table(frame).sort("card_id")
    assert cards["card_id"].to_list() == ["C00003-K1", "C00003-K2", "C00003-K3"]
    assert cards["card_type_key"].to_list() == ["", "credit", "debit"]


def test_every_transaction_resolves_to_exactly_one_card():
    frame = _frame(
        _row("1", "C00004", "credit", 1),
        _row("2", "C00004", None, 2),
        _row("3", "C00005", "debit", 2),
    )
    resolved = attach_card_ids(frame)
    assert resolved.height == frame.height
    assert resolved.filter(pl.col("card_id").is_null()).height == 0
    assert dict(resolved.select(["TransactionID", "card_id"]).rows()) == {
        "1": "C00004-K2",
        "2": "C00004-K1",
        "3": "C00005-K1",
    }


def test_card_type_key_never_null():
    keyed = add_card_type_key(_frame(_row("1", "C00006", None, 1)))
    assert keyed["card_type_key"].null_count() == 0
    assert keyed["card_type_key"].to_list() == [""]
