"""Opt-in synthetic model-quality observation, never part of default suites."""
import argparse
import json
import os
from pathlib import Path
from uuid import UUID

import httpx

from job_machine.fit.jev import evaluate_payload
from job_machine.fit.models import FitError, FitFact, FitInput
from job_machine.fit.rubric import build_payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Observe Jev on synthetic fixtures only")
    parser.add_argument("--execute", action="store_true", help="Explicitly permit billable synthetic API requests")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "not_run", "reason": "explicit_execute_required"}))
        return 0
    api_key = os.environ.get("TYPESAFE_API_KEY", "")
    if not api_key.strip():
        print(json.dumps({"status": "not_run", "reason": "missing_api_key"}))
        return 1
    fixtures = json.loads((Path(__file__).resolve().parents[1] / "tests/fit/fixtures/quality.json").read_text(encoding="utf-8"))
    failed = False
    with httpx.Client() as client:
        for case in fixtures:
            value = FitInput("synthetic-quality", UUID(int=1), case["job"], tuple(
                FitFact(str(i), fact["text"], fact["status"], "synthetic") for i, fact in enumerate(case["facts"])))
            try:
                result = evaluate_payload(build_payload(value), client=client, api_key=api_key)
                matches = case["expected_min"] <= result.score <= case["expected_max"]
                failed |= not matches
                print(json.dumps({"case": case["id"], "score": result.score,
                    "exploratory_range": [case["expected_min"], case["expected_max"]], "within_range": matches}))
            except FitError as error:
                print(json.dumps({"case": case["id"], "error": error.code}))
                return 1
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
