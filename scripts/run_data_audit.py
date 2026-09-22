"""Run the Gate 0 data audit and write runs/data_audit.json.

Read-only. Every figure in the report is computed from the supplied files.
Exits non-zero if a benchmark identifier fails to resolve, because the graph
schema must not be finalised while an identifier is unproven.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.audit_inputs import (  # noqa: E402
    CLOSED_CASE_POST_CLOSURE_FIELDS,
    IDENTITY_DEVICE_COLUMNS,
    TXN_CORE_COLUMNS,
    build_identity_frame,
    build_transaction_frame,
    cards_table,
    duplicate_count,
    file_facts,
    null_percentages,
    numeric_summary,
    shared_entity_profile,
    value_counts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "raw"
REPORT_PATH = PROJECT_ROOT / "runs" / "data_audit.json"

#: Columns a transaction carries when it is authorised. Everything the bank
#: learns later lives in the closed-case file, not here.
TRANSACTION_TIME_FIELDS = sorted(set(TXN_CORE_COLUMNS) | set(IDENTITY_DEVICE_COLUMNS))


def header_of(path: Path) -> list[str]:
    return pl.read_csv(path, n_rows=0, infer_schema_length=0).columns


def audit_case_pack(pack: pl.DataFrame, transactions: pl.DataFrame, cards: pl.DataFrame) -> dict:
    """Resolve every benchmark trigger against the transaction data."""
    resolved = pack.join(
        transactions.select(
            [
                pl.col("TransactionID").alias("flagged_txn_id"),
                pl.col("card_id").alias("derived_card_id"),
                pl.col("customer_id").alias("derived_customer_id"),
                pl.col("ts").alias("flagged_ts"),
                pl.col("TransactionAmt").alias("flagged_amount"),
                pl.col("channel").alias("flagged_channel"),
                pl.col("ProductCD").alias("flagged_product_cd"),
            ]
        ),
        on="flagged_txn_id",
        how="left",
    )
    known_cards = set(cards["card_id"].to_list())
    known_customers = set(transactions["customer_id"].unique().to_list())

    rows = []
    for row in resolved.to_dicts():
        rows.append(
            {
                "case_id": row["case_id"],
                "trigger_type": row["trigger_type"],
                "flagged_txn_id": row["flagged_txn_id"],
                "flagged_txn_found": row["derived_card_id"] is not None,
                "card_id": row["card_id"],
                "card_id_matches_derived": row["card_id"] == row["derived_card_id"],
                "card_id_exists": row["card_id"] in known_cards,
                "customer_id": row["customer_id"],
                "customer_id_matches_transaction": row["customer_id"] == row["derived_customer_id"],
                "customer_id_exists": row["customer_id"] in known_customers,
                "anchor_time": row["flagged_ts"],
                "flagged_amount": row["flagged_amount"],
                "flagged_channel": row["flagged_channel"],
                "flagged_product_cd": row["flagged_product_cd"],
                "risk_score": row["risk_score"],
            }
        )

    return {
        "cases": rows,
        "case_count": len(rows),
        "all_flagged_transactions_found": all(r["flagged_txn_found"] for r in rows),
        "all_card_ids_resolve": all(r["card_id_matches_derived"] for r in rows),
        "all_customer_ids_resolve": all(r["customer_id_matches_transaction"] for r in rows),
        "trigger_type_counts": value_counts(pack, "trigger_type"),
        "anchor_time_range": {
            "min": min(r["anchor_time"] for r in rows),
            "max": max(r["anchor_time"] for r in rows),
        },
    }


def audit_closed_cases(closed: pl.DataFrame, transactions: pl.DataFrame) -> dict:
    exploded = (
        closed.select(["case_id", "card_id", "customer_id", "txn_ids", "closed_at"])
        .with_columns(pl.col("txn_ids").str.split("|").alias("txn"))
        # empty_as_null pins the behaviour Polars 2.0 will change. True keeps a
        # case whose txn_ids list is empty as a visible null row instead of
        # silently dropping it. No closed case has an empty list today (the
        # shortest is one transaction), so both settings yield the same
        # 14,955 links; this makes the choice explicit rather than implicit.
        .explode("txn", empty_as_null=True)
        .rename({"txn": "TransactionID"})
    )
    joined = exploded.join(
        transactions.select(
            [
                "TransactionID",
                pl.col("card_id").alias("derived_card_id"),
                pl.col("ts").alias("txn_ts"),
            ]
        ),
        on="TransactionID",
        how="left",
    )
    missing = joined.filter(pl.col("derived_card_id").is_null())
    # A closed case must not list a transaction that happened after it closed.
    after_closure = joined.filter(
        pl.col("txn_ts").is_not_null() & (pl.col("txn_ts") > pl.col("closed_at"))
    )
    return {
        "rows": closed.height,
        "duplicate_case_ids": duplicate_count(closed, "case_id"),
        "transaction_links": joined.height,
        "transaction_links_not_found": missing.height,
        "card_id_mismatches": joined.filter(pl.col("card_id") != pl.col("derived_card_id")).height,
        "transactions_dated_after_case_closure": after_closure.height,
        "outcome_counts": value_counts(closed, "outcome"),
        "pattern_counts": value_counts(closed, "pattern"),
        "report_filed_counts": value_counts(closed, "report_filed"),
        "opened_at_range": {
            "min": closed["opened_at"].min(),
            "max": closed["opened_at"].max(),
        },
        "closed_at_range": {
            "min": closed["closed_at"].min(),
            "max": closed["closed_at"].max(),
        },
        "exposure_usd": numeric_summary(closed, "exposure_usd"),
        "actions_taken_vocabulary": sorted(
            {
                action
                for value in closed["actions_taken"].drop_nulls().to_list()
                for action in value.split("|")
                if action
            }
        ),
    }


def audit_temporal(transactions: pl.DataFrame, closed: pl.DataFrame, pack: pl.DataFrame) -> dict:
    """Establish what ts is and whether the benchmark sits after the history."""
    dt = transactions["TransactionDT"].cast(pl.Int64, strict=False)
    ts = transactions["ts"].str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False)
    # ts is a linear function of TransactionDT if it is derived event time.
    offsets = (ts.dt.epoch("s") - dt).unique()
    single_offset = offsets.len() == 1
    return {
        "ts_min": transactions["ts"].min(),
        "ts_max": transactions["ts"].max(),
        "transaction_dt_min": int(dt.min()),
        "transaction_dt_max": int(dt.max()),
        "ts_is_linear_in_transaction_dt": single_offset,
        "ts_minus_transaction_dt_distinct_offsets": int(offsets.len()),
        "ts_epoch_offset_seconds": int(offsets[0]) if single_offset else None,
        "ts_interpretation": (
            "derived event time: ts = dataset epoch + TransactionDT seconds, one "
            "constant offset, no timezone field supplied; treat as naive local time"
            if single_offset
            else "ts is not a constant offset of TransactionDT; treat with care"
        ),
        "history_window": {
            "closed_case_opened_min": closed["opened_at"].min(),
            "closed_case_closed_max": closed["closed_at"].max(),
        },
        "benchmark_window": {
            "opened_min": pack["opened_at"].min(),
            "opened_max": pack["opened_at"].max(),
        },
        "benchmark_opens_after_all_closed_cases": pack["opened_at"].min()
        > closed["closed_at"].max(),
    }


def audit_shared_entities(transactions: pl.DataFrame, identity: pl.DataFrame) -> dict:
    with_device = transactions.select(
        ["TransactionID", "card_id", "addr1", "P_emaildomain", "R_emaildomain"]
    ).join(
        identity.select(["TransactionID", "device_signature", "signature_strength"]),
        on="TransactionID",
        how="left",
    )
    strong_device = with_device.filter(pl.col("signature_strength") >= 3)
    return {
        "billing_region_addr1": shared_entity_profile(with_device, "addr1", "card_id"),
        "purchaser_email_domain": shared_entity_profile(with_device, "P_emaildomain", "card_id"),
        "recipient_email_domain": shared_entity_profile(with_device, "R_emaildomain", "card_id"),
        "device_signature_all": shared_entity_profile(with_device, "device_signature", "card_id"),
        "device_signature_strength_at_least_3": shared_entity_profile(
            strong_device, "device_signature", "card_id"
        ),
        "signature_strength_distribution": value_counts(
            identity.with_columns(pl.col("signature_strength").cast(pl.Utf8)),
            "signature_strength",
        ),
        "note": (
            "Region and common email domains are supernodes: a single value links "
            "thousands of cards. A shared-origin claim therefore requires time-local "
            "coordination plus rarity or fraud enrichment, never raw degree."
        ),
    }


def audit_leakage(closed_columns: list[str]) -> dict:
    return {
        "available_at_transaction_time": TRANSACTION_TIME_FIELDS,
        "created_at_or_after_case_closure": [
            column for column in CLOSED_CASE_POST_CLOSURE_FIELDS if column in closed_columns
        ],
        "available_at_case_open": ["case_id", "customer_id", "card_id", "opened_at"],
        "rule": (
            "A closed case may be used as memory for a new case only when its "
            "closed_at is at or before the new case's anchor time. Its outcome, "
            "pattern, exposure, actions, report flag and analyst notes are all "
            "post-closure fields."
        ),
        "risk_score_note": (
            "risk_score is produced by the bank's model at transaction time and is "
            "admissible as an input feature, but it is not an outcome label."
        ),
    }


def sample_rows(frame: pl.DataFrame, columns: list[str], n: int = 5) -> list[dict]:
    keep = [column for column in columns if column in frame.columns]
    return frame.select(keep).head(n).to_dicts()


def main() -> int:
    if not RAW.exists():
        print(f"Raw data directory missing: {RAW}")
        return 1

    paths = {
        "transactions": RAW / "transactions.csv",
        "identity": RAW / "identity.csv",
        "closed_cases": RAW / "closed_cases_history.csv",
        "case_pack": RAW / "case_pack.csv",
        "dataset_readme": RAW / "README.md",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        print(f"Missing supplied files: {', '.join(missing)}")
        return 1

    print("loading transactions ...")
    transactions = build_transaction_frame(RAW)
    print("loading identity ...")
    identity = build_identity_frame(RAW)
    closed = pl.read_csv(paths["closed_cases"], infer_schema_length=0)
    pack = pl.read_csv(paths["case_pack"], infer_schema_length=0)
    cards = cards_table(transactions)

    headers = {name: header_of(path) for name, path in paths.items() if path.suffix == ".csv"}

    facts = {
        "transactions": file_facts(
            paths["transactions"], transactions.height, len(headers["transactions"])
        ),
        "identity": file_facts(paths["identity"], identity.height, len(headers["identity"])),
        "closed_cases": file_facts(
            paths["closed_cases"], closed.height, len(headers["closed_cases"])
        ),
        "case_pack": file_facts(paths["case_pack"], pack.height, len(headers["case_pack"])),
    }
    readme_path = paths["dataset_readme"]

    identity_join = identity.join(
        transactions.select(["TransactionID", "channel"]), on="TransactionID", how="left"
    )

    print("building report ...")
    report = {
        "audit_version": 1,
        "source_directory": str(RAW),
        "files": {name: asdict(fact) for name, fact in facts.items()}
        | {
            "dataset_readme": {
                "name": readme_path.name,
                "size_bytes": readme_path.stat().st_size,
                "sha256": file_facts(readme_path, 0, 0).sha256,
            }
        },
        "headers": headers,
        "transactions": {
            "rows": transactions.height,
            "total_columns_in_file": len(headers["transactions"]),
            "columns_loaded_for_investigation": TXN_CORE_COLUMNS,
            "duplicate_transaction_ids": duplicate_count(transactions, "TransactionID"),
            "distinct_customers": transactions["customer_id"].n_unique(),
            "distinct_derived_cards": cards.height,
            "null_percentages": null_percentages(transactions, TXN_CORE_COLUMNS),
            "channel_counts": value_counts(transactions, "channel"),
            "product_cd_counts": value_counts(transactions, "ProductCD"),
            "card4_network_counts": value_counts(transactions, "card4"),
            "card6_type_counts": value_counts(transactions, "card6"),
            "transaction_amount": numeric_summary(transactions, "TransactionAmt"),
            "risk_score": numeric_summary(transactions, "risk_score"),
            "sample_rows": sample_rows(
                transactions,
                [
                    "TransactionID",
                    "ts",
                    "TransactionAmt",
                    "ProductCD",
                    "channel",
                    "risk_score",
                    "customer_id",
                    "card_id",
                    "addr1",
                    "P_emaildomain",
                ],
            ),
        },
        "identity": {
            "rows": identity.height,
            "total_columns_in_file": len(headers["identity"]),
            "duplicate_transaction_ids": duplicate_count(identity, "TransactionID"),
            "joins_to_a_transaction": identity_join.filter(pl.col("channel").is_not_null()).height,
            "online_transactions": transactions.filter(pl.col("channel") == "online").height,
            "identity_rows_on_in_person_transactions": identity_join.filter(
                pl.col("channel") == "in_person"
            ).height,
            "null_percentages": null_percentages(identity, IDENTITY_DEVICE_COLUMNS),
            "device_type_counts": value_counts(identity, "DeviceType"),
            "id_15_new_found_counts": value_counts(identity, "id_15"),
            "id_23_proxy_counts": value_counts(identity, "id_23"),
            "sample_rows": sample_rows(
                identity,
                [
                    "TransactionID",
                    "DeviceType",
                    "DeviceInfo",
                    "id_15",
                    "id_30",
                    "id_31",
                    "id_33",
                    "device_signature",
                    "signature_strength",
                ],
            ),
        },
        "card_identifier_mapping": {
            "card_id_present_in_transactions_csv": "card_id" in headers["transactions"],
            "derivation": (
                "card_id = customer_id + '-K' + index over distinct card6 values per "
                "customer, ordered ascending with the missing value first"
            ),
            "derived_cards": cards.height,
            "transactions_without_card_id": transactions.filter(pl.col("card_id").is_null()).height,
            "proof_report": "runs/card_mapping_proof.json",
        },
        "case_pack": audit_case_pack(pack, transactions, cards),
        "closed_cases": audit_closed_cases(closed, transactions),
        "temporal": audit_temporal(transactions, closed, pack),
        "shared_entities": audit_shared_entities(transactions, identity),
        "leakage_audit": audit_leakage(headers["closed_cases"]),
    }

    blocking = {
        "all_flagged_transactions_found": report["case_pack"]["all_flagged_transactions_found"],
        "all_benchmark_card_ids_resolve": report["case_pack"]["all_card_ids_resolve"],
        "all_benchmark_customer_ids_resolve": report["case_pack"]["all_customer_ids_resolve"],
        "all_closed_case_transactions_found": report["closed_cases"]["transaction_links_not_found"]
        == 0,
        "no_duplicate_transaction_ids": report["transactions"]["duplicate_transaction_ids"] == 0,
        "benchmark_after_history": report["temporal"]["benchmark_opens_after_all_closed_cases"],
    }
    report["gate_0_checks"] = blocking
    report["gate_0_passed"] = all(blocking.values())

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"\nwrote {REPORT_PATH}")
    for name, value in blocking.items():
        print(f"  {'PASS' if value else 'FAIL'}  {name}")
    if not report["gate_0_passed"]:
        print("\nGate 0 data audit FAILED. Do not finalise the graph schema.")
        return 1
    print("\nGate 0 data audit PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
