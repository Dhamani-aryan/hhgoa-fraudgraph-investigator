"""Citation, provenance and leakage validation of an evidence package.

Every check is named and reports the exact items that fail it, so a failing
package says what to fix. :func:`validate_package` fails when:

* an evidence id is missing, malformed or duplicated;
* a claim has no source reference or no query/document behind it;
* an entity id cannot be resolved to an id the graph or vector results returned;
* a policy anchor is not a retrieved PolicyChunk and a known document section;
* a cited prior case was not returned by retrieval, or lacks score or reasons;
* a claim's data timestamp exceeds the anchor, or its leakage flag disagrees;
* a resource-only lifetime precheck appears anywhere in the package;
* the package exceeds a configured cap or is missing a section;
* a WCC claim of a connected component lacks returned path segments, or a
  segment cites a card or device the graph did not return;
* an unavailable (withheld/refused/not applicable) item is not neutral;
* the hash chain is broken;
* the package lacks supporting, contradicting or neutral evidence.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from evidence.ledger import verify_chain
from evidence.models import SECTIONS, EvidencePackage
from graph.result_normalizers import RESOURCE_PRECHECK_SUFFIX
from retrieval.policy_chunks import all_chunks

_EVIDENCE_ID = re.compile(r"^EV-[A-Za-z0-9-]+-\d{3}$")


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    failures: list[str]


class CitationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str
    case_id: str
    passed: bool
    checks: list[CheckResult]

    def failed(self) -> list[CheckResult]:
        return [check for check in self.checks if not check.passed]


def _keys(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def validate_package(
    package: EvidencePackage, *, caps: dict[str, int] | None = None
) -> CitationReport:
    caps = caps or package.metadata.caps
    items = package.items()
    registry = set(package.observed_entity_ids)
    retrieved_cases = {case.case_id: case for case in package.prior_case_retrieval.cases}
    retrieved_chunks = set(package.policy_retrieval.chunk_ids)
    known_chunks = {chunk.chunk_id for chunk in all_chunks()}
    anchor = package.anchor_time
    checks: list[CheckResult] = []

    def check(name: str, failures: list[str]) -> None:
        checks.append(CheckResult(name=name, passed=not failures, failures=failures))

    ids = [item.evidence_id for item in items]
    check(
        "evidence_ids_present_unique_and_well_formed",
        [
            f"bad or duplicate evidence id {evidence_id!r}"
            for index, evidence_id in enumerate(ids)
            if not evidence_id or not _EVIDENCE_ID.match(evidence_id) or evidence_id in ids[:index]
        ],
    )

    check(
        "every_claim_has_a_source_reference",
        [
            f"{item.evidence_id}: no ref, query or document"
            for item in items
            if not item.ref or not item.claim or not (item.query_name or item.document_ref)
        ],
    )

    check(
        "every_entity_id_resolves",
        [
            f"{item.evidence_id}: {entity} was not returned by any graph or vector result"
            for item in items
            for entity in item.entity_ids
            if entity not in registry
        ]
        + [
            f"{item.evidence_id}: cites no entity id or policy anchor"
            for item in items
            if not item.entity_ids
        ],
    )

    policy_items = [item for item in items if item.section == "policy_context"]
    check(
        "policy_anchors_resolve",
        [
            f"{item.evidence_id}: {item.ref} is not a retrieved and known policy chunk"
            for item in policy_items
            if item.ref not in retrieved_chunks or item.ref not in known_chunks
        ]
        + [
            f"policy chunk {chunk_id} is not a known document section"
            for chunk_id in retrieved_chunks
            if chunk_id not in known_chunks
        ],
    )

    memory_items = [item for item in items if item.section == "case_memory"]
    memory_failures = []
    for item in memory_items:
        case_id = item.entity_ids[0] if item.entity_ids else ""
        case = retrieved_cases.get(case_id)
        if case is None:
            memory_failures.append(f"{item.evidence_id}: {case_id} was not retrieved")
            continue
        score = case.composite_retrieval_score
        if not (isinstance(score, float) and math.isfinite(score) and score > 0):
            memory_failures.append(f"{case_id}: no real positive retrieval score")
        if not case.reasons or not all(reason.strip() for reason in case.reasons):
            memory_failures.append(f"{case_id}: no retrieval reasons")
    for case in retrieved_cases.values():
        if not case.reasons:
            memory_failures.append(f"{case.case_id}: retrieved without reasons")
    check("cited_prior_cases_were_retrieved_with_score_and_reasons", memory_failures)

    check(
        "no_claim_crosses_the_anchor",
        [
            f"{item.evidence_id}: data at {item.data_max_time} is after the anchor {anchor}"
            for item in items
            if item.data_max_time and item.data_max_time > anchor
        ]
        + [
            f"{item.evidence_id}: leakage flag disagrees with its timestamps"
            for item in items
            if item.leakage_check_passed != (not item.data_max_time or item.data_max_time <= anchor)
        ]
        + [
            f"prior case {case.case_id} closed at {case.closed_at}, after the anchor"
            for case in retrieved_cases.values()
            if case.closed_at > anchor
        ]
        + (
            [f"package data_max_time {package.data_max_time} is after the anchor"]
            if package.data_max_time > anchor
            else []
        ),
    )

    rendered = json.loads(package.model_dump_json())
    check(
        "no_resource_precheck_in_evidence",
        sorted(
            {
                f"resource-only field {key} appears in the package"
                for key in _keys(rendered)
                if str(key).endswith(RESOURCE_PRECHECK_SUFFIX)
            }
        ),
    )

    segment_cap = caps.get("path_segments", 25)
    cap_failures = []
    if len(package.prior_case_retrieval.cases) > caps.get("prior_cases", 6):
        cap_failures.append(f"{len(package.prior_case_retrieval.cases)} prior cases")
    if len(package.policy_retrieval.chunks) > caps.get("policy_chunks", 4):
        cap_failures.append(f"{len(package.policy_retrieval.chunks)} policy chunks")
    if len(items) > caps.get("items", 60):
        cap_failures.append(f"{len(items)} evidence items")
    for item in items:
        if item.path_segments and len(item.path_segments) > segment_cap:
            cap_failures.append(f"{item.evidence_id}: {len(item.path_segments)} path segments")
        if len(item.entity_ids) > caps.get("entity_ids_per_item", 25):
            cap_failures.append(f"{item.evidence_id}: {len(item.entity_ids)} entity ids")
    missing = [section for section in SECTIONS if not package.sections.get(section)]
    cap_failures += [f"section {section} is empty" for section in missing]
    check("package_is_within_caps_with_all_sections", cap_failures)

    wcc_failures = []
    for item in items:
        if item.query_name != "wcc_shared_origin_v1" or item.availability != "observed":
            continue
        size = (item.value or {}).get("component_size", 0)
        if size > 1 and not item.path_segments:
            wcc_failures.append(f"{item.evidence_id}: a {size}-card component with no segments")
        for segment in item.path_segments or []:
            for key in ("from_card", "to_card", "device_id"):
                if segment.get(key) not in registry:
                    wcc_failures.append(
                        f"{item.evidence_id}: segment {key} "
                        f"{segment.get(key)} was not returned by the graph"
                    )
    check("wcc_claims_rest_on_returned_path_segments", wcc_failures)

    check(
        "unavailable_evidence_is_never_negative",
        [
            f"{item.evidence_id}: {item.availability} but {item.strength}"
            for item in items
            if item.availability != "observed" and item.strength != "neutral"
        ],
    )

    check(
        "hash_chain_is_intact",
        verify_chain(items)
        + (
            []
            if not items or items[-1].content_hash == package.ledger_final_hash
            else ["ledger_final_hash does not match the last record"]
        ),
    )

    present = {item.strength for item in items}
    check(
        "supporting_contradicting_and_neutral_evidence_present",
        [
            f"no {strength} evidence"
            for strength in ("supporting", "contradicting", "neutral")
            if strength not in present
        ],
    )

    return CitationReport(
        package_id=package.package_id,
        case_id=package.case_id,
        passed=all(result.passed for result in checks),
        checks=checks,
    )
