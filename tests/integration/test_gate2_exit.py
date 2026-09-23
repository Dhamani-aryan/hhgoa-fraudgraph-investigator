"""The Gate 2 exit criterion, rebuilt live and asserted requirement by requirement.

Gate 2 exit (build plan): a fixture case produces a compact evidence package
through MCP containing structural graph evidence, graph-algorithm output,
vector-retrieved memory and policy, negative evidence and traceable IDs.

This test runs ``scripts/run_gate2_fixture.py`` end to end against the live
workspace and the official MCP server, into a temporary directory, and checks
both the exit summary and the artifacts themselves.
"""

from __future__ import annotations

import json
import re

import pytest

from graph.client import TigerGraphConfigError, load_config
from graph.mcp_client import MCP_SERVED_TOOLS
from scripts import run_gate2_fixture

ARTIFACTS = (
    "mcp_tool_inventory.json",
    "mcp_calls.jsonl",
    "mcp_server_stderr.log",
    "mcp_smoke_result.json",
    "mcp_direct_equivalence.json",
    "evidence_package_HHG-019.json",
    "citation_report_HHG-019.json",
    "gate2_exit_summary.json",
)


@pytest.fixture(scope="module")
def exit_run(tmp_path_factory):
    try:
        config = load_config()
    except TigerGraphConfigError as error:
        pytest.skip(f"TigerGraph not available: {error}")
    runs = tmp_path_factory.mktemp("gate2")
    summary = run_gate2_fixture.run(runs)
    return summary, runs, config


def load(runs, name):
    return json.loads((runs / name).read_text(encoding="utf-8"))


# --- the exit summary ---------------------------------------------------------------------


def test_the_gate2_exit_passes(exit_run):
    summary, _, _ = exit_run
    failed = [name for name, held in summary["checks"].items() if not held]
    assert summary["exit_passed"] is True, failed


@pytest.mark.parametrize(
    "requirement",
    [
        "mcp_served_exactly_the_restricted_surface",
        "primary_path_was_mcp",
        "direct_fallback_not_used",
        "every_call_succeeded_through_mcp",
        "within_the_graph_call_budget",
        "every_item_trace_is_an_mcp_call",
        "trigger_and_baseline_present",
        "structural_graph_evidence_present",
        "wcc_algorithm_output_present",
        "exact_path_segments_present",
        "prior_cases_through_tigergraph_vector",
        "fraud_and_cleared_analogues_present",
        "prior_cases_have_scores_and_reasons",
        "policy_chunks_through_tigergraph_vector",
        "supporting_evidence_present",
        "contradicting_evidence_present",
        "neutral_or_unavailable_evidence_present",
        "query_names_and_versions_recorded",
        "no_evidence_crosses_the_anchor",
        "citation_validation_passed",
        "mcp_and_direct_are_equivalent",
    ],
)
def test_each_exit_requirement_holds(exit_run, requirement):
    summary, _, _ = exit_run
    assert summary["checks"][requirement] is True


def test_the_fixture_used_mcp_and_not_the_fallback(exit_run):
    summary, _, _ = exit_run
    assert summary["port_mode"] == "mcp_primary_with_direct_fallback"
    assert summary["adapters_used"] == {"mcp": summary["graph_call_count"]}
    assert summary["fallback_occurred"] is False
    assert len(summary["mcp_trace_ids"]) == summary["graph_call_count"] <= 12


def test_the_wcc_output_is_the_measured_component(exit_run):
    summary, _, _ = exit_run
    assert summary["wcc"]["component_size"] == 6
    assert summary["wcc"]["path_segments"] == 5


# --- the artifacts --------------------------------------------------------------------------


def test_every_artifact_is_written(exit_run):
    _, runs, _ = exit_run
    for name in ARTIFACTS:
        assert (runs / name).exists(), name


def test_no_artifact_carries_a_secret_a_host_or_an_embedding(exit_run):
    _, runs, config = exit_run
    host = config.host.split("//")[-1]
    embedding = re.compile(r"\[(?:\s*-?\d+\.\d+\s*,){100,}")
    for name in ARTIFACTS:
        text = (runs / name).read_text(encoding="utf-8")
        assert not [value for value in config.secret_values if value in text], name
        assert host not in text, name
        assert not embedding.search(text), f"{name} holds a vector"


def test_the_inventory_is_the_restricted_surface(exit_run):
    _, runs, _ = exit_run
    inventory = load(runs, "mcp_tool_inventory.json")
    assert sorted(t["name"] for t in inventory["served_tools"]) == sorted(MCP_SERVED_TOOLS)
    assert "write_investigation_case_v1" in inventory["forbidden_queries"]
    assert "write_investigation_case_v1" not in inventory["allowlisted_read_queries"]
    assert inventory["startup_command"].startswith("tigergraph-mcp --allowed-tools ")


def test_the_call_log_records_every_mcp_call(exit_run):
    summary, runs, _ = exit_run
    lines = (runs / "mcp_calls.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert {r["trace_id"] for r in records} >= set(summary["mcp_trace_ids"])
    for record in records:
        assert record["tool"] == "tigergraph__run_installed_query"
        assert record["duration_ms"] > 0 and record["result_bytes"] > 0
        vector = record["parameters"].get("query_vector")
        if vector is not None:
            assert set(vector) == {"vector_dims", "sha256"}


def test_the_server_logged_its_own_tool_calls(exit_run):
    _, runs, _ = exit_run
    text = (runs / "mcp_server_stderr.log").read_text(encoding="utf-8")
    assert text.count("tool call tool=tigergraph__run_installed_query") >= 11


def test_the_saved_package_revalidates(exit_run):
    """The artifact on disk, not only the object in memory, passes validation."""
    from evidence.citations import validate_package
    from evidence.models import EvidencePackage

    _, runs, _ = exit_run
    package = EvidencePackage.model_validate(load(runs, "evidence_package_HHG-019.json"))
    report = validate_package(package)
    assert report.passed, [(c.name, c.failures) for c in report.failed()]


def test_every_saved_claim_resolves_to_ids_or_policy_anchors(exit_run):
    _, runs, _ = exit_run
    package = load(runs, "evidence_package_HHG-019.json")
    registry = set(package["observed_entity_ids"])
    for section in package["sections"].values():
        for item in section:
            assert item["entity_ids"]
            assert set(item["entity_ids"]) <= registry
            assert item["ref"]
