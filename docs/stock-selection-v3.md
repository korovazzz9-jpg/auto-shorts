# Stock selection and recovery (2026-09-08)

Daily ES passes the full narration to vision. Position is a hint, not precise
sentence alignment. A validated complete approved array can be used even if the
trailing explanation hits max_tokens. Incomplete JSON, refusals, missing posters
and API errors never approve footage. Filter/cache version stays 3: relevance
criteria and prompt are unchanged.

## Scene replenishment

Daily targets max(6, requested queries) distinct downloaded clips. It first picks
one per query, then fills from other already approved candidates, then allows at
most three alternate searches retaining the original object query and narration.
Each alternate query is reviewed. IDs and identical file hashes cannot count twice.
A repeated opening shot used for the visual loop does not count as another scene.
The current equal-duration montage remains; distinct files are not proof of semantic
variety, exact shot/narration alignment, or factual accuracy.

If replenishment is still insufficient, the episode remains pending for watchdog
or the next slot, before spending on TTS/render/upload. No single-scene video is
published. An outage or absent suitable stock can still delay a slot; this is not
a guarantee of continuous publication. No rejected-footage bypass exists.

## Transient API errors and cost

The SDK retains max_retries=0. An explicit wrapper allows one retry for connection
errors, HTTP 408/409/429 and 5xx. Retry-After seconds or HTTP date is respected;
without it the pause is five seconds. Cooldowns above 60 seconds defer to a later
pipeline attempt. Successful content rejection is never retried as an API error.
Calls have a 45-second timeout. Returned usage, retries, recovered responses,
retry reasons and unknown usage from failed requests are counted. Recovered API
response is not necessarily approved footage.

Additional search input/output tokens are separate; retry tokens within additional
searches occur in BOTH counters, so do not add them together. Total input/output
counters remain authoritative for returned usage; unknown billing is never zeroed.
No promise of unchanged cost, and no assumed dollar pricing is embedded.

## Durable state

recovery_es.json stores the pending script, pair context, approved candidate URLs
keyed by filter version/narration/query/orientation, and the last 300 attempts.
Approved clips are redownloaded and checked on resume without another vision call.
The saved script is used before popping another queue item or generating live.
Failed download candidates are removed from the checkpoint for fresh retrieval.
State writes are atomic; ES daily/watchdog commit it even on failure and also save
an artifact for 14 days. A shared concurrency group prevents overlapping writers,
with cancellation disabled. Checkout uses current master to pick up persisted state.

Before upload the checkpoint marks publishing; immediately after YouTube returns
its ID it marks published. An ambiguous interrupted upload is held for reconciliation
rather than uploaded twice. A known published ID clears the pending episode, even
if later cross-posting failed. Hard termination or failed state persistence still
requires checking the artifact and YouTube before any retry; no distributed
exactly-once upload guarantee is claimed.

Weekly report includes retries/reasons, recovered episodes, known extra usage,
unknown-usage attempts, and slots with failed recorded attempts but no publication
after the 45-minute watchdog window. Runs which never started are not covered.

## Offline validation

    python -X utf8 -m unittest discover -s tests -p test_clip_selection_offline.py
    python -X utf8 -m unittest discover -s tests -p test_episode_recovery.py

These tests block paid/network calls. They cover bounds, approved backup filling,
additional search, duplicate bytes, saved selection reuse, queue/pair recovery,
pre-TTS deferral, completed and ambiguous uploads. They establish control flow,
not measured footage quality or improved views.

## Free stock sources (2026-09-08)

Pexels and Pixabay are searched together and interleaved before the existing
four-poster vision call. A failed provider does not suppress other providers.
Pixabay uses videos.<rendition>.thumbnail (or another rendition of the same clip),
with pixabay-prefixed IDs to avoid collisions with legacy numeric Pexels IDs.
Search results are cached for 24 hours in src/stock_search_cache.json; ES workflows
restore/save this cache, including failed attempts. No secret values are cached.

Coverr is optional: set COVERR_API_KEY in GitHub Actions repository secrets. Daily
ES and its watchdog already forward that key; absent key means no Coverr request.
Get a key at https://coverr.co/developers. Current free tier is 50 API calls/hour;
no paid plan or generation endpoint is enabled by this adapter. Actual account
quotas and current terms still apply. Coverr advertises commercially licensed API
content requiring attribution on its current developer page (the older docs intro
contains inconsistent commercial-use wording).

Coverr stores only public preview URLs and IDs in checkpoints. Signed URLs tied
to the API key are resolved just before downloading and never persisted. Downloads
use mp4_download so Coverr records them. No-resolution/missing-poster or explicitly
AI-marked hits are excluded. Coverr cannot be live-verified without an account key.

History tracks source_candidates, source_errors and downloaded_sources. Publication
adds provider credit links to the beginning of the description. The number of
model calls/posters per selection is unchanged; it is not a promise of identical
billing, since retries, replenishment and image dimensions can still affect cost.

Official references:
- https://pixabay.com/api/docs/
- https://www.pexels.com/api/documentation/
- https://api.coverr.co/docs/videos/
- https://api.coverr.co/docs/auth/
- https://coverr.co/developers

Live read-only checks: waterfall vertical returned Pexels + Pixabay with previews;
elephant/ocean waves/wildlife portrait returned Pexels under the existing portrait
resolution filter. No paid vision, TTS, generation or publication was run.
