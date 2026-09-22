"""Tests for the TigerGraph connection config and its redaction.

These do not touch a server. They cover the two deployment paths and the
guarantee that matters most here: a credential must never reach a log, a stack
trace or a demo screenshot.
"""

from __future__ import annotations

import pytest

from graph.client import (
    TigerGraphConfig,
    TigerGraphConfigError,
    load_config,
    redact,
)

SECRET = "abcd1234efgh5678ijkl9012mnop3456"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in (
        "TG_HOST",
        "TG_GRAPHNAME",
        "TG_TGCLOUD",
        "TG_SECRET",
        "TG_USERNAME",
        "TG_PASSWORD",
        "TG_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    # Never read the developer's real .env during tests.
    monkeypatch.setattr("graph.client.ENV_PATH", tmp_path / "absent.env")


def _set(monkeypatch, **values):
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_cloud_config_uses_the_secret(monkeypatch):
    _set(
        monkeypatch,
        TG_HOST="https://ws.tgcloud.io",
        TG_GRAPHNAME="HHGOAFraud",
        TG_TGCLOUD="true",
        TG_SECRET=SECRET,
    )
    config = load_config()
    assert config.tg_cloud is True
    assert config.secret == SECRET
    assert config.graphname == "HHGOAFraud"


def test_cloud_without_a_secret_is_rejected(monkeypatch):
    _set(
        monkeypatch,
        TG_HOST="https://ws.tgcloud.io",
        TG_GRAPHNAME="HHGOAFraud",
        TG_TGCLOUD="true",
    )
    with pytest.raises(TigerGraphConfigError, match="TG_SECRET"):
        load_config()


def test_cloud_accepts_a_pre_minted_token_instead_of_a_secret(monkeypatch):
    _set(
        monkeypatch,
        TG_HOST="https://ws.tgcloud.io",
        TG_GRAPHNAME="HHGOAFraud",
        TG_TGCLOUD="true",
        TG_API_TOKEN="token-value-here",
    )
    assert load_config().api_token == "token-value-here"


def test_self_managed_requires_username_and_password(monkeypatch):
    _set(
        monkeypatch,
        TG_HOST="https://localhost",
        TG_GRAPHNAME="HHGOAFraud",
        TG_TGCLOUD="false",
    )
    with pytest.raises(TigerGraphConfigError) as error:
        load_config()
    assert "TG_USERNAME" in str(error.value)
    assert "TG_PASSWORD" in str(error.value)


def test_trailing_slash_is_stripped_from_the_host(monkeypatch):
    _set(
        monkeypatch,
        TG_HOST="https://ws.tgcloud.io/",
        TG_GRAPHNAME="HHGOAFraud",
        TG_TGCLOUD="true",
        TG_SECRET=SECRET,
    )
    assert load_config().host == "https://ws.tgcloud.io"


def test_describe_never_includes_the_secret():
    config = TigerGraphConfig(
        host="https://ws.tgcloud.io",
        graphname="HHGOAFraud",
        tg_cloud=True,
        secret=SECRET,
    )
    described = config.describe()
    assert SECRET not in described
    assert "Savanna/Cloud" in described


def test_redact_scrubs_every_credential():
    config = TigerGraphConfig(
        host="https://ws.tgcloud.io",
        graphname="HHGOAFraud",
        tg_cloud=True,
        secret=SECRET,
        password="a-long-password",
        api_token="a-long-api-token",
    )
    message = (
        f"GET https://ws.tgcloud.io/requesttoken?secret={SECRET} failed; "
        f"password a-long-password; token a-long-api-token"
    )
    cleaned = redact(message, config)
    assert SECRET not in cleaned
    assert "a-long-password" not in cleaned
    assert "a-long-api-token" not in cleaned
    assert cleaned.count("***REDACTED***") == 3


def test_redact_ignores_trivially_short_values():
    """Blanket-replacing a short value would corrupt unrelated text."""
    config = TigerGraphConfig(
        host="https://ws.tgcloud.io",
        graphname="HHGOAFraud",
        tg_cloud=True,
        secret="ab",
    )
    assert config.secret_values == ()
    assert redact("a table of absolute values", config) == "a table of absolute values"


def test_connect_failure_message_is_redacted(monkeypatch):
    """A driver error carrying the secret must not escape unredacted."""
    _set(
        monkeypatch,
        TG_HOST="https://ws.tgcloud.io",
        TG_GRAPHNAME="HHGOAFraud",
        TG_TGCLOUD="true",
        TG_SECRET=SECRET,
    )
    import graph.client as client_module

    class Boom:
        def __init__(self, **kwargs):
            raise RuntimeError(f"auth failed for secret={SECRET}")

    fake = type("FakeModule", (), {"TigerGraphConnection": Boom})
    monkeypatch.setitem(__import__("sys").modules, "pyTigerGraph", fake)

    with pytest.raises(TigerGraphConfigError) as error:
        client_module.connect()

    assert SECRET not in str(error.value)
    assert "***REDACTED***" in str(error.value)
