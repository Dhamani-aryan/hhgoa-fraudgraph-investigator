"""Prove the derived card_id against every labelled card link in the supplied data.

Labelled links come from two independent places in the dataset:
  * ``closed_cases_history.csv`` -- each closed case names a ``card_id`` and the
    pipe-separated ``txn_ids`` that belong to it.
  * ``case_pack.csv`` -- each benchmark case names a ``card_id`` and its
    ``flagged_txn_id``.

The script exits non-zero if a single link fails to resolve, so the Gate 0
hard stop on card identity cannot be passed by assumption.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.identifiers import attach_card_ids, build_card_table  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "raw"
REPORT = PROJECT_ROOT / "runs" / "card_mapping_proof.json"

TXN_COLUMNS = ["TransactionID", "customer_id", "card1", "card6", "ts"]


def load_labelled_links() -> pl.DataFrame:
    closed = pl.read_csv(RAW / "closed_cases_history.csv", infer_schema_length=0)
    closed_links = (
        closed.select(["case_id", "card_id", "txn_ids"])
        .with_columns(pl.col("txn_ids").str.split("|").alias("txn"))
        .explode("txn")
        .select(
            pl.col("case_id"),
            pl.col("card_id"),
            pl.col("txn").alias("TransactionID"),
            pl.lit("closed_case").alias("origin"),
        )
    )
    pack = pl.read_csv(RAW / "case_pack.csv", infer_schema_length=0)
    pack_links = pack.select(
        pl.col("case_id"),
        pl.col("card_id"),
        pl.col("flagged_txn_id").alias("TransactionID"),
        pl.lit("case_pack").alias("origin"),
    )
    return pl.concat([closed_links, pack_links]).unique()


def main() -> int:
    transactions = (
        pl.scan_csv(RAW / "transactions.csv", infer_schema_length=0).select(TXN_COLUMNS).collect()
    )

    customer_card1 = transactions.select(["customer_id", "card1"]).unique()
    customers_with_many_card1 = (
        customer_card1.group_by("customer_id")
        .agg(pl.len().alias("n"))
        .filter(pl.col("n") > 1)
        .height
    )

    cards = build_card_table(transactions)
    resolved = attach_card_ids(transactions, cards)
    unresolved_rows = resolved.filter(pl.col("card_id").is_null()).height

    links = load_labelled_links()
    joined = links.join(
        resolved.select(["TransactionID", pl.col("card_id").alias("derived_card_id")]),
        on="TransactionID",
        how="left",
    )
    missing_txn = joined.filter(pl.col("derived_card_id").is_null()).height
    exact = joined.filter(pl.col("card_id") == pl.col("derived_card_id")).height
    mismatched = joined.height - exact

    per_origin = {
        row["origin"]: row["matched"]
        for row in joined.group_by("origin")
        .agg((pl.col("card_id") == pl.col("derived_card_id")).sum().alias("matched"))
        .to_dicts()
    }

    cards_per_customer = {
        str(row["n_cards"]): row["customers"]
        for row in cards.group_by("customer_id")
        .agg(pl.len().alias("n_cards"))
        .group_by("n_cards")
        .agg(pl.len().alias("customers"))
        .sort("n_cards")
        .to_dicts()
    }

    report = {
        "rule": (
            "card_id = customer_id + '-K' + index, where a card is a distinct card6 "
            "value within a customer, ordered ascending with the missing value first, "
            "numbered from 1"
        ),
        "customer_id_to_card1": {
            "distinct_customers": transactions["customer_id"].n_unique(),
            "distinct_card1": transactions["card1"].n_unique(),
            "customers_with_more_than_one_card1": customers_with_many_card1,
            "one_to_one": customers_with_many_card1 == 0,
        },
        "derived_cards": cards.height,
        "cards_per_customer": cards_per_customer,
        "transactions_without_derived_card_id": unresolved_rows,
        "labelled_links": {
            "total": joined.height,
            "transaction_not_found_in_transactions_csv": missing_txn,
            "exact_match": exact,
            "mismatch": mismatched,
            "matched_by_origin": per_origin,
        },
        "passed": mismatched == 0 and missing_txn == 0 and unresolved_rows == 0,
    }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if not report["passed"]:
        print("\nFAILED: the card_id derivation does not reproduce the supplied labels.")
        return 1
    print("\nPASSED: every labelled card link resolves to the derived card_id.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
