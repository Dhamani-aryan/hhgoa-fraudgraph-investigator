"""The single place this project opens a TigerGraph connection.

Two deployment paths, one interface:

* Savanna / TigerGraph Cloud authenticates with a database secret. pyTigerGraph
  takes it as ``gsqlSecret`` and exchanges it for a short-lived REST++ token.
  The documentation states a username/password pair is not used for Cloud.
* Community Edition and self-managed servers use a username and password.

Credentials are read from the environment and never logged. ``redact`` scrubs
any known secret value out of a string, and every error this module raises is
passed through it, because pyTigerGraph puts request URLs -- which can carry a
token -- into exception messages.

The investigation workflow uses this read-only. The single validated write path
for case memory is added in a later gate and kept separate from it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

#: Anything shorter than this is too generic to blanket-replace in a message.
_MIN_REDACTABLE_LENGTH = 6


class TigerGraphConfigError(RuntimeError):
    """The environment does not describe a usable connection."""


@dataclass(frozen=True)
class TigerGraphConfig:
    host: str
    graphname: str
    tg_cloud: bool
    secret: str = ""
    username: str = ""
    password: str = ""
    api_token: str = ""

    @property
    def secret_values(self) -> tuple[str, ...]:
        """Every value that must never reach a log."""
        return tuple(
            value
            for value in (self.secret, self.password, self.api_token)
            if value and len(value) >= _MIN_REDACTABLE_LENGTH
        )

    def describe(self) -> str:
        """A one-line description safe to print."""
        mode = "Savanna/Cloud (secret)" if self.tg_cloud else "self-managed (user/password)"
        return f"{self.host} graph={self.graphname} auth={mode}"


def load_config(env_path: Path | None = None) -> TigerGraphConfig:
    """Build the connection config from .env and the process environment."""
    env_path = ENV_PATH if env_path is None else env_path
    if env_path.exists():
        load_dotenv(env_path)

    host = os.getenv("TG_HOST", "").strip().rstrip("/")
    graphname = os.getenv("TG_GRAPHNAME", "").strip()
    tg_cloud = os.getenv("TG_TGCLOUD", "true").strip().lower() in {"1", "true", "yes"}

    config = TigerGraphConfig(
        host=host,
        graphname=graphname,
        tg_cloud=tg_cloud,
        secret=os.getenv("TG_SECRET", "").strip(),
        username=os.getenv("TG_USERNAME", "").strip(),
        password=os.getenv("TG_PASSWORD", "").strip(),
        api_token=os.getenv("TG_API_TOKEN", "").strip(),
    )

    missing = []
    if not config.host:
        missing.append("TG_HOST")
    if not config.graphname:
        missing.append("TG_GRAPHNAME")
    if tg_cloud:
        if not config.secret and not config.api_token:
            missing.append("TG_SECRET")
    else:
        if not config.username:
            missing.append("TG_USERNAME")
        if not config.password:
            missing.append("TG_PASSWORD")

    if missing:
        raise TigerGraphConfigError(
            "TigerGraph is not configured. Missing: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill it in; run scripts/bootstrap.py."
        )
    return config


def redact(text: str, config: TigerGraphConfig) -> str:
    """Replace every known secret value in ``text`` with a placeholder."""
    for value in config.secret_values:
        text = text.replace(value, "***REDACTED***")
    return text


def connect(config: TigerGraphConfig | None = None, *, get_token: bool = True):
    """Return an authenticated pyTigerGraph connection.

    Raises ``TigerGraphConfigError`` with a redacted message on failure, so a
    stack trace can never carry the secret into a log or a screenshot.
    """
    from pyTigerGraph import TigerGraphConnection

    config = config or load_config()

    kwargs = {
        "host": config.host,
        "graphname": config.graphname,
        "tgCloud": config.tg_cloud,
    }
    if config.tg_cloud:
        kwargs["gsqlSecret"] = config.secret
    else:
        kwargs["username"] = config.username
        kwargs["password"] = config.password
    if config.api_token:
        kwargs["apiToken"] = config.api_token

    try:
        connection = TigerGraphConnection(**kwargs)
        if get_token and not config.api_token:
            # On Cloud the secret is the credential the token is minted from.
            secret = config.secret if config.tg_cloud else None
            connection.getToken(secret)
    except Exception as error:  # noqa: BLE001 - re-raised redacted below
        raise TigerGraphConfigError(
            f"could not connect to TigerGraph at {config.host}: {redact(str(error), config)}"
        ) from None
    return connection
