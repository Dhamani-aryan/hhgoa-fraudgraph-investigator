"""Verify the local environment and supplied dataset before any other command.

Reports missing configuration and missing raw files without printing secret values.
Exit code 0 means the project is ready for the Gate 0 data audit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

REQUIRED_ENV_VARS = (
    "TG_HOST",
    "TG_GRAPHNAME",
    "TG_USERNAME",
    "TG_PASSWORD",
)


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


def check_env() -> list[str]:
    """Report which required variables are unset without revealing any value."""
    import os

    return [
        f"unset environment variable: {name}" for name in REQUIRED_ENV_VARS if not os.getenv(name)
    ]


def main() -> int:
    settings = load_settings()

    raw_problems = check_raw_files(settings)
    env_problems = check_env()

    print("FraudGraph Investigator bootstrap")
    print(f"project root: {PROJECT_ROOT}")
    print()

    if raw_problems:
        print("Dataset problems:")
        for problem in raw_problems:
            print(f"  - {problem}")
    else:
        print("Dataset: all four supplied files and the dataset README are present.")

    print()
    if env_problems:
        print("TigerGraph configuration not yet supplied (required from Gate 1 onward):")
        for problem in env_problems:
            print(f"  - {problem}")
    else:
        print("TigerGraph configuration: all required variables are set.")

    print()
    if raw_problems:
        print("Result: NOT READY. Place the supplied files in data/raw/ and rerun.")
        return 1

    print("Result: ready for the Gate 0 data audit (python scripts/run_data_audit.py).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
