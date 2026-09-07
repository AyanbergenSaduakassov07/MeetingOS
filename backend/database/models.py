"""ORM model definitions for the MeetingOS database.

Domain shape
------------
A ``Meeting`` belongs to an ``Organization`` and produces raw signal
(``Speaker``, ``TranscriptSegment``, ``Topic``) which the extraction layer
turns into governance objects (``Decision``, ``ActionItem``, ``Risk``,
``Commitment``).  ``DecisionEvent`` is the append-only audit trail that lets a
decision be traced across the meetings that touched it — that lineage is the
reason this schema exists and is why extracted rows keep a
``source_segment_id`` pointing back at the exact utterance they came from.

Conventions (carried over from the previous schema)
---------------------------------------------------
- String UUID primary keys, generated app-side, so rows can be created
  without a round-trip to the database.
- ``Column``-style declarative rather than 2.0 ``Mapped[]`` annotations,
  matching the rest of the backend.
- Enumerated values live in Python ``str`` enums and are stored as plain
  strings; SQLite has no native enum and string columns keep migrations
  additive.
- Timestamps are timezone-aware UTC.  ``datetime.utcnow`` is deprecated from
  Python 3.12 onward, so ``_utcnow`` is used in its place.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used as the default for every timestamp column."""
    return datetime.now(timezone.utc)


def _uuid() -> str:
    """Generate a string UUID primary key."""
    return str(uuid.uuid4())


# ── Enumerations ──────────────────────────────────────────────────────────


class UserRole(str, enum.Enum):
    """Org-chart role. Drives what a user may see, not just what they may do.

    ``board`` and ``auditor`` are read-mostly roles that exist so board packs
    and compliance exports can be scoped without granting write access.
    """

    EMPLOYEE = "employee"
    MANAGER = "manager"
    EXECUTIVE = "executive"
    BOARD = "board"
    ADMIN = "admin"
    AUDITOR = "auditor"


class MeetingStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    RECORDING = "recording"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MeetingSource(str, enum.Enum):
    LIVE = "live"
    UPLOAD = "upload"
    ZOOM = "zoom"
    GOOGLE_MEET = "google_meet"
    TEAMS = "teams"


class Visibility(str, enum.Enum):
    PRIVATE = "private"
    TEAM = "team"
    ORG = "org"


class DecisionStatus(str, enum.Enum):
    PROPOSED = "proposed"
    AGREED = "agreed"
    DEFERRED = "deferred"
    REVERSED = "reversed"
    SUPERSEDED = "superseded"


class DecisionEventType(str, enum.Enum):
    PROPOSED = "proposed"
    DISCUSSED = "discussed"
    AGREED = "agreed"
    REVISITED = "revisited"
    REVERSED = "reversed"
    SUPERSEDED = "superseded"


class ActionItemStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class RiskSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskStatus(str, enum.Enum):
    OPEN = "open"
    MITIGATING = "mitigating"
    ACCEPTED = "accepted"
    CLOSED = "closed"


class CommitmentStatus(str, enum.Enum):
    PENDING = "pending"
    KEPT = "kept"
    BROKEN = "broken"
    RENEGOTIATED = "renegotiated"


class VerificationStatus(str, enum.Enum):
    """Whether an extracted claim is actually supported by the segment it cites.

    ``UNSUPPORTED`` is reserved for a citation that does not resolve to a real
    segment of this meeting — the model invented an id. That is categorically
    different from a weak-but-real citation (``LOW_CONFIDENCE``), and the two
    must not be collapsed: one is a hallucinated reference, the other is a
    judgement call a reviewer can make.
    """

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    LOW_CONFIDENCE = "low_confidence"
    UNSUPPORTED = "unsupported"


class DocumentType(str, enum.Enum):
    AGENDA = "agenda"
    DECK = "deck"
    MINUTES = "minutes"
    CONTRACT = "contract"
    REPORT = "report"
    OTHER = "other"


class EvalTask(str, enum.Enum):
    """Which extraction path an eval case exercises."""

    TRANSCRIPTION = "transcription"
    DIARIZATION = "diarization"
    SUMMARY = "summary"
    DECISION = "decision"
    ACTION_ITEM = "action_item"
    RISK = "risk"
    COMMITMENT = "commitment"


# ── Tenancy and identity ──────────────────────────────────────────────────


class Organization(Base):
    """A customer tenant. Every domain row hangs off exactly one org."""

    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    domain = Column(String, nullable=True)  # email domain for auto-join
    plan = Column(String, default="trial")
    # Hard-delete horizon for recordings and transcripts. Enterprise buyers
    # ask for this before they ask for features.
    retention_days = Column(Integer, default=365)
    settings = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    users = relationship("User", back_populates="organization", foreign_keys="User.org_id")
    meetings = relationship("Meeting", back_populates="organization")


class User(Base):
    """A person inside an organization.

    ``manager_id`` is a self-referential edge so the reporting line can be
    walked when deciding who sees an escalated risk or an overdue commitment.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_users_org_email"),)

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False, default=UserRole.EMPLOYEE.value)
    title = Column(String, nullable=True)
    department = Column(String, nullable=True)
    manager_id = Column(String, ForeignKey("users.id"), nullable=True)
    avatar_url = Column(String, nullable=True)
    timezone = Column(String, default="UTC")
    is_active = Column(Boolean, default=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    organization = relationship("Organization", back_populates="users", foreign_keys=[org_id])
    reports = relationship("User", backref="manager", remote_side=[id])


# ── Meetings and raw signal ───────────────────────────────────────────────


class Meeting(Base):
    """A single meeting: its scheduling metadata, its audio, and its outcome."""

    __tablename__ = "meetings"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    scheduled_start = Column(DateTime(timezone=True), nullable=True)
    scheduled_end = Column(DateTime(timezone=True), nullable=True)
    actual_start = Column(DateTime(timezone=True), nullable=True)
    actual_end = Column(DateTime(timezone=True), nullable=True)

    status = Column(String, nullable=False, default=MeetingStatus.SCHEDULED.value, index=True)
    source = Column(String, nullable=False, default=MeetingSource.UPLOAD.value)
    external_id = Column(String, nullable=True)  # Zoom/Meet/Teams conference id

    recording_path = Column(String, nullable=True)
    audio_duration_seconds = Column(Float, nullable=True)
    language = Column(String, default="en")

    template_id = Column(String, ForeignKey("meeting_templates.id"), nullable=True)
    created_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    visibility = Column(String, nullable=False, default=Visibility.TEAM.value)

    summary = Column(Text, nullable=True)
    sentiment_score = Column(Float, nullable=True)
    processing_error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    organization = relationship("Organization", back_populates="meetings")
    template = relationship("MeetingTemplate")
    speakers = relationship("Speaker", back_populates="meeting", cascade="all, delete-orphan")
    segments = relationship("TranscriptSegment", back_populates="meeting", cascade="all, delete-orphan")
    topics = relationship("Topic", back_populates="meeting", cascade="all, delete-orphan")


class Speaker(Base):
    """A distinct voice in a meeting, resolved to a ``User`` when we can.

    Diarization produces anonymous voices first (``display_label`` = "Speaker
    1").  ``voice_embedding`` is the fingerprint used to match that voice to a
    known person, here and in later meetings.  It is stored as raw little-endian
    float32 bytes rather than JSON: a 192- or 256-dim embedding per speaker per
    meeting adds up, and the bytes go straight into a numpy buffer for cosine
    comparison without a parse step.  ``embedding_model`` and ``embedding_dim``
    travel with it because embeddings from different models are not comparable
    and the model will be swapped.
    """

    __tablename__ = "speakers"

    id = Column(String, primary_key=True, default=_uuid)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)

    display_label = Column(String, nullable=False)  # "Speaker 1" until identified
    voice_embedding = Column(LargeBinary, nullable=True)
    embedding_model = Column(String, nullable=True)  # e.g. "pyannote/embedding-3.0"
    embedding_dim = Column(Integer, nullable=True)
    identification_confidence = Column(Float, nullable=True)
    is_confirmed = Column(Boolean, default=False)  # a human accepted the match

    talk_time_seconds = Column(Float, default=0.0)
    word_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=_utcnow)

    meeting = relationship("Meeting", back_populates="speakers")
    user = relationship("User")
    segments = relationship("TranscriptSegment", back_populates="speaker")


class TranscriptSegment(Base):
    """One contiguous utterance. The provenance anchor for everything extracted."""

    __tablename__ = "transcript_segments"

    id = Column(String, primary_key=True, default=_uuid)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=False, index=True)
    speaker_id = Column(String, ForeignKey("speakers.id"), nullable=True, index=True)

    sequence = Column(Integer, nullable=False)  # ordering within the meeting
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    language = Column(String, nullable=True)
    is_final = Column(Boolean, default=True)  # False while streaming a live meeting
    is_redacted = Column(Boolean, default=False)

    # Retrieval index for the copilot.  Same storage choice as
    # ``Speaker.voice_embedding``: raw little-endian float32 bytes rather than
    # JSON, because a 1536-dim vector per segment per meeting adds up and the
    # bytes go straight into a numpy buffer without a parse step.
    #
    # This is not pgvector.  MeetingOS runs on SQLite, which has no vector
    # index, so similarity is computed in Python over the segments of one
    # meeting — a few hundred rows at most, which is well inside the range
    # where a brute-force scan beats maintaining an index.  ``embedding_model``
    # travels with the vector because embeddings from different models are not
    # comparable and the model will be swapped.
    embedding = Column(LargeBinary, nullable=True)
    embedding_model = Column(String, nullable=True)
    embedding_dim = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)

    meeting = relationship("Meeting", back_populates="segments")
    speaker = relationship("Speaker", back_populates="segments")


class Topic(Base):
    """A discussion topic occupying a span of the meeting."""

    __tablename__ = "topics"

    id = Column(String, primary_key=True, default=_uuid)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=False, index=True)

    label = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    start_ms = Column(Integer, nullable=True)
    end_ms = Column(Integer, nullable=True)
    salience = Column(Float, nullable=True)  # 0..1 share of meeting attention
    keywords = Column(JSON, default=list)

    created_at = Column(DateTime(timezone=True), default=_utcnow)

    meeting = relationship("Meeting", back_populates="topics")


# ── Extracted governance objects ──────────────────────────────────────────


class Evidence(Base):
    """One claim and the transcript that backs it.

    Before this existed, every extracted item carried five loose columns —
    ``source_segment_id``, ``source_quote``, ``extraction_confidence``,
    ``verification_status``, ``verification_score`` — duplicated across four
    tables. That is a data clump: the same fields always travelling together,
    which is a type asking to be born. Worse, it made provenance unqueryable.
    "Show me every low-confidence claim in this org" meant four UNIONs, and
    "which claims cite this segment?" meant four more.

    Evidence is that type. One row per claim, holding what was asserted, the
    verbatim words behind it, the segments it cites, and the verdict on
    whether those segments actually support it.

    **A claim can cite more than one segment.** A decision reached across three
    turns of conversation has three sources, and the old single ``source_segment_id``
    could only ever record the first. Citations live in ``evidence_citations``
    and keep their order.

    The extracted items keep their five original attribute names as properties
    that read and write through to here, so Phase 3 code and its tests are
    unaffected by the move. The interface stayed; the implementation moved.
    """

    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=True, index=True)

    # What is being asserted. Denormalised from the owning item so Evidence can
    # be searched and embedded without joining back to four different tables.
    claim_text = Column(Text, nullable=True)
    # The verbatim words the extractor cited. Checking that this appears in the
    # cited segment is a deterministic fabrication test that costs nothing and
    # beats any similarity score.
    quote = Column(Text, nullable=True)

    # Span across the cited segments. Maintained by ``cite``; denormalised so a
    # timeline query does not have to join through the citation table.
    start_ms = Column(Integer, nullable=True)
    end_ms = Column(Integer, nullable=True)

    confidence = Column(Float, nullable=True)
    verification_status = Column(
        String, nullable=False, default=VerificationStatus.UNVERIFIED.value, index=True
    )
    verification_score = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    meeting = relationship("Meeting")
    citations = relationship(
        "EvidenceCitation",
        back_populates="evidence",
        order_by="EvidenceCitation.sequence",
        cascade="all, delete-orphan",
    )

    def cite(self, segment) -> "EvidenceCitation":
        """Add a source segment and widen the span to include it."""
        citation = EvidenceCitation(
            evidence=self, segment_id=segment.id, sequence=len(self.citations)
        )
        self.citations.append(citation)
        if segment.start_ms is not None:
            self.start_ms = segment.start_ms if self.start_ms is None else min(self.start_ms, segment.start_ms)
        if segment.end_ms is not None:
            self.end_ms = segment.end_ms if self.end_ms is None else max(self.end_ms, segment.end_ms)
        return citation

    @property
    def segment_ids(self) -> list[str]:
        """Cited segment ids, in citation order."""
        return [citation.segment_id for citation in self.citations]

    @property
    def is_grounded(self) -> bool:
        """True when this claim cites at least one real segment."""
        return bool(self.citations)

    def __repr__(self) -> str:
        return f"<Evidence {self.id} {self.verification_status} cites={len(self.citations)}>"


class EvidenceCitation(Base):
    """One (Evidence -> TranscriptSegment) link, ordered.

    A separate table rather than a JSON array because "which claims cite this
    segment?" is a question the timeline and memory-index work needs to answer
    with an index, not a scan.
    """

    __tablename__ = "evidence_citations"

    id = Column(String, primary_key=True, default=_uuid)
    evidence_id = Column(String, ForeignKey("evidence.id"), nullable=False, index=True)
    segment_id = Column(String, ForeignKey("transcript_segments.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=0)

    evidence = relationship("Evidence", back_populates="citations")
    segment = relationship("TranscriptSegment")


class _EvidenceBacked:
    """Compatibility shim: the five original citation attributes.

    Phase 3's extractor and verifier read and write ``item.source_segment_id``,
    ``item.verification_status`` and friends. Those names are the established
    interface, and there is no reason to churn every call site to prove a
    schema change happened — so they stay, delegating to ``evidence``.

    Assigning any of them to an item that has no Evidence creates one, which is
    what lets ``_persist`` keep building items field by field.
    """

    def _ensure_evidence(self) -> "Evidence":
        if self.evidence is None:
            self.evidence = Evidence(org_id=self.org_id, meeting_id=self.meeting_id)
        return self.evidence

    @property
    def source_segment_id(self):
        evidence = self.evidence
        if evidence is None or not evidence.citations:
            return None
        return evidence.citations[0].segment_id

    @source_segment_id.setter
    def source_segment_id(self, value):
        evidence = self._ensure_evidence()
        evidence.citations.clear()
        if value is not None:
            evidence.citations.append(EvidenceCitation(evidence=evidence, segment_id=value, sequence=0))

    @property
    def source_quote(self):
        return self.evidence.quote if self.evidence else None

    @source_quote.setter
    def source_quote(self, value):
        self._ensure_evidence().quote = value

    @property
    def extraction_confidence(self):
        return self.evidence.confidence if self.evidence else None

    @extraction_confidence.setter
    def extraction_confidence(self, value):
        self._ensure_evidence().confidence = value

    @property
    def verification_status(self):
        if self.evidence is None:
            return VerificationStatus.UNVERIFIED.value
        return self.evidence.verification_status

    @verification_status.setter
    def verification_status(self, value):
        self._ensure_evidence().verification_status = value

    @property
    def verification_score(self):
        return self.evidence.verification_score if self.evidence else None

    @verification_score.setter
    def verification_score(self, value):
        self._ensure_evidence().verification_score = value


class Decision(_EvidenceBacked, Base):
    """Something the meeting settled.

    ``supersedes_id`` chains decisions so a reversal three months later still
    points at what it replaced; the full history lives in ``DecisionEvent``.
    """

    __tablename__ = "decisions"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=True, index=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    rationale = Column(Text, nullable=True)
    status = Column(String, nullable=False, default=DecisionStatus.PROPOSED.value, index=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decision_maker_id = Column(String, ForeignKey("users.id"), nullable=True)

    supersedes_id = Column(String, ForeignKey("decisions.id"), nullable=True)
    # Provenance lives in Evidence. The five original attribute names remain
    # available via _EvidenceBacked, delegating here.
    evidence_id = Column(String, ForeignKey("evidence.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    meeting = relationship("Meeting")
    evidence = relationship("Evidence")
    decision_maker = relationship("User")
    supersedes = relationship("Decision", remote_side=[id])
    events = relationship("DecisionEvent", back_populates="decision", cascade="all, delete-orphan")


class DecisionEvent(Base):
    """Append-only entry in a decision's life.

    Kept separate from ``Decision`` so the current state stays cheap to query
    while the trail survives — an auditor asking "when did this change, in
    which meeting, and who was in the room" is answered from this table.
    """

    __tablename__ = "decision_events"

    id = Column(String, primary_key=True, default=_uuid)
    decision_id = Column(String, ForeignKey("decisions.id"), nullable=False, index=True)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=True, index=True)

    event_type = Column(String, nullable=False, default=DecisionEventType.DISCUSSED.value)
    actor_id = Column(String, ForeignKey("users.id"), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    notes = Column(Text, nullable=True)
    payload = Column(JSON, default=dict)  # before/after snapshot for reversals

    created_at = Column(DateTime(timezone=True), default=_utcnow)

    decision = relationship("Decision", back_populates="events")
    meeting = relationship("Meeting")
    actor = relationship("User")


class ActionItem(_EvidenceBacked, Base):
    """Tracked work assigned in a meeting."""

    __tablename__ = "action_items"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=True, index=True)
    decision_id = Column(String, ForeignKey("decisions.id"), nullable=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    assignee_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    assigned_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    status = Column(String, nullable=False, default=ActionItemStatus.OPEN.value, index=True)
    priority = Column(String, nullable=False, default=Priority.MEDIUM.value)
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Provenance lives in Evidence. The five original attribute names remain
    # available via _EvidenceBacked, delegating here.
    evidence_id = Column(String, ForeignKey("evidence.id"), nullable=True, index=True)
    external_ticket_url = Column(String, nullable=True)  # Jira/Linear round-trip

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    meeting = relationship("Meeting")
    evidence = relationship("Evidence")
    decision = relationship("Decision")
    assignee = relationship("User", foreign_keys=[assignee_id])
    assigned_by = relationship("User", foreign_keys=[assigned_by_id])


class Risk(_EvidenceBacked, Base):
    """A risk raised in conversation, with an owner and a mitigation path."""

    __tablename__ = "risks"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=True, index=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True)  # financial, legal, technical, people, ...
    severity = Column(String, nullable=False, default=RiskSeverity.MEDIUM.value, index=True)
    likelihood = Column(Float, nullable=True)  # 0..1
    status = Column(String, nullable=False, default=RiskStatus.OPEN.value, index=True)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    mitigation = Column(Text, nullable=True)

    # Provenance lives in Evidence. The five original attribute names remain
    # available via _EvidenceBacked, delegating here.
    evidence_id = Column(String, ForeignKey("evidence.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    meeting = relationship("Meeting")
    evidence = relationship("Evidence")
    owner = relationship("User")


class Commitment(_EvidenceBacked, Base):
    """A verbal promise — "I'll have the numbers by Friday".

    Distinct from ``ActionItem`` on purpose.  An action item is tracked work
    someone agreed to own; a commitment is a statement a person made, scored
    later on whether it was kept.  Conflating the two loses the follow-through
    signal, which is the thing executives actually want out of this product.
    """

    __tablename__ = "commitments"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=True, index=True)

    committer_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    committed_to_id = Column(String, ForeignKey("users.id"), nullable=True)
    text = Column(Text, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default=CommitmentStatus.PENDING.value, index=True)
    fulfilled_at = Column(DateTime(timezone=True), nullable=True)

    # Provenance lives in Evidence. The five original attribute names remain
    # available via _EvidenceBacked, delegating here.
    evidence_id = Column(String, ForeignKey("evidence.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    meeting = relationship("Meeting")
    evidence = relationship("Evidence")
    committer = relationship("User", foreign_keys=[committer_id])
    committed_to = relationship("User", foreign_keys=[committed_to_id])


# ── Configuration, context, and quality ───────────────────────────────────


class MeetingTemplate(Base):
    """Per-meeting-type configuration: agenda, extraction schema, prompt tweaks.

    A board meeting and a standup want different structured output out of the
    same pipeline; the template is what varies, not the code.
    """

    __tablename__ = "meeting_templates"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    agenda = Column(JSON, default=list)  # ordered agenda items
    extraction_schema = Column(JSON, default=dict)  # JSON Schema the LLM must fill
    prompt_overrides = Column(JSON, default=dict)
    required_roles = Column(JSON, default=list)  # UserRole values expected to attend
    default_visibility = Column(String, nullable=False, default=Visibility.TEAM.value)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Document(Base):
    """A file attached to a meeting or to the org — agenda, deck, contract."""

    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=True, index=True)

    title = Column(String, nullable=False)
    doc_type = Column(String, nullable=False, default=DocumentType.OTHER.value)
    storage_path = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    checksum = Column(String, nullable=True)  # sha256, for dedupe
    uploaded_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    extracted_text = Column(Text, nullable=True)  # feeds retrieval
    language = Column(String, nullable=True)
    # Documents carry contracts and financials far more often than a casual
    # meeting does. This flags the ones an operator has marked as needing care
    # before they leave the machine; see backend/meetings/redaction.py.
    is_sensitive = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    meeting = relationship("Meeting")
    uploaded_by = relationship("User")
    chunks = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    """One indexable slice of a document.

    Documents are chunked rather than embedded whole for the same reason
    transcripts are segmented: a fifty-page contract embedded as one vector
    matches everything weakly and nothing precisely, and a citation pointing at
    "the contract" tells a reader nothing about where to look.

    ``page`` and ``ordinal`` are the document equivalent of a transcript
    timestamp — the coordinates a citation needs to be checkable.
    """

    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False, index=True)

    ordinal = Column(Integer, nullable=False, default=0)
    page = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    language = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)

    document = relationship("Document", back_populates="chunks")


class MeetingDocument(Base):
    """An explicit link between a meeting and a document discussed in it.

    Explicit, not inferred. Detecting that a transcript refers to a particular
    document is its own extraction problem — "the contract we talked about" has
    no id in it — and guessing wrong attaches a contract to the wrong meeting,
    which is worse than not linking at all. ``Document.meeting_id`` remains for
    the document's own home meeting; this table is the many-to-many for
    documents referenced across several.
    """

    __tablename__ = "meeting_documents"

    id = Column(String, primary_key=True, default=_uuid)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=False, index=True)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False, index=True)
    linked_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)

    meeting = relationship("Meeting")
    document = relationship("Document")


class EvalCase(Base):
    """A frozen input/expected-output pair for regression-testing extraction.

    Nullable ``org_id`` because the shipped baseline suite belongs to no
    tenant, while customers can add their own cases on top.
    """

    __tablename__ = "eval_cases"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    meeting_id = Column(String, ForeignKey("meetings.id"), nullable=True)

    name = Column(String, nullable=False)
    task = Column(String, nullable=False, default=EvalTask.SUMMARY.value, index=True)
    input_payload = Column(JSON, nullable=False, default=dict)
    expected_output = Column(JSON, nullable=False, default=dict)

    provider = Column(String, nullable=True)  # provider the last run used
    model = Column(String, nullable=True)
    last_score = Column(Float, nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    meeting = relationship("Meeting")
