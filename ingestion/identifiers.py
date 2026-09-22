"""Deterministic identifier derivation for the supplied HHGOA dataset.

The supplied ``transactions.csv`` carries ``customer_id`` but no ``card_id``.
The benchmark case pack and the closed-case history both reference cards as
``<customer_id>-K<n>``. This module derives that identifier from the raw
transaction columns and is the single place the rule is expressed.

The rule, proven against every labelled link in the supplied data
(see ``scripts/prove_card_mapping.py``):

1. ``customer_id`` is one-to-one with ``card1``; ``card1`` is the issuer field
   the dataset README says ``customer_id`` was derived from.
2. Within a customer, a distinct card is a distinct ``card6`` value
   (the card type: ``credit``, ``debit``, ``charge card``, ``debit or credit``,
   or missing). ``card6`` is the only column that separates the labelled cards
   of every multi-card customer in the supplied data.
3. A customer's cards are ordered by ``card6`` ascending with the missing value
   sorting first, and numbered from 1.
4. ``card_id = f"{customer_id}-K{index}"``.

Proof result: 14,975 of 14,975 labelled card links (14,955 closed-case
transaction links plus the 20 benchmark flagged transactions) resolve to the
derived identifier with no mismatches and no unresolved transactions.
"""

from __future__ import annotations

import polars as pl

#: Sentinel used for a missing ``card6``. The empty string sorts before every
#: real card type, which is the ordering the supplied labels follow.
MISSING_CARD_TYPE = ""

CARD_KEY_COLUMN = "card6"
CARD_TYPE_COLUMN = "card_type_key"
CARD_ID_COLUMN = "card_id"


def add_card_type_key(frame: pl.DataFrame | pl.LazyFrame) -> pl.DataFrame | pl.LazyFrame:
    """Add the normalized card-type key used to separate a customer's cards."""
    return frame.with_columns(
        pl.col(CARD_KEY_COLUMN).fill_null(MISSING_CARD_TYPE).alias(CARD_TYPE_COLUMN)
    )


def build_card_table(transactions: pl.DataFrame) -> pl.DataFrame:
    """Return one row per derived card.

    Columns: ``customer_id``, ``card_type_key``, ``card_index``, ``card_id``,
    ``txn_count``, ``first_seen``, ``last_seen``.

    ``transactions`` must contain ``customer_id``, ``card6`` and ``ts``.
    """
    framed = add_card_type_key(transactions)
    grouped = (
        framed.group_by(["customer_id", CARD_TYPE_COLUMN])
        .agg(
            pl.len().alias("txn_count"),
            pl.col("ts").min().alias("first_seen"),
            pl.col("ts").max().alias("last_seen"),
        )
        .sort(["customer_id", CARD_TYPE_COLUMN])
    )
    return grouped.with_columns(
        pl.col("customer_id").cum_count().over("customer_id").alias("card_index")
    ).with_columns(
        (pl.col("customer_id") + "-K" + pl.col("card_index").cast(pl.Utf8)).alias(CARD_ID_COLUMN)
    )


def attach_card_ids(transactions: pl.DataFrame, cards: pl.DataFrame | None = None) -> pl.DataFrame:
    """Attach the derived ``card_id`` to every transaction row.

    The join key is never null, so every transaction resolves to exactly one
    card. Callers should assert that no ``card_id`` is null.
    """
    cards = build_card_table(transactions) if cards is None else cards
    framed = add_card_type_key(transactions)
    return framed.join(
        cards.select(["customer_id", CARD_TYPE_COLUMN, CARD_ID_COLUMN]),
        on=["customer_id", CARD_TYPE_COLUMN],
        how="left",
    )
