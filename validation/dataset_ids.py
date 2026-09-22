"""The set of identifiers an answer is allowed to name.

The dataset README is explicit: "Every ID in your answer files must exist in
this dataset" and "Made-up IDs score zero". This module builds that index once
from the supplied files and caches it, so the validator can check every
identifier and recompute every exposure without rereading 675 MB.

The cache lives under ``data/cache/`` (git-ignored) and is keyed by the SHA-256
of the source files, so editing or replacing a supplied file invalidates it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from ingestion.audit_inputs import (
    device_signature_expression,
    device_signature_strength,
)
from ingestion.identifiers import attach_card_ids, build_card_table

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = PROJECT_ROOT / "data" / "raw"
DEFAULT_CACHE = PROJECT_ROOT / "data" / "cache"

#: Tolerance for comparing a reported exposure with the recomputed sum.
#: One cent per transaction accumulates, so compare at half a cent per item
#: with a one cent floor.
EXPOSURE_TOLERANCE_USD = 0.01

_CACHE_INPUTS = ("transactions.csv", "identity.csv", "closed_cases_history.csv", "case_pack.csv")


def _fingerprint(raw_dir: Path) -> str:
    """Cheap fingerprint of the supplied files: name, size and mtime."""
    parts = []
    for name in _CACHE_INPUTS:
        path = raw_dir / name
        stat = path.stat()
        parts.append(f"{name}:{stat.st_size}:{int(stat.st_mtime)}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class DatasetIndex:
    """Every identifier and amount the validator needs, held in memory."""

    transaction_amounts: dict[str, float]
    card_ids: frozenset[str]
    customer_ids: frozenset[str]
    closed_case_ids: frozenset[str]
    benchmark_case_ids: frozenset[str]
    device_profiles: frozenset[str]
    #: closed case id -> closure timestamp, for the memory-epoch cutoff check
    closed_case_closed_at: dict[str, str] = field(default_factory=dict)
    #: benchmark case id -> anchor (flagged transaction) timestamp
    benchmark_anchor_ts: dict[str, str] = field(default_factory=dict)
    #: benchmark case id -> flagged transaction id
    benchmark_flagged_txn: dict[str, str] = field(default_factory=dict)

    @property
    def transaction_ids(self) -> frozenset[str]:
        return frozenset(self.transaction_amounts)

    def exposure_of(self, txn_ids: list[str]) -> tuple[float, list[str]]:
        """Sum absolute amounts, returning the total and any unknown IDs."""
        total = 0.0
        unknown: list[str] = []
        for txn_id in txn_ids:
            amount = self.transaction_amounts.get(txn_id)
            if amount is None:
                unknown.append(txn_id)
            else:
                total += abs(amount)
        return round(total, 2), unknown

    def unknown(self, kind: str, values: list[str]) -> list[str]:
        """Return the values of ``kind`` that are not in the dataset."""
        known = {
            "transaction": self.transaction_ids,
            "card": self.card_ids,
            "customer": self.customer_ids,
            "closed_case": self.closed_case_ids,
            "benchmark_case": self.benchmark_case_ids,
            "device_profile": self.device_profiles,
        }[kind]
        return [value for value in values if value not in known]


def _build(raw_dir: Path) -> dict:
    transactions = (
        pl.scan_csv(raw_dir / "transactions.csv", infer_schema_length=0)
        .select(["TransactionID", "TransactionAmt", "customer_id", "card6", "ts"])
        .collect()
    )
    transactions = attach_card_ids(transactions)
    cards = build_card_table(transactions)

    identity = (
        pl.scan_csv(raw_dir / "identity.csv", infer_schema_length=0)
        .select(["TransactionID", "DeviceInfo", "id_30", "id_31", "id_33"])
        .collect()
        .with_columns(device_signature_expression(), device_signature_strength())
    )

    closed = pl.read_csv(raw_dir / "closed_cases_history.csv", infer_schema_length=0)
    pack = pl.read_csv(raw_dir / "case_pack.csv", infer_schema_length=0)

    anchors = pack.select(["case_id", "flagged_txn_id"]).join(
        transactions.select([pl.col("TransactionID").alias("flagged_txn_id"), "ts"]),
        on="flagged_txn_id",
        how="left",
    )

    amounts = transactions.select(
        ["TransactionID", pl.col("TransactionAmt").cast(pl.Float64, strict=False)]
    )

    return {
        "transaction_amounts": dict(amounts.iter_rows()),
        "card_ids": sorted(cards["card_id"].to_list()),
        "customer_ids": sorted(transactions["customer_id"].unique().to_list()),
        "closed_case_ids": sorted(closed["case_id"].to_list()),
        "benchmark_case_ids": sorted(pack["case_id"].to_list()),
        # A device profile is only citable when its signature is strong enough
        # to be evidence; a blank or near-blank signature links nothing.
        "device_profiles": sorted(
            identity.filter(pl.col("signature_strength") >= 2)["device_signature"]
            .unique()
            .to_list()
        ),
        "closed_case_closed_at": dict(closed.select(["case_id", "closed_at"]).iter_rows()),
        "benchmark_anchor_ts": dict(anchors.select(["case_id", "ts"]).iter_rows()),
        "benchmark_flagged_txn": dict(pack.select(["case_id", "flagged_txn_id"]).iter_rows()),
    }


def load_dataset_index(
    raw_dir: Path | None = None,
    cache_dir: Path | None = None,
    *,
    refresh: bool = False,
) -> DatasetIndex:
    """Load the identifier index, building and caching it on first use."""
    raw_dir = raw_dir or DEFAULT_RAW
    cache_dir = cache_dir or DEFAULT_CACHE
    cache_path = cache_dir / f"dataset_index_{_fingerprint(raw_dir)}.json"

    if cache_path.exists() and not refresh:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        payload = _build(raw_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

    return DatasetIndex(
        transaction_amounts=payload["transaction_amounts"],
        card_ids=frozenset(payload["card_ids"]),
        customer_ids=frozenset(payload["customer_ids"]),
        closed_case_ids=frozenset(payload["closed_case_ids"]),
        benchmark_case_ids=frozenset(payload["benchmark_case_ids"]),
        device_profiles=frozenset(payload["device_profiles"]),
        closed_case_closed_at=payload["closed_case_closed_at"],
        benchmark_anchor_ts=payload["benchmark_anchor_ts"],
        benchmark_flagged_txn=payload["benchmark_flagged_txn"],
    )
