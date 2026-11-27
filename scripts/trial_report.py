#!/usr/bin/env python3
"""Read-only equal-maturity experiment report; requires installed youtube-channel-mcp."""
import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "experiments/two-a-day-2026-11-27/plan.json"


def maturity_window(published_at):
    publication = datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(TZ).date()
    return publication, publication + timedelta(days=1), publication + timedelta(days=7)


def direction(video, ledger=None):
    for slot in (ledger or {}).values():
        if slot.get("url", "").rsplit("/", 1)[-1] == video["id"]:
            return slot["direction"], "internal_upload_ledger"
    description = video.get("snippet", {}).get("description", "")
    # Recognize only the generator's explicit teaching-description format.
    if description.startswith("تعلم 5 كلمات انجليزي مع الترجمة العربية!"):
        return "english", "existing_generator_description"
    if description.startswith("Learn 7 everyday Egyptian Arabic words"):
        return "arabic", "existing_generator_description"
    return "unknown", "no_explicit_direction_evidence"


def summarize(rows):
    totals = {metric: sum(row.get(metric, 0) for row in rows) for metric in ("views", "engagedViews", "estimatedMinutesWatched", "subscribersGained", "subscribersLost")}
    engaged = totals["engagedViews"]
    totals["net_video_attributed_subscribers"] = totals["subscribersGained"] - totals["subscribersLost"]
    totals["gross_subscribers_per_1000_engaged_views"] = 1000 * totals["subscribersGained"] / engaged if engaged else None
    totals["mature_video_count"] = len(rows)
    totals["median_views_per_video"] = statistics.median(r["views"] for r in rows) if rows else None
    totals["median_engaged_views_per_video"] = statistics.median(r["engagedViews"] for r in rows) if rows else None
    percentages = [r["averageViewPercentage"] for r in rows if r.get("engagedViews", 0) > 0]
    totals["median_average_view_percentage_nonzero_engaged_videos"] = statistics.median(percentages) if percentages else None
    totals["videos_with_retention_average"] = len(percentages)
    return totals


def build_report(api, videos, plan, latest, ledger=None):
    cohorts = {key: {"videos": [], "pending": [], "unavailable": []} for key in ("baseline", "trial")}
    intervals = {"baseline": (plan["baseline_publication_start"], plan["baseline_publication_end"]), "trial": (plan["start_date"], plan["end_date"])}
    for video in videos:
        if video.get("status", {}).get("privacyStatus") != "public":
            continue
        published_at = video.get("snippet", {}).get("publishedAt")
        if not published_at:
            continue
        publication, start, end = maturity_window(published_at)
        label, evidence = direction(video, ledger)
        for cohort, (first, last) in intervals.items():
            if not date.fromisoformat(first) <= publication <= date.fromisoformat(last):
                continue
            info = {"video": video["id"], "title": video["snippet"].get("title"), "direction": label, "direction_evidence": evidence, "publication_day_pacific": str(publication), "maturity_start": str(start), "maturity_end": str(end)}
            if latest is None or end > latest:
                cohorts[cohort]["pending"].append(info)
                continue
            try:
                result = api.report(str(start), str(end), dimensions="creatorContentType", filters="video==" + video["id"])
                shorts = [row for row in result["rows"] if str(row.get("creatorContentType", "")).lower() == "shorts"]
                if not shorts:
                    cohorts[cohort]["unavailable"].append({**info, "reason": "No Shorts report row; not assumed zero."})
                    continue
                # Single video/content type yields one row with provider aggregates.
                cohorts[cohort]["videos"].append({**info, **shorts[0]})
            except ValueError as error:
                cohorts[cohort]["unavailable"].append({**info, "reason": str(error)})
    for cohort, data in cohorts.items():
        data["all_directions"] = summarize(data["videos"])
        data["by_direction"] = {label: summarize([r for r in data["videos"] if r["direction"] == label]) for label in ("english", "arabic", "unknown")}
        first, last = intervals[cohort]
        eligible_end = min(date.fromisoformat(last), latest) if latest else None
        if eligible_end and eligible_end >= date.fromisoformat(first):
            daily = api.summary(first, str(eligible_end))
            data["daily_channel"] = daily
            days = len(daily["rows"])
            aggregate = (daily.get("aggregate_through_latest_returned_day") or {}).get("rows", [])
            totals = aggregate[0] if aggregate else {}
            data["channel_returned_days"] = days
            data["channel_engaged_views_per_returned_day"] = totals.get("engagedViews", 0) / days if days and totals else None
            data["channel_net_subscribers_per_returned_day"] = (totals.get("subscribersGained", 0) - totals.get("subscribersLost", 0)) / days if days and totals else None
        else:
            data["daily_channel"] = None
    return {"latest_returned_analytics_day": str(latest) if latest else None, "maturity_definition": plan["maturity_window"], "cohorts": cohorts, "caveats": ["Compare matched directions and equal maturity; missing rows remain unavailable, never zero.", "Per-video subscriber conversion uses watch-page-attributed gains divided by engaged views, not channel-wide subscriber growth.", "Typical retention is the median of per-video averageViewPercentage for videos with engaged views; this is not a pooled audience-retention curve.", "Daily channel metrics include all channel content; the trial changes direction mix and content. This is an observational experiment, not a causal frequency test.", "Two uploads/day already occurred before trial; the change is one English plus one Egyptian Arabic, not doubled successful posting volume."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(PLAN.parent / "report.json"))
    parser.add_argument("--ledger", default=str(PLAN.parent / "uploads.json"), help="Use a freshly fetched deployed upload ledger when the local checkout is stale.")
    args = parser.parse_args()
    from youtube_channel_mcp.server import client
    api = client()
    plan = json.loads(PLAN.read_text())
    if api.channel()["id"] != plan["channel_id"]:
        raise SystemExit("Wrong authorized channel; no report generated.")
    today = datetime.now(TZ).date()
    probe = api.summary(str(today - timedelta(days=14)), str(today - timedelta(days=1)))
    latest = date.fromisoformat(probe["latest_returned_day"]) if probe["latest_returned_day"] else None
    videos, token = [], None
    for _ in range(100):
        page = api.videos(token)
        videos.extend(page["videos"])
        token = page["next_page_token"]
        if not token:
            break
    ledger_path = Path(args.ledger)
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    result = build_report(api, videos, plan, latest, ledger)
    result.update(channel_id=plan["channel_id"], generated_at=datetime.now(TZ).isoformat(), inventory_count=len(videos), inventory_truncated=bool(token))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": args.output, "latest_day": result["latest_returned_analytics_day"], "cohorts": {key: {"mature": len(value["videos"]), "pending": len(value["pending"]), "unavailable": len(value["unavailable"])} for key, value in result["cohorts"].items()}}))


if __name__ == "__main__":
    main()
