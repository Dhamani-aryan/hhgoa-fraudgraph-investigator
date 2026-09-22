"""Verify the local environment, the supplied dataset, and the TigerGraph config.

Read-only. Loads .env so it checks what the project will actually use at
runtime, and reports missing values by name without ever printing one.

Exit code 0 means the dataset is present and ready for the Gate 0 data audit.
The TigerGraph section is reported separately because it is only required from
Gate 1 onward.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"
ENV_PATH = PROJECT_ROOT / ".env"

#: Required whichever deployment is used.
COMMON_TG_VARS = ("TG_HOST", "TG_GRAPHNAME")

#: Savanna and TigerGraph Cloud authenticate with a database secret. The docs
#: are explicit that a username/password pair is not used there; pyTigerGraph
#: takes the secret as gsqlSecret and exchanges it for a token.
CLOUD_TG_VARS = ("TG_SECRET",)

#: Community Edition and self-managed servers use a username and password.
SELF_MANAGED_TG_VARS = ("TG_USERNAME", "TG_PASSWORD")


def load_settings() -> dict:
    with SETTINGS_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def check_raw_files(settings: dict) -> list[str]:
    raw_dir = PROJECT_ROOT / settings["dataset"]["raw_dir"]
    problems = []
    for label, filename in settings["dataset"]["files"].items():
        path = raw_dir / filename
        if not path.exists():
            problems.append(f"missing raw file: {label} -> {path}")
        elif path.stat().st_size == 0:
            problems.append(f"empty raw file: {label} -> {path}")
    return problems


def is_cloud() -> bool:
    return os.getenv("TG_TGCLOUD", "true").strip().lower() in {"1", "true", "yes"}


def required_tg_vars() -> tuple[str, ...]:
    extra = CLOUD_TG_VARS if is_cloud() else SELF_MANAGED_TG_VARS
    return COMMON_TG_VARS + extra


def check_tigergraph() -> tuple[list[str], list[str]]:
    """Return (problems, notes). Never returns or prints a secret value."""
    problems = []
    notes = []

    for name in required_tg_vars():
        if not os.getenv(name, "").strip():
            problems.append(f"unset: {name}")

    host = os.getenv("TG_HOST", "").strip()
    if host:
        if not host.startswith(("http://", "https://")):
            problems.append("TG_HOST must include the scheme, for example https://...")
        if host.endswith("/"):
            problems.append("TG_HOST must not end with a trailing slash")
        if host.count("/") > 2:
            problems.append("TG_HOST must be the origin only, with no path")

    if is_cloud():
        notes.append("deployment: Savanna / TigerGraph Cloud (TG_TGCLOUD=true)")
        notes.append("credential: TG_SECRET, created in the workspace Admin Portal")
        if os.getenv("TG_USERNAME", "").strip() or os.getenv("TG_PASSWORD", "").strip():
            notes.append(
                "TG_USERNAME/TG_PASSWORD are set but ignored on Cloud; Savanna "
                "authenticates with the secret"
            )
    else:
        notes.append("deployment: Community Edition or self-managed (TG_TGCLOUD=false)")
        notes.append("credential: TG_USERNAME and TG_PASSWORD")

    tools = os.getenv("TG_MCP_ALLOWED_TOOLS", "").strip()
    if tools and "vector" not in {item.strip() for item in tools.split(",")}:
        problems.append(
            "TG_MCP_ALLOWED_TOOLS is missing 'vector'; TigerGraph vector retrieval "
            "is a required challenge component"
        )

    return problems, notes


def main() -> int:
    settings = load_settings()

    env_loaded = ENV_PATH.exists()
    if env_loaded:
        load_dotenv(ENV_PATH)

    raw_problems = check_raw_files(settings)
    tg_problems, tg_notes = check_tigergraph()

    print("FraudGraph Investigator bootstrap")
    print(f"project root: {PROJECT_ROOT}")
    print(f"env file    : {'.env loaded' if env_loaded else '.env not found'}")
    print()

    if raw_problems:
        print("Dataset problems:")
        for problem in raw_problems:
            print(f"  - {problem}")
    else:
        print("Dataset: all four supplied files and the dataset README are present.")

    print()
    print("TigerGraph configuration (required from Gate 1 onward):")
    for note in tg_notes:
        print(f"  . {note}")
    if tg_problems:
        for problem in tg_problems:
            print(f"  - {problem}")
    else:
        print("  . all required variables are set")

    print()
    if raw_problems:
        print("Result: NOT READY. Place the supplied files in data/raw/ and rerun.")
        return 1

    interpreter = Path(sys.executable).name
    if tg_problems:
        print(
            "Result: dataset ready for the Gate 0 data audit "
            f"({interpreter} scripts/run_data_audit.py)."
        )
        print("        TigerGraph is not configured yet, so Gate 1 cannot connect.")
        return 0

    print(
        "Result: dataset and TigerGraph both configured. Verify the connection with "
        f"{interpreter} scripts/check_tigergraph.py"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
