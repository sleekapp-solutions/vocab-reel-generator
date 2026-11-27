# Permanent two-a-day posting with an initial measurement window

User-approved permanent mix: one English-learning Short plus one Egyptian Arabic Short daily. November 27–December 10, 2026, inclusive, America/Los_Angeles (PST), remains the initial 14-day growth-measurement and fresh-content window; it is not a publishing expiry. Spanish and new channels remain deferred.

The deployed English workflow already had two daily schedules and successful uploads. The separate Arabic workflow was failing with Gemini `400 INVALID_ARGUMENT: Unknown name speechConfig`. This trial changes the direction mix, not the successful posting frequency. Results cannot establish a causal benefit from doubling volume.

## Permanent posting and content transition

The English workflow has exactly one cron trigger at **09:17 UTC**; Arabic has exactly one at **13:23 UTC**. These correspond to **01:17 and 05:23 PST**, respectively. The old 17:38 UTC English trigger has been removed, rather than being restored after the measurement window. UTC trigger times remain fixed, so local clock times shift with daylight saving. GitHub schedules are best effort and can be delayed; these are intended trigger times, not guaranteed publication times.

Both directions continue daily on and after December 11. There is no date-based pause, second English slot, or posting reversion. Only the content source changes: the fixed fresh CSV batches run through December 10; on December 11 both original published Google Sheets resume at their preserved zero-based saved positions (**English 83; Arabic 226**, as verified before deployment). English consumes 5 pairs per successful upload, Arabic 7. Each original source continues from its own current index and wraps using the existing modulo behavior when it reaches the list end. Repeating old vocabulary in that continuing cycle is intentional, not represented as fresh material.

The gate blocks manual workflow uploads to protect the two scheduled daily slots; manual dry runs remain available. Shared workflow concurrency prevents the posting jobs from advancing state simultaneously. The upload ledger prevents another scheduled upload for the same Pacific date/direction both inside and after the measurement window. Failed uploads do not advance either index or ledger. Outside this scheduled workflow, a direct local generator invocation retains its existing behavior; it is not a channel-wide quota controller.

## Fresh material and preserved source

The initial measurement window uses two additive, project-owned UTF-8 CSV files: 70 English expressions (5 × 14) and 98 Egyptian Arabic expressions (7 × 14). Both were checked against the both full existing published sheets (821 English rows / 300 Arabic rows) and parsed vocabulary bullets from 469 accessible channel videos. The audit normalizes case, punctuation and diacritics and rejects a matching English OR Arabic form. No selected form matched those checked sources. It cannot establish absence in deleted videos, untranscribed speech or omitted descriptions. See `freshness-audit.json` for the exact coverage.

These are useful short phrases, not claimed to be newly discovered words. The translations are sense-specific; masculine speaker/addressee forms are used where relevant and disclosed in descriptions. Romanization is a learner aid, not a phonetic guarantee. The source sheets have not been edited: the connected Drive account did not expose them. Their original rows, URLs and state indices remain intact. A source-sheet bug can therefore be fixed separately rather than silently overwritten. For example, the next legacy English batch pairs “Reconcile” (verb) with “تسوية” (noun); a future sheet review should resolve part-of-speech and context mismatches before resuming that material.

Each fixed fresh-content-window date owns one unique batch per direction. Content selection never uses modulo, never falls back to old words and fails if a queue is incomplete. Successful uploads append date/direction/video URL records to `uploads.json`; previews never consume words. A recorded date/direction cannot upload again. The original `state_english.json` and `state_arabic.json` do not advance while the additive fresh queues are used. They resume advancing only after successful uploads from their respective original Sheets on and after December 11. No source index is reset during the transition.

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

If this checkout is stale, first fetch the deployed `experiments/two-a-day-2026-11-27/uploads.json` from the repository and pass its path with `--ledger`; trial directions are grounded in the internal upload ledger, never implementation IDs in public descriptions.

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

## Original Arabic failure evidence

The last successful Arabic run on November 5 uploaded rows 220–226 of 300 and advanced the index to 226. The November 6 run selected valid rows 227–233 and failed during Gemini speech generation with `400 INVALID_ARGUMENT`, rejecting `speechConfig` under `generation_config`; the November 26 failure is identical. The sheet was not exhausted and modulo cycling did not cause the speech request failure. English uploads continued. Both workflow records remained active; upload was disabled only for the explicit dry-run validation.

- Last success: https://github.com/sleekapp-solutions/vocab-reel-generator/actions/runs/42106006612
- First sustained failure: https://github.com/sleekapp-solutions/vocab-reel-generator/actions/runs/42284382962
- Recent same failure: https://github.com/sleekapp-solutions/vocab-reel-generator/actions/runs/45904886745

## Permanent-schedule verification

Boundary tests cover November 27, December 10, December 11 and later dates; actual workflow cron counts; resumed Sheet selection; normal index advancement; modulo wrap for both list sizes; duplicate rejection; and failed uploads preserving state. The original two-week comparison and December 20 maturation guidance remain unchanged. No automatic monitoring has been enabled.
