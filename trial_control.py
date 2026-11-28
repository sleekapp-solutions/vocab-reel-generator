"""Permanent daily posting gate and bounded fresh-content window."""
import argparse
import csv
from datetime import date, datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PLAN = ROOT / "experiments/two-a-day-2026-11-27/plan.json"


def load_plan():
    return json.loads(PLAN.read_text())


def trial_day(plan, today):
    start, end = date.fromisoformat(plan["start_date"]), date.fromisoformat(plan["end_date"])
    return (today - start).days if start <= today <= end else None


def schedule_decision(direction, cron, today, manual=False, upload=False):
    plan = load_plan()
    day = trial_day(plan, today) if plan.get("activated") else None
    if manual:
        return {"run": not upload, "trial": day is not None, "day": day, "reason": "Manual previews are allowed; scheduled jobs own the two permanent daily upload slots."}
    expected = {"english": "17 9 * * *", "arabic": "23 13 * * *"}[direction]
    return {"run": bool(plan.get("activated")) and cron == expected, "trial": day is not None, "day": day, "reason": "One slot per direction permanently; only the fresh-content measurement window expires."}


def assert_slot_available(direction, today, ledger_path):
    path = Path(ledger_path)
    ledger = json.loads(path.read_text()) if path.exists() else {}
    if f"{today}:{direction}" in ledger:
        raise ValueError("This daily slot was already uploaded; refusing a duplicate.")


def batch_for_day(direction, today, ledger_path=None):
    plan = load_plan()
    day = trial_day(plan, today)
    if day is None:
        raise ValueError("Trial content is unavailable outside the fixed trial dates.")
    size = 7 if direction == "arabic" else 5
    path = PLAN.parent / f"{direction}-trial.csv"
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 14 * size:
        raise ValueError("Trial content is incomplete; refusing to wrap or publish partial content.")
    selected = rows[day * size:(day + 1) * size]
    if ledger_path:
        assert_slot_available(direction, today, ledger_path)
    if any(not r.get("arabic") or not r.get("english") or (direction == "arabic" and not r.get("pronunciation")) for r in selected):
        raise ValueError("Incomplete trial vocabulary; refusing upload.")
    return [(r["arabic"], r["english"], r.get("pronunciation", "")) for r in selected]


def record_upload(direction, today, url, path, source="trial", presentation=None):
    path = Path(path)
    ledger = json.loads(path.read_text()) if path.exists() else {}
    key = f"{today}:{direction}"
    if key in ledger:
        raise ValueError("Daily slot already recorded.")
    ledger[key] = {"url": url, "published_at": datetime.now(ZoneInfo("UTC")).isoformat(), "direction": direction, "source": source}
    if presentation:
        ledger[key]["presentation"] = presentation
    path.write_text(json.dumps(ledger, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", choices=["english", "arabic"], required=True)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    decision = schedule_decision(args.direction, os.environ.get("EVENT_SCHEDULE", ""), today, manual, os.environ.get("MANUAL_UPLOAD") == "true")
    # Manual dry runs select today's trial queue but never consume it.
    ledger = PLAN.parent / "uploads.json"
    if not manual and decision["run"] and f"{today}:{args.direction}" in json.loads(ledger.read_text() if ledger.exists() else "{}"):
        decision.update(run=False, reason="Daily slot already recorded; no duplicate upload.")
    output = {"run": str(decision["run"]).lower(), "trial": str(decision["trial"]).lower(), "trial_date": str(today)}
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in output.items()))
    print(json.dumps({**output, "reason": decision["reason"]}))


if __name__ == "__main__":
    main()
