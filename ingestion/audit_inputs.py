"""Phase zero data audit for the four supplied HHGOA files.

Produces the record the build plan's data audit gate requires: file hashes and
sizes, row counts, exact headers, null rates, duplicate identifier counts, the
proven card identifier mapping, benchmark identifier resolution, temporal
range and timestamp interpretation, distinct channels and outcomes, shared
entity cardinality and collision analysis, and a leakage audit separating
fields available at transaction time from fields created at case closure.

Everything here is read-only. Nothing in this module invents an identifier:
every reported mapping is computed from the supplied files.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ingestion.identifiers import attach_card_ids, build_card_table

CHUNK = 1 << 22

#: Transaction columns the investigation needs. The remaining Vesta feature
#: columns stay in local staging rather than becoming graph attributes.
TXN_CORE_COLUMNS = [
    "TransactionID",
    "TransactionDT",
    "TransactionAmt",
    "ProductCD",
    "card1",
    "card2",
    "card3",
    "card4",
    "card5",
    "card6",
    "addr1",
    "addr2",
    "dist1",
    "dist2",
    "P_emaildomain",
    "R_emaildomain",
    "customer_id",
    "ts",
    "channel",
    "risk_score",
]

#: Identity columns that form the device signature and its supporting context.
IDENTITY_DEVICE_COLUMNS = [
    "TransactionID",
    "DeviceType",
    "DeviceInfo",
    "id_15",
    "id_23",
    "id_30",
    "id_31",
    "id_33",
    "id_34",
]

#: Closed-case fields created by the investigation, never available at the
#: anchor time of a case that is still open. Using any of these for a case that
#: closed after the anchor time is leakage.
CLOSED_CASE_POST_CLOSURE_FIELDS = [
    "closed_at",
    "outcome",
    "pattern",
    "first_fraud_txn_id",
    "txn_ids",
    "n_txns",
    "exposure_usd",
    "connected_card_ids",
    "actions_taken",
    "report_filed",
    "analyst_notes",
]


@dataclass(frozen=True)
class FileFacts:
    name: str
    size_bytes: int
    sha256: str
    rows: int
    columns: int


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def file_facts(path: Path, frame_height: int, column_count: int) -> FileFacts:
    return FileFacts(
        name=path.name,
        size_bytes=path.stat().st_size,
        sha256=sha256_of(path),
        rows=frame_height,
        columns=column_count,
    )


def null_percentages(frame: pl.DataFrame, columns: list[str]) -> dict[str, float]:
    height = frame.height or 1
    return {
        column: round(100.0 * frame[column].null_count() / height, 4)
        for column in columns
        if column in frame.columns
    }


def duplicate_count(frame: pl.DataFrame, column: str) -> int:
    return frame.height - frame[column].n_unique()


def value_counts(frame: pl.DataFrame, column: str, limit: int = 30) -> dict[str, int]:
    counts = (
        frame.group_by(column)
        .agg(pl.len().alias("n"))
        .sort("n", descending=True)
        .head(limit)
        .to_dicts()
    )
    return {("<null>" if row[column] is None else str(row[column])): row["n"] for row in counts}


def numeric_summary(frame: pl.DataFrame, column: str) -> dict[str, float | None]:
    series = frame[column].cast(pl.Float64, strict=False)
    if series.len() == 0:
        return {}
    return {
        "min": series.min(),
        "p25": series.quantile(0.25),
        "median": series.median(),
        "p75": series.quantile(0.75),
        "p99": series.quantile(0.99),
        "max": series.max(),
        "null_count": series.null_count(),
    }


def shared_entity_profile(frame: pl.DataFrame, column: str, card_column: str) -> dict:
    """Cardinality and collision profile for a candidate shared-entity vertex.

    A high card count on a single value means the entity is a supernode and
    cannot by itself imply coordination.
    """
    present = frame.filter(pl.col(column).is_not_null())
    per_value = (
        present.group_by(column)
        .agg(
            pl.col(card_column).n_unique().alias("cards"),
            pl.len().alias("transactions"),
        )
        .sort("cards", descending=True)
    )
    if per_value.height == 0:
        return {"distinct_values": 0, "coverage_pct": 0.0}
    cards_series = per_value["cards"]
    return {
        "distinct_values": per_value.height,
        "coverage_pct": round(100.0 * present.height / (frame.height or 1), 4),
        "cards_per_value": {
            "max": int(cards_series.max()),
            "median": float(cards_series.median()),
            "p99": float(cards_series.quantile(0.99)),
        },
        "values_linking_one_card_only": int((cards_series == 1).sum()),
        "values_linking_over_100_cards": int((cards_series > 100).sum()),
        "top_values_by_card_count": [
            {
                "value": str(row[column]),
                "cards": row["cards"],
                "transactions": row["transactions"],
            }
            for row in per_value.head(5).to_dicts()
        ],
    }


def device_signature_expression() -> pl.Expr:
    """Composite device signature: DeviceInfo | OS | browser | screen.

    Matches the profile string shape used in the dataset README's worked
    example. Missing parts are kept as empty so signature strength can be
    measured rather than silently collapsing distinct devices together.
    """
    parts = [
        pl.col("DeviceInfo").fill_null(""),
        pl.col("id_30").fill_null(""),
        pl.col("id_31").fill_null(""),
        pl.col("id_33").fill_null(""),
    ]
    return pl.concat_str(parts, separator=" | ").alias("device_signature")


def device_signature_strength() -> pl.Expr:
    """Number of the four signature fields that are present (0-4)."""
    fields = ["DeviceInfo", "id_30", "id_31", "id_33"]
    return sum(pl.col(field).is_not_null().cast(pl.Int32) for field in fields).alias(
        "signature_strength"
    )


def build_transaction_frame(raw_dir: Path) -> pl.DataFrame:
    """Load the investigation-relevant transaction columns with card_id attached."""
    frame = (
        pl.scan_csv(raw_dir / "transactions.csv", infer_schema_length=0)
        .select(TXN_CORE_COLUMNS)
        .collect()
    )
    return attach_card_ids(frame)


def build_identity_frame(raw_dir: Path) -> pl.DataFrame:
    return (
        pl.scan_csv(raw_dir / "identity.csv", infer_schema_length=0)
        .select(IDENTITY_DEVICE_COLUMNS)
        .collect()
        .with_columns(device_signature_expression(), device_signature_strength())
    )


def cards_table(transactions: pl.DataFrame) -> pl.DataFrame:
    return build_card_table(transactions)
