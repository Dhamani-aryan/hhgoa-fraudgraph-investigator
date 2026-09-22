"""Validate every answer file in cases/ and write the validation reports.

Writes a machine-readable report to ``runs/validation_report.json`` and prints
a human-readable summary. Exits non-zero if any case fails, if a case is
missing, or if an unexpected file is present.

This is the submission validation gate. Until the agent exists, running it on
an empty cases/ directory correctly reports twenty missing cases.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validation.answer_validator import validate_directory  # noqa: E402
from validation.dataset_ids import load_dataset_index  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = PROJECT_ROOT / "cases"
REPORT_PATH = PROJECT_ROOT / "runs" / "validation_report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--refresh-index",
        action="store_true",
        help="rebuild the dataset identifier cache from data/raw",
    )
    args = parser.parse_args()

    index = load_dataset_index(refresh=args.refresh_index)
    report = validate_directory(args.cases_dir, index)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"cases directory : {report['cases_dir']}")
    print(f"expected cases  : {report['expected_case_count']}")
    print(f"files found     : {report['files_found']}")
    if report["missing_case_ids"]:
        print(f"missing         : {', '.join(report['missing_case_ids'])}")
    if report["unexpected_case_ids"]:
        print(f"unexpected      : {', '.join(report['unexpected_case_ids'])}")

    for item in report["reports"]:
        failed = [rule["rule_id"] for rule in item["rules"] if rule["outcome"] == "failed"]
        skipped = [rule["rule_id"] for rule in item["rules"] if rule["outcome"] == "skipped"]
        if not item["schema_valid"]:
            status = "SCHEMA FAIL"
        elif failed:
            status = "RULE FAIL"
        elif skipped:
            status = "VALID (unchecked rules)"
        else:
            status = "VALID"
        print(f"  {item['case_id'] or item['path']:<12} {status}")
        for message in item["schema_errors"]:
            print(f"      schema: {message}")
        for rule in item["rules"]:
            if rule["outcome"] == "failed":
                for failure in rule["failures"]:
                    print(f"      {rule['rule_id']}: {failure}")
        if skipped:
            print(f"      unchecked without a run trace: {', '.join(skipped)}")

    print(f"\nwrote {REPORT_PATH}")
    if report["all_ready_for_submission"]:
        print("Result: all cases valid and fully checked.")
        return 0
    if report["all_valid"]:
        print("Result: all cases valid, but some rules could not be checked without a run trace.")
        return 1
    print("Result: FAILED.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
