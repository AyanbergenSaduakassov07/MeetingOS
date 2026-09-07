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

## Two suites

`*.json` at the top level are **extraction** cases: transcript excerpt in,
expected decisions/actions/risks/commitments out. Scored by
`just eval`.

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
