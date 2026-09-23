"""Gate 2 exit: one fixture case through official TigerGraph MCP to a cited evidence package.

    .venv/Scripts/python scripts/run_gate2_fixture.py

Path, end to end:

    official tigergraph-mcp server (restricted surface)
    -> MCPGraphToolPort, inside FallbackGraphToolPort (direct fallback armed)
    -> installed GSQL queries and time-bounded WCC
    -> feature assembler
    -> TigerGraph vector prior-case retrieval
    -> TigerGraph vector policy retrieval
    -> GraphRAG evidence package
    -> citation and leakage validation

The direct fallback is armed because that is the production configuration,
but the exit only passes when it was NOT used: every call must have gone
through MCP. The same queries are then re-run through the direct adapter,
separately, to record MCP/direct equivalence.

Artifacts, all under the git-ignored runs/gate2/:

    mcp_tool_inventory.json      sanitized served-tool inventory and startup
    mcp_calls.jsonl              sanitized per-call log (vectors as dims + hash)
    mcp_server_stderr.log        the server's own tool-call log, sanitized
    mcp_smoke_result.json        one normalized live MCP query result
    mcp_direct_equivalence.json  canonical MCP vs direct comparison per query
    evidence_package_<case>.json the serialized package
    citation_report_<case>.json  the validation report
    gate2_exit_summary.json      every exit requirement and whether it held

Exit code 0 only when every requirement held.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evidence.citations import validate_package  # noqa: E402
from evidence.collector import CaseTrigger  # noqa: E402
from evidence.context_builder import build_evidence_package  # noqa: E402
from graph.client import TigerGraphConfigError, connect, load_config  # noqa: E402
from graph.mcp_client import (  # noqa: E402
    MCP_SERVED_TOOLS,
    MCPSession,
    describe_startup,
    sanitize,
)
from graph.tool_port import (  # noqa: E402
    FORBIDDEN_QUERIES,
    MAX_GRAPH_CALLS,
    READ_QUERIES,
    CallBudget,
    CallLog,
    DirectGraphToolPort,
    FallbackGraphToolPort,
    MCPGraphToolPort,
    canonical,
    vector_fingerprint,
)
from retrieval.embeddings import embed  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs" / "gate2"

#: The Gate 2 exit fixture. Chosen over HHG-017 because it measurably
#: exercises more of the required evidence: a six-card fraud-enriched WCC
#: component with path segments and a non-supernode shared device.
FIXTURE = CaseTrigger(
    case_id="HHG-019",
    flagged_txn_id="3503878",
    card_id="C07987-K2",
    customer_id="C07987",
    trigger_type="risk_score",
    trigger_text=(
        "Real-time model scored transaction 3503878 ($99.92, online) at 0.90. Review and decide."
    ),
    opened_at="2016-12-01 22:28:53",
    risk_score=0.90,
)

STRUCTURAL_QUERIES = {
    "get_case_context_v1",
    "get_card_baseline_v1",
    "get_transaction_window_v1",
    "extract_temporal_graph_features_v1",
    "find_shared_origin_activity_v1",
    "find_region_anomalies_v1",
    "wcc_shared_origin_v1",
    "calculate_case_exposure_v1",
}


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _sanitize_file(path: Path, config) -> None:
    if path.exists():
        path.write_text(sanitize(path.read_text(encoding="utf-8"), config), encoding="utf-8")


def run(runs_dir: Path = DEFAULT_RUNS_DIR, trigger: CaseTrigger = FIXTURE) -> dict[str, Any]:
    config = load_config()
    runs_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("mcp_calls.jsonl", "mcp_server_stderr.log"):
        (runs_dir / stale).unlink(missing_ok=True)

    started = time.perf_counter()
    session = MCPSession(config, stderr_path=runs_dir / "mcp_server_stderr.log").start()
    startup_s = round(time.perf_counter() - started, 2)
    try:
        inventory = {
            "server": session.server_info,
            "package": "tigergraph-mcp==1.0.3",
            "transport": "stdio",
            "startup_command": describe_startup(),
            "startup_seconds": startup_s,
            "served_tools": [tool.as_dict() for tool in session.inventory],
            "restricted_surface": list(MCP_SERVED_TOOLS),
            "allowlisted_read_queries": sorted(READ_QUERIES),
            "forbidden_queries": sorted(FORBIDDEN_QUERIES),
        }
        _write(runs_dir / "mcp_tool_inventory.json", inventory)

        log = CallLog(runs_dir / "mcp_calls.jsonl")
        budget = CallBudget(MAX_GRAPH_CALLS)
        mcp = MCPGraphToolPort(session, budget=budget, log=log)
        direct_for_fallback = DirectGraphToolPort(connect(config), config=config)
        port = FallbackGraphToolPort(mcp, direct_for_fallback)

        built = time.perf_counter()
        package = build_evidence_package(port, trigger)
        package_s = round(time.perf_counter() - built, 2)
        report = validate_package(package)

        _write(
            runs_dir / f"evidence_package_{trigger.case_id}.json",
            json.loads(package.model_dump_json()),
        )
        _write(
            runs_dir / f"citation_report_{trigger.case_id}.json",
            json.loads(report.model_dump_json()),
        )

        # The smoke result: the first MCP call's normalized values, trimmed.
        smoke_port = MCPGraphToolPort(session, budget=CallBudget(1))
        smoke = smoke_port.run_query(
            "get_case_context_v1",
            {"flagged_txn_id": trigger.flagged_txn_id, "as_of_ts": trigger.opened_at},
        )
        _write(
            runs_dir / "mcp_smoke_result.json",
            {
                "tool": smoke.record.tool,
                "query_name": smoke.query_name,
                "trace_id": smoke.record.trace_id,
                "duration_ms": smoke.record.duration_ms,
                "refused": smoke.refused,
                "flagged_transaction": smoke.values.get("flagged_transaction"),
                "effective_cutoff": smoke.values.get("effective_cutoff"),
                "result_blocks": smoke.record.result_blocks,
            },
        )

        # Equivalence: replay every MCP call of the package through BOTH
        # adapters, with the exact parameters the call record logged. A query
        # vector is logged only as a fingerprint, so it is re-embedded from
        # the recorded query text and must reproduce the logged SHA-256.
        replay_mcp = MCPGraphToolPort(session, budget=CallBudget(20))
        replay_direct = DirectGraphToolPort(connect(config), config=config, budget=CallBudget(20))
        comparisons = []
        for record in [r for r in log.records if r.ok and r.adapter == "mcp"]:
            params = replay_parameters(record, package)
            through_mcp = replay_mcp.run_query(record.query_name, params)
            through_direct = replay_direct.run_query(record.query_name, params)
            comparisons.append(
                {
                    "query_name": record.query_name,
                    "package_trace_id": record.trace_id,
                    "mcp_trace_id": through_mcp.record.trace_id,
                    "direct_trace_id": through_direct.record.trace_id,
                    "canonically_equal": canonical(through_mcp.values)
                    == canonical(through_direct.values),
                }
            )
        _write(runs_dir / "mcp_direct_equivalence.json", comparisons)
    finally:
        session.close()
        _sanitize_file(runs_dir / "mcp_server_stderr.log", config)

    summary = exit_summary(package, report, inventory, comparisons, package_s)
    _write(runs_dir / "gate2_exit_summary.json", summary)
    return summary


def replay_parameters(record, package) -> dict[str, Any]:
    """The parameters of a logged call, with its query vector rebuilt and checked."""
    params = dict(record.parameters)
    for name, value in params.items():
        if isinstance(value, list) and value and str(value[-1]).startswith("... "):
            raise RuntimeError(f"{record.query_name}.{name} was truncated in the log")
    if "query_vector" in params:
        text = (
            package.prior_case_retrieval.query_text
            if record.query_name == "find_similar_closed_cases_v1"
            else package.policy_retrieval.query_text
        )
        vector = embed(text)
        rebuilt = vector_fingerprint([round(value, 6) for value in vector])
        if rebuilt != params["query_vector"]:
            raise RuntimeError(f"{record.query_name}: re-embedded vector does not match the log")
        params["query_vector"] = vector
    return params


def exit_summary(package, report, inventory, comparisons, package_s) -> dict[str, Any]:
    meta = package.metadata
    items = package.items()
    graph_items = [i for i in items if i.section == "graph_evidence"]
    wcc_items = [
        i for i in items if i.query_name == "wcc_shared_origin_v1" and i.availability == "observed"
    ]
    cases = package.prior_case_retrieval
    policy = package.policy_retrieval
    item_traces = {i.trace_id for i in items if i.trace_id}
    checks = {
        "mcp_served_exactly_the_restricted_surface": sorted(
            t["name"] for t in inventory["served_tools"]
        )
        == sorted(MCP_SERVED_TOOLS),
        "primary_path_was_mcp": meta.primary_adapter == "mcp",
        "direct_fallback_not_used": not meta.fallback_occurred
        and set(meta.adapters_used) == {"mcp"},
        "every_call_succeeded_through_mcp": all(c.ok and c.adapter == "mcp" for c in meta.calls),
        "within_the_graph_call_budget": meta.graph_call_count <= MAX_GRAPH_CALLS,
        "every_item_trace_is_an_mcp_call": item_traces <= set(meta.mcp_trace_ids),
        "trigger_and_baseline_present": bool(package.sections["trigger_and_baseline"]),
        "structural_graph_evidence_present": any(
            i.query_name in STRUCTURAL_QUERIES for i in graph_items
        ),
        "wcc_algorithm_output_present": bool(wcc_items),
        "exact_path_segments_present": any(i.path_segments for i in wcc_items),
        "prior_cases_through_tigergraph_vector": cases.retrieval_path == "tigergraph_vector"
        and bool(cases.cases),
        "fraud_and_cleared_analogues_present": {c.outcome for c in cases.cases}
        >= {"confirmed_fraud", "cleared"},
        "prior_cases_have_scores_and_reasons": all(
            c.composite_retrieval_score > 0 and c.reasons for c in cases.cases
        ),
        "policy_chunks_through_tigergraph_vector": bool(policy.chunks)
        and all(ch.tigergraph_vector_rank >= 1 for ch in policy.chunks),
        "supporting_evidence_present": any(i.strength == "supporting" for i in items),
        "contradicting_evidence_present": any(i.strength == "contradicting" for i in items),
        "neutral_or_unavailable_evidence_present": any(i.strength == "neutral" for i in items),
        "query_names_and_versions_recorded": bool(meta.query_versions)
        and all(i.query_bundle_version for i in items),
        "no_evidence_crosses_the_anchor": package.leakage_check_passed
        and package.data_max_time <= package.anchor_time,
        "citation_validation_passed": report.passed,
        "mcp_and_direct_are_equivalent": bool(comparisons)
        and all(c["canonically_equal"] for c in comparisons),
    }
    return {
        "fixture": package.case_id,
        "package_id": package.package_id,
        "exit_passed": all(checks.values()),
        "checks": checks,
        "anchor_time": package.anchor_time,
        "review_time": meta.review_time,
        "data_max_time": package.data_max_time,
        "port_mode": meta.port_mode,
        "adapters_used": meta.adapters_used,
        "fallback_occurred": meta.fallback_occurred,
        "graph_call_count": meta.graph_call_count,
        "graph_call_budget": meta.graph_call_budget,
        "mcp_total_call_ms": round(sum(c.duration_ms for c in meta.calls), 1),
        "package_build_seconds": package_s,
        "mcp_trace_ids": meta.mcp_trace_ids,
        "counts": package.counts(),
        "prior_cases": [
            {
                "case_id": c.case_id,
                "group": c.group,
                "outcome": c.outcome,
                "composite_retrieval_score": c.composite_retrieval_score,
                "vector_cosine_similarity": c.vector_cosine_similarity,
                "reasons": c.reasons,
            }
            for c in cases.cases
        ],
        "policy_chunks": [
            {
                "chunk_id": ch.chunk_id,
                "tigergraph_vector_rank": ch.tigergraph_vector_rank,
                "vector_cosine_similarity": ch.vector_cosine_similarity,
                "signal": ch.signal,
            }
            for ch in policy.chunks
        ],
        "wcc": {
            "component_size": package.features["wcc_component_size"].value,
            "path_segments": len(package.features["wcc_path_segments"].value or []),
            "fraud_enriched_members": package.features["wcc_fraud_enriched_members"].value,
        },
        "withheld_or_unavailable": meta.withheld_or_unavailable,
        "citation_checks_failed": [c.name for c in report.failed()],
    }


def main() -> int:
    try:
        summary = run()
    except TigerGraphConfigError as error:
        print(f"FAILED: {error}")
        return 1
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "fixture",
                    "exit_passed",
                    "port_mode",
                    "adapters_used",
                    "fallback_occurred",
                    "graph_call_count",
                    "counts",
                    "citation_checks_failed",
                )
            },
            indent=2,
        )
    )
    failed = [name for name, held in summary["checks"].items() if not held]
    if failed:
        print(f"Gate 2 exit FAILED: {failed}")
        return 1
    print(f"Gate 2 exit passed. Artifacts in {DEFAULT_RUNS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
