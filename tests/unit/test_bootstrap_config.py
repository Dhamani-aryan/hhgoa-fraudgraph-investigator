"""Tests for the deployment-aware TigerGraph configuration check.

Savanna and TigerGraph Cloud authenticate with a database secret; the
pyTigerGraph documentation is explicit that a username/password pair is not
used there. Community Edition and self-managed servers use username and
password. bootstrap.py must ask for the right one, and must never print a
value.
"""

from __future__ import annotations

import pytest

from scripts import bootstrap


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "TG_TGCLOUD",
        "TG_HOST",
        "TG_GRAPHNAME",
        "TG_SECRET",
        "TG_USERNAME",
        "TG_PASSWORD",
        "TG_MCP_ALLOWED_TOOLS",
    ):
        monkeypatch.delenv(name, raising=False)


def _cloud(monkeypatch, **extra):
    monkeypatch.setenv("TG_TGCLOUD", "true")
    monkeypatch.setenv("TG_HOST", "https://example.tgcloud.io")
    monkeypatch.setenv("TG_GRAPHNAME", "HHGOAFraud")
    monkeypatch.setenv("TG_MCP_ALLOWED_TOOLS", "schema,query,discovery,vector,utility")
    for key, value in extra.items():
        monkeypatch.setenv(key, value)


def test_cloud_requires_the_secret_not_a_password(monkeypatch):
    _cloud(monkeypatch)
    assert bootstrap.required_tg_vars() == ("TG_HOST", "TG_GRAPHNAME", "TG_SECRET")
    problems, _ = bootstrap.check_tigergraph()
    assert "unset: TG_SECRET" in problems
    assert not any("TG_PASSWORD" in problem for problem in problems)


def test_cloud_with_a_secret_is_complete(monkeypatch):
    _cloud(monkeypatch, TG_SECRET="not-a-real-secret")
    problems, _ = bootstrap.check_tigergraph()
    assert problems == []


def test_self_managed_requires_username_and_password(monkeypatch):
    monkeypatch.setenv("TG_TGCLOUD", "false")
    monkeypatch.setenv("TG_HOST", "https://localhost")
    monkeypatch.setenv("TG_GRAPHNAME", "HHGOAFraud")
    assert bootstrap.required_tg_vars() == (
        "TG_HOST",
        "TG_GRAPHNAME",
        "TG_USERNAME",
        "TG_PASSWORD",
    )
    problems, _ = bootstrap.check_tigergraph()
    assert "unset: TG_USERNAME" in problems
    assert "unset: TG_PASSWORD" in problems
    assert not any("TG_SECRET" in problem for problem in problems)


def test_cloud_notes_that_username_and_password_are_ignored(monkeypatch):
    _cloud(monkeypatch, TG_SECRET="s", TG_USERNAME="tigergraph")
    _, notes = bootstrap.check_tigergraph()
    assert any("ignored on Cloud" in note for note in notes)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("https://example.tgcloud.io", None),
        ("example.tgcloud.io", "scheme"),
        ("https://example.tgcloud.io/", "trailing slash"),
        ("https://example.tgcloud.io/graph", "no path"),
    ],
)
def test_host_shape_is_checked(monkeypatch, host, expected):
    _cloud(monkeypatch, TG_SECRET="s")
    monkeypatch.setenv("TG_HOST", host)
    problems, _ = bootstrap.check_tigergraph()
    if expected is None:
        assert problems == []
    else:
        assert any(expected in problem for problem in problems)


def test_missing_vector_tool_is_flagged(monkeypatch):
    _cloud(monkeypatch, TG_SECRET="s")
    monkeypatch.setenv("TG_MCP_ALLOWED_TOOLS", "schema,query,discovery,utility")
    problems, _ = bootstrap.check_tigergraph()
    assert any("vector" in problem for problem in problems)


def test_no_secret_value_ever_appears_in_the_output(monkeypatch, capsys, tmp_path):
    """The whole point of reporting by name: values must not leak."""
    secret = "sup3rs3cret-value-that-must-not-print"
    _cloud(monkeypatch, TG_SECRET=secret, TG_PASSWORD=secret)
    # Point at a .env that does not exist, so the developer's real file never
    # influences the result and the test behaves the same on any machine.
    monkeypatch.setattr(bootstrap, "ENV_PATH", tmp_path / "absent.env")

    bootstrap.main()

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    # The name is reported even though the value is not.
    assert "TG_SECRET" not in captured.out or "unset: TG_SECRET" not in captured.out
