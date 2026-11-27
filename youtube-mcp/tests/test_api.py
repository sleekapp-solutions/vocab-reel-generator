from unittest.mock import MagicMock
import json
import pytest
from youtube_channel_mcp.api import YouTube, dates, language, execute
from youtube_channel_mcp.auth import credentials, save_token

VID = "abcdefghijk"
OTHER = "ABCDEFGHIJK"


def response(rows, names):
    return {"columnHeaders": [{"name": n} for n in names], "rows": rows}


def service():
    data, analytics = MagicMock(), MagicMock()
    data.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": "UCowner", "contentDetails": {"relatedPlaylists": {"uploads": "UUuploads"}}}]}
    data.videos.return_value.list.return_value.execute.return_value = {"items": []}
    return YouTube(data, analytics)


def test_dates():
    dates("2026-01-01", "2026-02-01")
    for start, end in [("2026-02-30", "2026-03-01"), ("2026-02-01", "2026-01-01"), ("20260101", "2026-02-01")]:
        with pytest.raises(ValueError):
            dates(start, end)


def test_language_does_not_guess_titles():
    assert language({"title": "Learn Arabic العربية", "defaultLanguage": "ar"}, VID)["language"] == "unknown"
    assert language({"defaultAudioLanguage": "ar-EG"}, VID)["language"] == "ar"


def test_language_mapping_overrides_audio(tmp_path, monkeypatch):
    path = tmp_path / "languages.json"
    path.write_text(json.dumps({VID: "en"}))
    monkeypatch.setenv("YOUTUBE_MCP_LANGUAGE_MAP", str(path))
    assert language({"defaultAudioLanguage": "ar"}, VID) == {"language": "en", "evidence": "user_mapping"}


def test_top_shorts_filters_before_ranking_and_reports_truncation():
    api = service()
    rows = [[VID, 10]] + [[OTHER, 1]] * 199
    api.analytics.reports.return_value.query.return_value.execute.return_value = response(rows, ["video", "views"])
    result = api.top_shorts("2026-01-01", "2026-01-31", 1)
    assert result["rows"][0]["video"] == VID
    assert result["potentially_truncated"] is True
    args = api.analytics.reports.return_value.query.call_args.kwargs
    assert args["dimensions"] == "video"
    assert args["filters"] == "creatorContentType==shorts"
    assert result["rows"][0]["creatorContentType"] == "shorts"


def test_compare_requeries_union_in_both_periods():
    api = service()
    api.top_shorts = MagicMock(side_effect=[{"rows": [{"video": VID}]}, {"rows": [{"video": OTHER}]}])
    api.report = MagicMock(return_value={"rows": [{"video": VID, "creatorContentType": "shorts"}]})
    result = api.compare_shorts("2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28")
    assert result["same_video_cohort"] == [VID, OTHER]
    assert all(call.kwargs["filters"] == f"video=={VID},{OTHER}" for call in api.report.call_args_list)
    assert result["cohort_periods"][0]["rows"][0]["video"] == VID


def test_inventory_pagination_and_lifetime_label():
    api = service()
    api.data.playlistItems.return_value.list.return_value.execute.return_value = {"items": [{"contentDetails": {"videoId": VID}}], "nextPageToken": "next"}
    result = api.videos("cursor", 10)
    assert result["next_page_token"] == "next"
    assert "lifetime" in result["statistics_period"]
    assert api.data.playlistItems.return_value.list.call_args.kwargs["pageToken"] == "cursor"


def test_language_totals_unknowns_and_truncation():
    api = service()
    api.videos = MagicMock(return_value={"videos": [{"id": VID, "language_classification": {"language": "unknown"}}], "next_page_token": "more"})
    api.report = MagicMock(return_value={"rows": [{"video": VID, "creatorContentType": "shorts", "views": 7, "subscribersGained": 2, "subscribersLost": 1}]})
    result = api.language_performance("2026-01-01", "2026-01-31", 1)
    assert result["inventory_truncated"]
    assert result["buckets"]["unknown"]["views"] == 7
    assert result["buckets"]["unknown"]["net_subscribers"] == 1
    assert result["buckets"]["en"]["returned_video_count"] == 0


def test_retention_single_video_and_empty_rows():
    api = service()
    api.analytics.reports.return_value.query.return_value.execute.return_value = {}
    assert api.retention(VID, "2026-01-01", "2026-01-31")["rows"] == []
    assert api.analytics.reports.return_value.query.call_args.kwargs["filters"] == "video==" + VID
    with pytest.raises(ValueError):
        api.retention(VID + "," + OTHER, "2026-01-01", "2026-01-31")


def test_summary_uses_google_aggregate_and_marks_freshness():
    api = service()
    api.report = MagicMock(side_effect=[
        {"rows": [{"day": "2026-01-01", "estimatedMinutesWatched": 1}, {"day": "2026-01-02", "estimatedMinutesWatched": 1}]},
        {"rows": [{"estimatedMinutesWatched": 3, "averageViewDuration": 17}]},
    ])
    result = api.summary("2026-01-01", "2026-01-03")
    assert result["latest_returned_day"] == "2026-01-02"
    assert result["requested_end_day_returned"] is False
    assert result["aggregate_through_latest_returned_day"]["rows"][0]["estimatedMinutesWatched"] == 3
    assert api.report.call_args_list[1].args == ("2026-01-01", "2026-01-02")


def test_summary_does_not_fabricate_totals_for_empty_report():
    api = service()
    api.report = MagicMock(return_value={"rows": []})
    result = api.summary("2026-01-01", "2026-01-03")
    assert result["aggregate_through_latest_returned_day"] is None
    assert api.report.call_count == 1


def test_comments_and_replies_paginate():
    api = service()
    api.data.commentThreads.return_value.list.return_value.execute.return_value = {"items": [], "nextPageToken": "more"}
    assert api.comments(VID)["next_page_token"] == "more"
    api.replies("comment", "cursor")
    assert api.data.comments.return_value.list.call_args.kwargs["pageToken"] == "cursor"


def scheduled_api(privacy="private", owner="UCowner"):
    api = service()
    api.data.videos.return_value.list.return_value.execute.return_value = {"items": [{"snippet": {"channelId": owner}, "status": {"privacyStatus": privacy, "license": "youtube", "embeddable": False, "selfDeclaredMadeForKids": False, "uploadStatus": "processed"}}]}
    return api


def test_schedule_preview_does_not_write_and_preserves_status():
    api = scheduled_api()
    result = api.schedule(VID, "2099-01-01T12:00:00Z")
    assert result["dry_run"]
    assert result["proposed_update"]["status"]["embeddable"] is False
    assert "uploadStatus" not in result["proposed_update"]["status"]
    api.data.videos.return_value.update.assert_not_called()


def test_schedule_confirm_only_status_update():
    api = scheduled_api()
    api.schedule(VID, "2099-01-01T12:00:00Z", True)
    assert api.data.videos.return_value.update.call_args.kwargs["part"] == "status"


@pytest.mark.parametrize("privacy,owner", [("public", "UCowner"), ("private", "UCsomeone")])
def test_schedule_rejects_wrong_owner_or_public(privacy, owner):
    api = scheduled_api(privacy, owner)
    with pytest.raises(ValueError):
        api.schedule(VID, "2099-01-01T12:00:00Z", True)
    api.data.videos.return_value.update.assert_not_called()


@pytest.mark.parametrize("timestamp", ["2020-01-01T00:00:00Z", "2099-01-01T00:00:00"])
def test_schedule_rejects_past_or_naive(timestamp):
    with pytest.raises(ValueError):
        scheduled_api().schedule(VID, timestamp)


def test_api_errors_redact_response():
    from googleapiclient.errors import HttpError
    import httplib2
    request = MagicMock()
    request.execute.side_effect = HttpError(httplib2.Response({"status": 403}), b'{"error":{"message":"SECRET","errors":[{"reason":"accessNotConfigured"}]}}', uri="https://example.com/SECRET")
    with pytest.raises(ValueError) as caught:
        execute(request)
    assert "SECRET" not in str(caught.value)
    assert "accessNotConfigured" in str(caught.value)


def test_dedicated_token_rejects_upload_only(tmp_path, monkeypatch):
    path = tmp_path / "read-token.json"
    path.write_text(json.dumps({"scopes": ["https://www.googleapis.com/auth/youtube.upload"], "token": "SECRET"}))
    monkeypatch.setenv("YOUTUBE_MCP_TOKEN", str(path))
    before = path.read_bytes()
    with pytest.raises(ValueError) as caught:
        credentials()
    assert "SECRET" not in str(caught.value)
    assert path.read_bytes() == before


def test_token_saved_private(tmp_path):
    path = tmp_path / "read-token.json"
    save_token(path, "secret")
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("filename", ["token.json", "client_secrets.json"])
def test_legacy_paths_are_protected(tmp_path, monkeypatch, filename):
    from youtube_channel_mcp.auth import token_path
    monkeypatch.setenv("YOUTUBE_MCP_TOKEN", str(tmp_path / filename))
    with pytest.raises(ValueError, match="protected"):
        token_path()


def test_read_write_paths_cannot_collide(tmp_path, monkeypatch):
    from youtube_channel_mcp.auth import token_path
    path = str(tmp_path / "mcp-token.json")
    monkeypatch.setenv("YOUTUBE_MCP_TOKEN", path)
    monkeypatch.setenv("YOUTUBE_MCP_WRITE_TOKEN", path)
    with pytest.raises(ValueError, match="different"):
        token_path(True)
