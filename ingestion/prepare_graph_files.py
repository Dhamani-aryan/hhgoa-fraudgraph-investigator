"""Turn the four supplied CSVs into normalized vertex and edge files.

Output goes to ``data/prepared/`` (git-ignored, regenerable). Every file is
plain CSV with a header, ready for a TigerGraph loading job.

Two rules shape the output and both come from the Gate 0 audit:

* A ``FROM_DEVICE`` edge is only written when the device signature has at least
  two of its four identifying fields. A weaker signature stays transaction-local
  rather than linking unrelated cards through a coarse field such as the browser
  alone.
* ``EmailDomain`` and ``BillingRegion`` carry ``n_cards`` so a rarity check is a
  single hop. They are supernodes: one domain touches 9,332 cards.

``NEXT`` is ordered by ``(ts, txn_id)`` within a card. The transaction id
tie-break makes the chain identical on every regeneration.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl

from ingestion.audit_inputs import (
    IDENTITY_DEVICE_COLUMNS,
    TXN_CORE_COLUMNS,
    device_signature_expression,
    device_signature_strength,
)
from ingestion.identifiers import attach_card_ids

#: A device signature this weak cannot create a shared-device link.
MIN_SIGNATURE_STRENGTH_FOR_EDGE = 2

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def device_id_of(signature: str) -> str:
    """Deterministic id for a device signature."""
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]


def _device_id_expr() -> pl.Expr:
    return (
        pl.col("device_signature")
        .map_elements(device_id_of, return_dtype=pl.Utf8)
        .alias("device_id")
    )


def load_transactions(raw_dir: Path) -> pl.DataFrame:
    frame = (
        pl.scan_csv(raw_dir / "transactions.csv", infer_schema_length=0)
        .select(TXN_CORE_COLUMNS)
        .collect()
    )
    return attach_card_ids(frame)


def load_identity(raw_dir: Path) -> pl.DataFrame:
    return (
        pl.scan_csv(raw_dir / "identity.csv", infer_schema_length=0)
        .select(IDENTITY_DEVICE_COLUMNS)
        .collect()
        .with_columns(device_signature_expression(), device_signature_strength())
        .with_columns(_device_id_expr())
    )


def build_transaction_vertices(transactions: pl.DataFrame) -> pl.DataFrame:
    return transactions.select(
        pl.col("TransactionID").alias("txn_id"),
        pl.col("ts"),
        pl.col("TransactionAmt").cast(pl.Float64, strict=False).alias("amount"),
        pl.col("ProductCD").fill_null("").alias("product_cd"),
        pl.col("channel").fill_null("").alias("channel"),
        pl.col("risk_score").cast(pl.Float64, strict=False).alias("risk_score"),
        pl.col("addr1").fill_null("").alias("addr1"),
        pl.col("addr2").fill_null("").alias("addr2"),
        pl.col("dist1").cast(pl.Float64, strict=False).fill_null(-1.0).alias("dist1"),
        pl.col("dist2").cast(pl.Float64, strict=False).fill_null(-1.0).alias("dist2"),
        pl.col("P_emaildomain").fill_null("").alias("p_email_domain"),
        pl.col("R_emaildomain").fill_null("").alias("r_email_domain"),
        pl.col("card_id"),
        pl.col("customer_id"),
        # Where the full Vesta feature row can be found again.
        (pl.lit("transactions.csv#") + pl.col("TransactionID")).alias("raw_row_ref"),
    )


def build_card_vertices(transactions: pl.DataFrame, cards: pl.DataFrame) -> pl.DataFrame:
    detail = transactions.group_by("card_id").agg(
        pl.col("card4").drop_nulls().first().alias("card_network"),
        pl.col("card1").drop_nulls().first().alias("issuer_card1"),
        pl.col("card2").drop_nulls().first().alias("issuer_card2"),
        pl.col("card3").drop_nulls().first().alias("issuer_card3"),
        pl.col("card5").drop_nulls().first().alias("issuer_card5"),
    )
    return (
        cards.join(detail, on="card_id", how="left")
        .select(
            pl.col("card_id"),
            pl.col("customer_id"),
            pl.col("card_type_key").alias("card_type"),
            pl.col("card_network").fill_null(""),
            pl.col("issuer_card1").fill_null(""),
            pl.col("issuer_card2").fill_null(""),
            pl.col("issuer_card3").fill_null(""),
            pl.col("issuer_card5").fill_null(""),
            pl.col("txn_count").alias("n_transactions"),
            pl.col("first_seen"),
            pl.col("last_seen"),
        )
        .sort("card_id")
    )


def build_cardholder_vertices(transactions: pl.DataFrame, cards: pl.DataFrame) -> pl.DataFrame:
    per_customer = transactions.group_by("customer_id").agg(
        pl.len().alias("n_transactions"),
        pl.col("ts").min().alias("first_seen"),
        pl.col("ts").max().alias("last_seen"),
    )
    card_counts = cards.group_by("customer_id").agg(pl.len().alias("n_cards"))
    return (
        per_customer.join(card_counts, on="customer_id", how="left")
        .select(
            "customer_id",
            pl.col("n_cards").fill_null(0),
            "n_transactions",
            "first_seen",
            "last_seen",
        )
        .sort("customer_id")
    )


def build_device_vertices(identity: pl.DataFrame, transactions: pl.DataFrame) -> pl.DataFrame:
    joined = identity.join(
        transactions.select(["TransactionID", "card_id", "ts"]),
        on="TransactionID",
        how="left",
    )
    return (
        joined.group_by("device_id")
        .agg(
            pl.col("device_signature").first().alias("label"),
            pl.col("DeviceInfo").drop_nulls().first().alias("device_info"),
            pl.col("id_30").drop_nulls().first().alias("operating_system"),
            pl.col("id_31").drop_nulls().first().alias("browser"),
            pl.col("id_33").drop_nulls().first().alias("screen"),
            pl.col("DeviceType").drop_nulls().first().alias("device_type"),
            pl.col("id_23").drop_nulls().first().alias("proxy_category"),
            pl.col("id_34").drop_nulls().first().alias("match_status"),
            pl.col("id_15").drop_nulls().first().alias("new_or_found"),
            pl.col("signature_strength").max().alias("signature_strength"),
            pl.len().alias("n_transactions"),
            pl.col("card_id").n_unique().alias("n_cards"),
            pl.col("ts").min().alias("first_seen"),
            pl.col("ts").max().alias("last_seen"),
        )
        .with_columns(
            [
                pl.col(name).fill_null("")
                for name in (
                    "label",
                    "device_info",
                    "operating_system",
                    "browser",
                    "screen",
                    "device_type",
                    "proxy_category",
                    "match_status",
                    "new_or_found",
                )
            ]
        )
        .sort("device_id")
    )


def _domain_profile(transactions: pl.DataFrame, column: str) -> pl.DataFrame:
    return (
        transactions.filter(pl.col(column).is_not_null() & (pl.col(column) != ""))
        .group_by(column)
        .agg(pl.len().alias("n_transactions"), pl.col("card_id").n_unique().alias("n_cards"))
        .rename({column: "domain"})
    )


def build_email_domain_vertices(transactions: pl.DataFrame) -> pl.DataFrame:
    purchaser = _domain_profile(transactions, "P_emaildomain")
    recipient = _domain_profile(transactions, "R_emaildomain")
    return (
        pl.concat([purchaser, recipient])
        .group_by("domain")
        .agg(pl.col("n_transactions").sum(), pl.col("n_cards").max())
        .sort("domain")
    )


def build_billing_region_vertices(transactions: pl.DataFrame) -> pl.DataFrame:
    return (
        transactions.filter(pl.col("addr1").is_not_null() & (pl.col("addr1") != ""))
        .group_by("addr1")
        .agg(
            pl.col("addr2").drop_nulls().first().alias("country_code"),
            pl.len().alias("n_transactions"),
            pl.col("card_id").n_unique().alias("n_cards"),
        )
        .rename({"addr1": "region_code"})
        .with_columns(pl.col("country_code").fill_null(""))
        .sort("region_code")
    )


def build_closed_case_vertices(raw_dir: Path) -> pl.DataFrame:
    closed = pl.read_csv(raw_dir / "closed_cases_history.csv", infer_schema_length=0)
    # memory_text is what prior-case retrieval embeds and reads. It is built
    # from post-closure fields, which is why a closed case is only admissible
    # once closed_at is at or before the new case's anchor time.
    memory_text = pl.concat_str(
        [
            pl.lit("Case "),
            pl.col("case_id"),
            pl.lit(" outcome "),
            pl.col("outcome").fill_null(""),
            pl.lit(" pattern "),
            pl.col("pattern").fill_null(""),
            pl.lit(". Exposure USD "),
            pl.col("exposure_usd").fill_null("0"),
            pl.lit(" over "),
            pl.col("n_txns").fill_null("0"),
            pl.lit(" transactions. Actions "),
            pl.col("actions_taken").fill_null(""),
            pl.lit(". Report filed "),
            pl.col("report_filed").fill_null(""),
            pl.lit(". "),
            pl.col("analyst_notes").fill_null(""),
        ]
    ).alias("memory_text")

    return closed.select(
        "case_id",
        "customer_id",
        "card_id",
        "opened_at",
        "closed_at",
        pl.col("outcome").fill_null(""),
        pl.col("pattern").fill_null(""),
        pl.col("first_fraud_txn_id").fill_null("").alias("first_fraud_txn_id"),
        pl.col("n_txns").cast(pl.Int64, strict=False).fill_null(0).alias("n_txns"),
        pl.col("exposure_usd").cast(pl.Float64, strict=False).fill_null(0.0).alias("exposure_usd"),
        pl.col("actions_taken").fill_null(""),
        pl.col("report_filed").fill_null(""),
        pl.col("analyst_notes").fill_null(""),
        memory_text,
    ).sort("case_id")


def build_edges(
    transactions: pl.DataFrame, identity: pl.DataFrame, raw_dir: Path
) -> dict[str, pl.DataFrame]:
    edges: dict[str, pl.DataFrame] = {}

    edges["owns"] = (
        transactions.select(["customer_id", "card_id"]).unique().sort(["customer_id", "card_id"])
    )
    edges["made"] = transactions.select(
        pl.col("card_id"), pl.col("TransactionID").alias("txn_id")
    ).sort(["card_id", "txn_id"])

    strong = identity.filter(pl.col("signature_strength") >= MIN_SIGNATURE_STRENGTH_FOR_EDGE)
    edges["from_device"] = strong.select(
        pl.col("TransactionID").alias("txn_id"), pl.col("device_id")
    ).sort("txn_id")

    edges["purchaser_email"] = (
        transactions.filter(pl.col("P_emaildomain").is_not_null() & (pl.col("P_emaildomain") != ""))
        .select(pl.col("TransactionID").alias("txn_id"), pl.col("P_emaildomain").alias("domain"))
        .sort("txn_id")
    )
    edges["recipient_email"] = (
        transactions.filter(pl.col("R_emaildomain").is_not_null() & (pl.col("R_emaildomain") != ""))
        .select(pl.col("TransactionID").alias("txn_id"), pl.col("R_emaildomain").alias("domain"))
        .sort("txn_id")
    )
    edges["billed_in"] = (
        transactions.filter(pl.col("addr1").is_not_null() & (pl.col("addr1") != ""))
        .select(pl.col("TransactionID").alias("txn_id"), pl.col("addr1").alias("region_code"))
        .sort("txn_id")
    )

    # NEXT: deterministic order within a card, with the id as the tie-break.
    ordered = (
        transactions.select(["card_id", "TransactionID", "ts"])
        .with_columns(pl.col("ts").str.to_datetime(DATETIME_FORMAT, strict=False).alias("ts_dt"))
        .sort(["card_id", "ts_dt", "TransactionID"])
    )
    ordered = ordered.with_columns(
        pl.col("TransactionID").shift(-1).over("card_id").alias("next_txn_id"),
        pl.col("ts_dt").shift(-1).over("card_id").alias("next_ts"),
    )
    edges["next"] = (
        ordered.filter(pl.col("next_txn_id").is_not_null())
        .select(
            pl.col("TransactionID").alias("txn_id"),
            pl.col("next_txn_id"),
            (pl.col("next_ts") - pl.col("ts_dt"))
            .dt.total_seconds()
            .cast(pl.Int64)
            .alias("gap_seconds"),
        )
        .sort("txn_id")
    )

    closed = pl.read_csv(raw_dir / "closed_cases_history.csv", infer_schema_length=0)
    known_txns = set(transactions["TransactionID"].to_list())
    known_cards = set(transactions["card_id"].to_list())

    involves = (
        closed.select(["case_id", "txn_ids"])
        .with_columns(pl.col("txn_ids").str.split("|").alias("txn"))
        .explode("txn", empty_as_null=True)
        .filter(pl.col("txn").is_not_null() & (pl.col("txn") != ""))
        .select("case_id", pl.col("txn").alias("txn_id"))
    )
    edges["case_involves"] = involves.filter(pl.col("txn_id").is_in(list(known_txns))).sort(
        "case_id"
    )

    edges["case_on_card"] = (
        closed.select(["case_id", "card_id"])
        .filter(pl.col("card_id").is_in(list(known_cards)))
        .sort("case_id")
    )

    connected = (
        closed.select(["case_id", "connected_card_ids"])
        .with_columns(pl.col("connected_card_ids").fill_null("").str.split("|").alias("cc"))
        .explode("cc", empty_as_null=True)
        .filter(pl.col("cc").is_not_null() & (pl.col("cc") != ""))
        .select("case_id", pl.col("cc").alias("card_id"))
    )
    edges["case_connected_to"] = connected.filter(pl.col("card_id").is_in(list(known_cards))).sort(
        "case_id"
    )

    return edges
