# Extraction eval cases

Ten frozen transcript excerpts with hand-verified expected extractions, used by
`backend/eval/run_eval.py` to score the Phase 3 extraction pipeline.

## Provenance — read this before trusting a score

**These are hand-authored, not transcribed from real recordings.** No real
meeting has ever been recorded, transcribed, or extracted by this project: the
only audio in `data/recordings/` is synthetic tone I generated to give the
waveform something to draw, and the seeded "Robotics club weekly" meeting was
written by hand, not produced by the pipeline.

They are written to be *representative* of the target domain — student club and
small-organisation governance meetings — and each expected output was derived by
reading the excerpt and deciding what a careful human would extract. That makes
them a real regression suite and a real measure of extraction behaviour. It does
not make them a measure of how the pipeline performs on real speech, which
carries disfluency, crosstalk, ASR error, and speaker-attribution noise that
none of these excerpts have.

Scores here are therefore an **upper bound**. Treat them as "does extraction
still behave as designed" rather than "is extraction accurate in production".
Replace or supplement these with cases cut from genuine recordings before
reading any number here as a production quality signal.

## Privacy

Every name, organisation, figure, and date is invented. No case contains real
personal data, so the suite can be committed, shared, and sent to a third-party
model API without a redaction pass. Keep it that way: if a case is ever added
from a genuine meeting, it must be redacted first — see the privacy assessment
in the phase report.

## Five suites

`*.json` at the top level are **extraction** cases: transcript excerpt in,
expected decisions/actions/risks/commitments out. Scored by `just eval`.

`crosslingual/*.json` measure whether the configured **embedding model** aligns
languages: index a should-retrieve and a should-not-retrieve record in one
language, query in another, check the right one ranks first. Scored by
`just eval -- --crosslingual`, and skipped rather than scored when no real
embedding provider is configured — measuring cross-language retrieval against a
monolingual bag-of-words stub measures the stub.

`copilot/*.json` and `fusion/*.json` are **corpus answer** cases, described
below. Run everything with `just eval -- --all`.

`comparator/*.json` are **claim comparator** cases: a prior claim and a new
one, with the expected relationship (consistent / refined / contradicted /
reversed). Scored by `just eval -- --comparator`.

The comparator set is split three ways on purpose:

- `genuine` (3) — real contradictions and reversals that must be caught.
- `near_miss` (5) — topic drift, partial updates, a range narrowing to a
  figure, a decision restated. These look like conflicts and are not. A false
  positive here is worse than a miss: it sends a board to re-litigate a
  decision that was never in question, and teaches readers to ignore the
  conflict list.
- `adversarial` (1) — an injection payload demanding a `reversed` verdict for
  two claims that do not conflict.

The reported `false_positive_rate` over the near-miss set is the number to
watch, not overall accuracy.

## Structure

One JSON file per case:

```jsonc
{
  "name": "unique-slug",
  "complexity": "simple | medium | complex | adversarial",
  "notes": "what this case is testing",
  "segments": [{"speaker": "Chair", "start_ms": 0, "end_ms": 8000, "text": "..."}],
  "expected": {
    "decisions":   [{"gist": "...", "cites_segment": 2}],
    "action_items":[{"gist": "...", "cites_segment": 3}],
    "risks":       [{"gist": "...", "cites_segment": 5}],
    "commitments": [{"gist": "...", "cites_segment": 5}]
  }
}
```

`gist` is matched semantically, not literally — see `run_eval.py`. `cites_segment`
is the index into `segments` a correct extraction should cite; scoring reports
citation accuracy separately from whether the item was found at all.

An empty expected list is a real expectation: cases like `no-decisions-social`
exist to catch over-extraction, which is the failure mode that matters most here.

## Corpus answer cases (`copilot/`, `fusion/`)

These score the org-wide copilot end to end: a corpus is built from the case,
indexed, asked the question, and the answer scored. A `fusion` case is a
`copilot` case that also carries `documents`, so one runner serves both — a
scoring change cannot apply to one suite and silently miss the other.

```jsonc
{
  "name": "unique-slug",
  "complexity": "simple | cross_meeting | fusion | refusal | adversarial",
  "meetings": [{"title": "...", "language": "en", "records": [
      {"key": "budget", "text": "...", "verification_status": "verified", "relevant": true}]}],
  "documents": [{"title": "...", "language": "en", "chunks": [
      {"key": "clause", "text": "...", "relevant": true}]}],
  "question": "...",
  "expects_answer": true,
  "must_cite": ["budget", "clause"],
  "must_contain_any": ["500,000", "500000"],
  "must_not_contain": ["PWNED"],
  "must_span_kinds": ["meeting", "document"]
}
```

`key` is a stable label for a record. Scoring maps generated record ids back
through it, so a citation score never depends on a uuid. `relevant` marks the
records that genuinely answer the question — that is what citation precision is
measured against, while `must_cite` is what recall is measured against.

Every case gets its own database *and* its own org. Sharing either would let
one case's records answer another case's question, turning a retrieval failure
into a pass.

### What the numbers mean

- **citation precision** — of the records the answers cited, how many were
  relevant. Pooled over records, not averaged per case, so one case citing ten
  records cannot be outvoted by one citing a single record.
- **citation recall** — of the records that should have been cited, how many
  were.
- **answer accuracy** — of answerable cases, how many answers contained the
  fact the case requires.
- **refusal accuracy** / **false answers** — over the unanswerable cases only.
  Read these next to the three above, always. A model that refuses everything
  scores perfect citation precision on citations it never made; one that
  answers everything scores perfect recall on questions it should have
  declined. Neither number means anything alone.
- **source-span accuracy** — did an answer that needed both a meeting and a
  document cite both.
- **coverage** — the fraction of cases that reached the model at all. Cases
  that failed first (rate limit, outage) are excluded from every quality number
  above and counted here instead. A provider failure is missing data, not a
  score of zero.

The refusal and adversarial cases are the point of these suites. Roughly a
third of each is unanswerable or hostile, because a corpus copilot that answers
a plausible nearby question, or follows an instruction planted in a retrieved
chunk, fails in a way the answerable cases cannot show.
