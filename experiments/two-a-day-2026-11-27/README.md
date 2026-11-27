# Two-a-day, two-direction growth trial

User-approved mix: one English-learning Short plus one Egyptian Arabic Short daily for 14 days, November 27–December 10, 2026, inclusive, America/Los_Angeles (PST). Spanish and new channels remain deferred.

The deployed English workflow already had two daily schedules and successful uploads. The separate Arabic workflow was failing with Gemini `400 INVALID_ARGUMENT: Unknown name speechConfig`. This trial changes the direction mix, not the successful posting frequency. Results cannot establish a causal benefit from doubling volume.

## Posting and automatic end

The existing cron triggers are retained. A tested gate allows the English 09:17 UTC slot and the Arabic 13:23 UTC slot during the trial: **01:17 and 05:23 PST**, respectively. The second English trigger (17:38 UTC / 09:38 PST) skips during the trial. GitHub schedules are best effort and can be delayed; these are intended trigger times, not guaranteed publication times.

From December 11 PST, the gate automatically restores both English slots and pauses Arabic. This returns to the two-successful-English-posts baseline rather than accidentally producing three daily uploads after repairing Arabic. A new Arabic schedule requires a new decision. No time-based manual edit is needed to end the trial. The gate blocks manually requested uploads during the trial to protect the two-slot total; dry runs remain available. Shared workflow concurrency prevents the two posting jobs from advancing state simultaneously.

## Fresh material and preserved source

The trial uses two additive, project-owned UTF-8 CSV files: 70 English expressions (5 × 14) and 98 Egyptian Arabic expressions (7 × 14). Both were checked against the full existing directional published sheets (821 English rows / 300 Arabic rows) and parsed vocabulary bullets from 469 accessible channel videos. The audit normalizes case, punctuation and diacritics and rejects a matching English OR Arabic form. No selected form matched those checked sources. It cannot establish absence in deleted videos, untranscribed speech or omitted descriptions. See `freshness-audit.json` for the exact coverage.

These are useful short phrases, not claimed to be newly discovered words. The translations are sense-specific; masculine speaker/addressee forms are used where relevant and disclosed in descriptions. Romanization is a learner aid, not a phonetic guarantee. The source sheets have not been edited: the connected Drive account did not expose them. Their original rows, URLs and state indices remain intact. A source-sheet bug can therefore be fixed separately rather than silently overwritten. For example, the next legacy English batch pairs “Reconcile” (verb) with “تسوية” (noun); a future sheet review should resolve part-of-speech and context mismatches before resuming that material.

Each fixed trial date owns one unique batch per direction. Content selection never uses modulo, never falls back to old words and fails if a queue is incomplete. Successful uploads append date/direction/video URL records to `uploads.json`; previews never consume words. A recorded date/direction cannot upload again. The original `state_english.json` and `state_arabic.json` do not advance during this additive trial.

If an upload succeeds but the subsequent Git state push fails, inspect the run/video before rerunning; the API upload and Git commit are not an atomic transaction. No automatic catch-up posting is enabled, since it could exceed two in a day. Failed/missed slots remain visible and reduce the delivered experiment sample instead of triggering extra posts.

## Arabic speech repair and layout

The Arabic job now calls the documented Gemini 3.8 Flash TTS Interactions REST API. It separates a verbatim bilingual transcript from `speech_metadata.style`, retains the Achird voice, requests audio, decodes and validates the returned WAV container and retries only transient quota/server failures. Errors never include API keys or arbitrary response bodies. It does not silently substitute formal-Arabic gTTS if Egyptian speech fails. Reference: https://aistudio.google.com/docs/speech-generation

The existing backgrounds, colors, coordinates and layout are preserved. Phrase text wraps and shrinks within fixed column bounds; all 168 entries are checked programmatically for complete, unclipped text and Arabic-table row height. No screenshots or browser control were used. The new descriptions accurately call the content phrases. The English headline emphasizes useful conversation material; the best prior reach/retention example used that framing. This is a hypothesis, not proof that a headline caused performance.

## Measurement

Private local `baseline.json` stores the pre-trial daily summary, leading Shorts, metadata and retention curves. `inventory.json` records accessible inventory for freshness and cohort grounding. These analytics snapshots are ignored by Git and are not deployed publicly.

Run a read-only comparison locally with the installed dedicated OAuth/MCP package:

```sh
youtube-mcp/.venv/bin/python scripts/trial_report.py
```

The report compares baseline publication dates November 13–26 with trial publication dates November 27–December 10. Each video is measured over the **first seven complete Pacific calendar days after its publication day** (days 1–7). Daily Analytics cannot provide exact rolling 168-hour windows. Immature videos stay pending; missing report rows stay unavailable, not zero. A full final review is planned no earlier than December 20 at 10:00 PST, allowing the final December 10 cohort seven complete days plus reporting lag. Availability is checked at report time rather than assumed.

Compare:

- Daily channel engaged views and net subscriber gains, with returned-day coverage shown.
- Matched-direction, equal-age video views/engaged views and gross attributed subscribers per 1,000 engaged views.
- Median per-video average-view percentage among videos with engaged views, plus mature/pending/missing sample counts.
- Baseline retention curves and future retention checks for outliers; the median average-view percentage is not a pooled segment-retention curve.

Per-video subscriber gains are watch-page-attributed and do not equal all channel acquisition. Channel metrics include the rest of the channel catalog. Report mix, vocabulary, publishing time and maturation differences alongside results. No claim of ongoing monitoring is made unless a Codex follow-up is separately registered and verified.

## Validation without publishing

`Validate two-a-day trial (no upload)` is an explicitly dispatched CI workflow. It runs focused tests and generates both first-day MP4 previews using speech credentials but no YouTube credentials. It verifies that dry runs leave all word/ledger state unchanged and saves an artifact for review. It has no schedule and no upload step.

Local checks:

```sh
youtube-mcp/.venv/bin/python -m pytest -q tests youtube-mcp/tests
```
