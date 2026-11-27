"""Bounded experiment selection and scheduler gate. No network or generation imports."""
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
        # Explicit manual uploads during the trial could exceed two per day.
        return {"run": not upload or day is None, "trial": day is not None, "day": day, "reason": "Manual upload disabled during trial; scheduled jobs own the two daily slots."}
    if direction == "arabic":
        return {"run": day is not None, "trial": day is not None, "day": day, "reason": "Arabic runs once/day only inside trial; paused outside trial."}
    return {"run": day is None or cron == "17 9 * * *", "trial": day is not None, "day": day, "reason": "Keep morning English slot during trial; restore both English slots after trial."}


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
    if ledger_path and Path(ledger_path).exists():
        ledger = json.loads(Path(ledger_path).read_text())
        if f"{today}:{direction}" in ledger:
            raise ValueError("This daily trial slot was already uploaded; refusing a duplicate.")
    if any(not r.get("arabic") or not r.get("english") or (direction == "arabic" and not r.get("pronunciation")) for r in selected):
        raise ValueError("Incomplete trial vocabulary; refusing upload.")
    return [(r["arabic"], r["english"], r.get("pronunciation", "")) for r in selected]


def record_upload(direction, today, url, path):
    path = Path(path)
    ledger = json.loads(path.read_text()) if path.exists() else {}
    key = f"{today}:{direction}"
    if key in ledger:
        raise ValueError("Daily trial slot already recorded.")
    ledger[key] = {"url": url, "published_at": datetime.now(ZoneInfo("UTC")).isoformat(), "direction": direction}
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
    if decision["trial"] and decision["run"] and f"{today}:{args.direction}" in json.loads(ledger.read_text() if ledger.exists() else "{}"):
        decision.update(run=False, reason="Daily slot already recorded; no duplicate upload.")
    output = {"run": str(decision["run"]).lower(), "trial": str(decision["trial"]).lower(), "trial_date": str(today)}
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in output.items()))
    print(json.dumps({**output, "reason": decision["reason"]}))


if __name__ == "__main__":
    main()
