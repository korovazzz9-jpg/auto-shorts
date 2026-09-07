# Stock selection v3 (2026-09-07)

Daily Shorts and the local pipeline pass the full saved narration to the existing
Haiku vision call. Query position is a hint, not a sentence/timing alignment.
Script generation and stock query generation are unchanged. Other callers without
narration retain query-only selection, but use the same strict validation.

The response must contain a JSON object with an `approved` array of unique,
in-range integer poster numbers, best first. Empty means rejected.
Malformed/truncated responses, API errors and missing previews never approve
footage.

Amended 2026-09-07 after the first live run under v3 (video 2gD7Jh7lUa8): requiring
the reply to be *exactly* JSON rejected 4 of its 5 beats, so the video shipped built
from a single clip. The model had approved footage in all four — it simply wrapped
the object in a ```json fence and appended its reasoning. The first balanced `{...}`
object is now extracted before validation; the object's contents are still validated
strictly (unique, in-range ints, no extra keys), and an unclosed object still counts
as truncated. Tolerance covers the wrapper only, never the verdict. This is locally
validated JSON, not an API-enforced output schema. Broken downloads may only fall
back to another approved candidate. The emergency unverified bypass was removed.
An empty daily result stops before TTS and publishing; this can lose a scheduled
slot. Partial results still use the existing equal-duration montage and do not
promise per-sentence synchronization or factual correctness of the script.

At most one model request per query; SDK retries are disabled. Empty stock search
may simplify the free search before vision, retaining the original context.
Rejection does not trigger a second paid request. Cache v3 includes narration and
shot position, so cross-script hits are intentionally reduced. Added input/output
token counters measure returned usage, not dollars or unreported failed requests.
More prompt tokens and reduced cache reuse mean lower cost is NOT guaranteed.

Validation (no live model, stock, TTS or publication calls):

    python -X utf8 -m unittest discover -s tests -p test_clip_selection_offline.py -v

12 offline regression tests cover parsing, rejection, API failure, missing posters,
cache context/version, approved download backups, the one-call bound, saved ES queue
context, empty/search-error counts, and the pre-TTS stop. These establish control
flow, not a measured improvement in visual relevance or views.