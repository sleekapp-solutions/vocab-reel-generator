# YouTube Channel MCP

A reusable Python MCP stdio server calling Google's YouTube Data API v3 and YouTube Analytics API v2 directly. No vidIQ, external analytics provider, API key, video generator imports, or intermediary data service. It can be copied/installed separately from VocabReelGenerator. The existing generator, `client_secrets.json`, and upload-only `token.json` are not modified.

## Installed here

The isolated Python 3.12 environment is `youtube-mcp/.venv`; the package is installed editable. Run checks from the repository root:

```sh
youtube-mcp/.venv/bin/pytest -q youtube-mcp/tests
```

For a fresh installation with Python 3.10+:

```sh
python3.12 -m venv youtube-mcp/.venv
youtube-mcp/.venv/bin/pip install -e 'youtube-mcp[test]'
```

The official MCP Python SDK is constrained to its supported v1 maintenance API (`mcp>=1.28,<2`) to keep FastMCP/stdio behavior stable. Installed versions can be captured with `pip freeze`; `requirements-lock.txt` records the tested environment.

## One-time connection

1. In the Google Cloud project associated with your Desktop OAuth client, enable **YouTube Data API v3** and **YouTube Analytics API**. Existing upload access does not prove Analytics is enabled. The user enabled these APIs during connection setup; this implementation did not change Cloud settings itself.
2. Configure the Google Auth Platform consent audience. If the OAuth app is external and in Testing, add the Google account as a test user. Use a **Desktop app** OAuth client. The existing `client_secrets.json` can be used if it is a Desktop client; do not paste its contents into chat. External Testing-mode refresh tokens can expire after seven days for these scopes; use appropriate production/verification setup for durable usage. Google account/channel and app policy restrictions can still require attention.
3. Run this once in a local terminal. The command opens Google's consent page and waits up to five minutes for a loopback callback. **You must sign in and grant consent yourself**, selecting the intended YouTube/Brand channel.

```sh
cd /Users/mina/Desktop/VocabReelGenerator
youtube-mcp/.venv/bin/youtube-channel-auth \
  --client-secrets /Users/mina/Desktop/VocabReelGenerator/client_secrets.json
```

It requests `youtube.readonly` and `yt-analytics.readonly`. Tokens are saved separately at `~/.config/youtube-channel-mcp/read-token.json` with mode 0600 and atomic replacement. The MCP never starts interactive OAuth itself. It refreshes its own token as needed. It neither loads nor upgrades the uploader's `token.json`. To use multiple channels, create distinct MCP token files using `YOUTUBE_MCP_TOKEN` during both authorization and server startup, and register separate server names.

4. Register in Codex with the following command, or merge `codex-config.example.toml` into `~/.codex/config.toml` (or trusted project `.codex/config.toml`). Do not replace an existing config file. This installation is now registered globally as `youtube_channel` with writes disabled. The command below is for fresh installations; reconnect Codex to discover it.

```sh
codex mcp add youtube_channel \
  --env YOUTUBE_MCP_ENABLE_WRITES=0 -- \
  /Users/mina/Desktop/VocabReelGenerator/youtube-mcp/.venv/bin/youtube-channel-mcp
```

The example config includes a 180-second tool timeout for bounded multi-page reports. CLI registration uses Codex defaults; add `tool_timeout_sec = 180` under the new server table if large reports time out. Restart/reconnect Codex so the server tools are discovered. This local stdio integration uses its own Google OAuth; `codex mcp login` is not the authorization command for it.

5. Ask: **“Use YouTube Channel to check connection_status and identify my authorized channel, then retrieve channel_metrics for 2026-11-01 through 2026-11-25.”** Only a successful `authorized_channel` verifies live Data API access; a successful metrics request separately verifies Analytics. Local token presence alone is never called a live connection. Live Data API and Analytics access were verified after user consent and API enablement. The November 19–25, 2026 daily request returned rows through November 24 at verification time; later availability can change.

## Conversational use

After connection, ask Codex naturally:

- “Compare my top 10 Shorts from November 1–12 with November 13–24, 2026. Which gained subscribers?”
- “Compare English and Arabic Shorts this month; show unknown classifications and coverage limits.”
- “Inspect audience retention and the latest comments on these three videos, then propose next week's content experiments.”
- “Show my scheduled uploads.” (`list_videos` returns privacy and `publishAt` status.)

The `channel_review` MCP prompt provides a reusable channel-review workflow. This is a tool integration for an MCP-capable assistant, not a separate autonomous chat app, scheduled monitor, or replacement for all of YouTube Studio.

## Tools and interpretation

| Tool | Behavior |
| --- | --- |
| `connection_status` | Local setup check, no token data or network request |
| `authorized_channel` | Live channel identity, upload playlist and lifetime stats |
| `list_videos` | Upload inventory with cursor pagination, metadata/status and lifetime stats |
| `channel_metrics` | Daily metrics plus Google aggregate through the latest returned day, with explicit end-day coverage |
| `top_shorts` | Rank by views, watch minutes or gained subscribers; Google content-type classification |
| `compare_shorts` | Top lists and the same union of videos queried in both date ranges |
| `language_performance` | Sum additive metrics by evidence-backed language; inventory limit/unknowns disclosed |
| `audience_retention` | Single-video elapsed-time watch ratio and relative retention |
| `list_comments` | Paginated channel/video threads, including a possibly incomplete reply subset |
| `comment_replies` | Paginated full reply retrieval for a top-level comment ID |
| `schedule_private_video` | Optional write tool; absent by default, dry run by default |

Dates are inclusive YouTube Analytics Pacific dates, not UTC. Requested end dates may exceed the latest fully processed report day. Unavailable/empty rows are not filled with fabricated zeroes. Lifetime Data API statistics must not be compared as date-range analytics. `engagedViews` is returned separately from `views` because Shorts counting definitions differ. Retention is not guaranteed for every video/date range; watch ratios can exceed 1 due to repeats. Subscriber metrics filtered by video reflect gains/losses attributed to the video's watch page and may not equal channel-wide totals.

`top_shorts` applies the live-verified Analytics filter `creatorContentType==shorts` before ranking and returns up to **200 ranked Shorts**. It returns the scanned count and truncation flag. The live API returns lowercase content-type values; comparisons accept either case. Combining unfiltered `video,creatorContentType` is rejected by the live API, so that combination is used only with an explicit video-ID filter for cohort/language reports. `compare_shorts` requeries the union of both top lists in both periods, rather than treating absence from a top list as zero. Compare equivalent period lengths and account for video age. Full historical rankings beyond the top cap are not promised.

`language_performance` scans at most 10 inventory pages (500 videos) by default; callers can set 1–100 pages. It batches Analytics requests for the enumerated videos, reports inventory truncation, and sums only additive metrics. It does not average averages. The channel summary fetches its period aggregate directly from Google rather than summing rounded daily watch minutes; this preserves Google's aggregate duration and percentage metrics. Deleted/inaccessible inventory and report availability can limit coverage. Page scans consume quota and can take time.

Language classification uses an optional video-ID map first, otherwise `snippet.defaultAudioLanguage` (`en`/`ar` including regional variants). Other declared audio languages become `other`; missing evidence becomes `unknown`. `defaultLanguage` is returned only as metadata context, never treated as proof of audio language. Titles, scripts, Unicode, hashtags, duration and the generator's current state are never used to guess. Audio language is not necessarily the language being taught, particularly for bilingual vocabulary reels. For that distinction create a mapping after reviewing the content:

```json
{"abcdefghijk": "en", "ABCDEFGHIJK": "ar"}
```

Set `YOUTUBE_MCP_LANGUAGE_MAP` to its absolute path in the server environment. Values are `en`, `ar`, or `unknown`; map semantics should be agreed with the assistant before drawing conclusions. Mapping is a local read-only input, not a change to YouTube metadata.

## Optional scheduling permission

Read-only operation requires no write consent. To enable scheduling, separately authorize:

```sh
youtube-mcp/.venv/bin/youtube-channel-auth \
  --client-secrets /Users/mina/Desktop/VocabReelGenerator/client_secrets.json --write
```

This saves `write-token.json` separately and requests `youtube.force-ssl` in addition to read scopes. Google grants that scope broader permissions than this server exposes; enable it only if scheduling is wanted. Set `YOUTUBE_MCP_ENABLE_WRITES = "1"` in the Codex server environment and reconnect. Merely creating the write token does not expose write tools. The read tools still use the read token.

Ask for a schedule preview specifying the exact owned private video ID and a future timestamp with UTC offset, e.g. `2026-12-01T09:00:00-08:00`. Review the concrete preview before explicitly authorizing `confirm=true`. A preview never issues an update. The tool verifies ownership and current private status, rejects naive/past timestamps, and preserves the other writable status fields. YouTube additionally requires the video never to have been published; the API enforces that restriction. Scheduling is a future public release, not an upload. It cannot override policy, copyright, eligibility, or processing restrictions.

Upload creation remains in the existing uploader. New upload, immediate publish, metadata editing, comment posting/moderation, deletion, monetization, copyright administration, and general channel administration are not exposed. No real publication, scheduling update, upload or comment reply was performed for tests.

## Security and validation

Credentials stay local and are never returned as MCP results. Google API errors are reduced to HTTP status, allowlisted reason format, and actionable guidance; request URLs, headers and raw response messages are suppressed. Token errors return reauthorization guidance without credentials. Tool annotations mark reads and optional writes, but annotations are advisory: keep Codex's normal write approval policy. Comment/video text must be treated as untrusted data. Do not commit credential files or local language maps containing private information.

Tests use fake Google services for report parameters, date validation, pagination, Shorts selection, language evidence/unknowns, cohort comparisons, retention, errors, token separation/permissions and scheduling guards. A real subprocess MCP test validates initialization, tool discovery/annotations, prompts, a safe status call and a missing-token error. These checks validate implementation/protocol behavior, not channel access or real report availability.

## Official references

- [Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)
- [YouTube channel report combinations and limits](https://developers.google.com/youtube/analytics/channel_reports)
- [Analytics reports.query scopes, dates and filters](https://developers.google.com/youtube/analytics/reference/reports/query)
- [Analytics content-type dimensions](https://developers.google.com/youtube/analytics/dimensions#creatorContentType)
- [Video scheduling status](https://developers.google.com/youtube/v3/docs/videos#status.publishAt)
- [Video update replacement semantics](https://developers.google.com/youtube/v3/docs/videos/update)
- [Official MCP Python SDK v1](https://py.sdk.modelcontextprotocol.io/v1/)
- [Codex MCP configuration](https://developers.openai.com/codex/mcp)
