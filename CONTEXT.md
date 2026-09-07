# MeetingOS — Domain Glossary

The shared vocabulary. Terms only; no implementation detail, no spec.

> **The datastore is SQLite. It is not Postgres, and there is no pgvector.**
>
> The original blueprint said Postgres + pgvector. That was never true of the
> implementation, and the gap has already caused confusion more than once —
> briefs keep asking to "extend the pgvector setup" or to use "Postgres
> full-text search", neither of which exists here.
>
> What actually exists: SQLite, with embeddings stored as little-endian float32
> blobs and similarity computed exactly, in Python, by full scan. Keyword search
> is SQLite FTS5, not Postgres FTS. This is adequate for a club or small-team
> corpus and will stop being adequate at scale — which is why corpus retrieval
> sits behind the `MemoryIndex` interface (`backend/memory/base.py`), so moving
> to Postgres + pgvector is a backend swap rather than a rewrite.

## Meeting record

**Meeting** — one recorded conversation. Owns a recording, a transcript, and
everything extracted from it.

**TranscriptSegment** — one contiguous utterance by one speaker, with a start
and end time. The atomic unit of provenance: nothing extracted is trusted
unless it points at one.

**Speaker** — a distinct voice within a meeting, resolved to a **User** when we
can match it. Anonymous until then ("Speaker 1").

**Topic** — a stretch of a meeting about one subject. Derived, not spoken.

## Extraction

**Claim** — an assertion the extractor believes the meeting made. Not yet
trusted. A claim becomes trustworthy only when its **Evidence** is verified.

**Decision** — something the group actually settled. A proposal that was
rejected is still a Decision (to reject); a proposal nobody responded to is not.

**ActionItem** — a task someone took on, with an owner where one was named.

**Risk** — a concern, blocker, or exposure someone raised.

**Commitment** — a personal promise about the speaker's own future action.
Distinct from an ActionItem: "I'll chase the invoice" is both; "Priya should
chase the invoice" is only an ActionItem.

## Provenance

**Evidence** — one claim and the transcript that backs it: the claim text, the
verbatim quote, the **TranscriptSegment**(s) cited, the time span across them,
extraction confidence, and a verification verdict. Every Decision, ActionItem,
Risk and Commitment resolves to exactly one Evidence record, and Evidence is
queryable on its own.

**Citation** — one link from Evidence to a TranscriptSegment. Ordered, because
a claim can span several utterances.

**Verification status** — the verdict on whether the cited segments actually
support the claim:
- `verified` — the quote appears in the cited segment, or the claim and segment
  are semantically close enough. (The brief's "supported".)
- `low_confidence` — the citation resolves to a real segment, but that segment
  may not support the claim. A human should look.
- `unsupported` — the citation does not resolve to a real segment of this
  meeting. The model invented an id. Categorically different from
  `low_confidence`: one is a fabricated reference, the other a judgement call.
- `unverified` — the verifier has not run. Must never be read as "checked".
- `superseded` — a duplicate of another item, merged rather than deleted.

**Grounded** — an Evidence record that cites at least one real segment. An
ungrounded claim may still be displayed, but never as fact.

## Cross-meeting

**Chain** — the linear sequence of Decisions on one subject, oldest first,
linked by `supersedes_id`. Linear on purpose: "what happened to this question"
has one answer per point in time.

**DecisionEvent** — an append-only entry in a decision's life, recording which
meeting revisited it.

**Relationship** — how a new claim stands against a prior one on the same
subject:
- `consistent` — same thing, or unrelated. Two claims about different subjects
  are consistent; they do not conflict.
- `refined` — same direction, more detail or a narrower scope. A range becoming
  a figure is refinement, not reversal.
- `contradicted` — incompatible with the prior claim, but nobody in the meeting
  appeared to notice. This is the one worth surfacing, precisely because
  nothing else will catch it.
- `reversed` — the meeting deliberately overturned the prior decision.

A `contradicted` or `reversed` verdict must cite **both** Evidence records. An
accusation with only one receipt is downgraded to `consistent` and marked
`low_confidence`.

## Obligations

**Commitment** — a promise a person made about their own future action.
**ActionItem** — tracked work someone was given. Kept apart from Commitment:
a broken promise says something about follow-through that an unfinished task
does not.

**Overdue** — a deadline in the past *and* a status still open. Computed
server-side so every client agrees. An obligation with no deadline is never
overdue; inventing one to call somebody late would manufacture the accusation.

**Completion rate** — completed over *settled* obligations. Null when nothing
has settled: a rate over zero closed items is not a rate, and 0% would read as
a finding about someone who simply has not finished yet.
