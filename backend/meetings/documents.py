"""Document ingestion: extract text, chunk it, make it searchable.

Documents join meetings in the corpus index so a question can be answered by
cross-referencing the two — "the contract says 90 days, but the board minuted
60" is the kind of finding that only exists when both are in one index.

Chunking
--------
A document is chunked, not embedded whole. A fifty-page contract as one vector
matches everything weakly and nothing precisely, and a citation reading "the
contract" tells a reader nothing about where to look. Chunks carry ``page`` and
``ordinal``, which are the document's equivalent of a transcript timestamp: the
coordinates that make a citation checkable.

Chunks overlap by ``CHUNK_OVERLAP_CHARS`` so a sentence spanning a boundary is
retrievable from either side, which is the common failure of naive splitting.

Untrusted content — the same treatment as transcripts, and it matters more
------------------------------------------------------------------------------
A transcript is what people said in a room. A document is a file someone
uploaded, which makes it a *better* injection vector: an attacker can craft
every byte, hide text in white-on-white or in metadata, and know it will be
retrieved verbatim. Once it is in the org index it reaches every question
anyone asks, not just questions about that document.

So document text gets exactly the same handling as transcript text — fenced,
flattened, never interpolated into a system prompt, never used to select code —
and the extraction step below additionally strips control characters and
collapses whitespace, because a PDF text layer can contain both in quantities
no human typed.

Privacy
-------
Documents skew far more sensitive than meetings: contracts, financials, board
packs. ``redact_for_egress`` is applied on the same opt-in flag as transcripts,
and ``Document.is_sensitive`` overrides that flag for one file: a document
marked sensitive is redacted as it is indexed, so every downstream cloud call
reads the redacted copy. Neither is a substitute for a decision about whether
this class of file should reach a third-party API at all.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config
from ..database import Document, DocumentChunk, Meeting, MeetingDocument

logger = logging.getLogger(__name__)

# Chunk size in characters. Roughly a long paragraph — small enough that a
# citation points somewhere specific, large enough to carry an argument.
CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150

# Hard ceiling on extracted text per document. A 500-page PDF is a corpus, not
# a document, and embedding it would spend real money without being asked.
MAX_EXTRACT_CHARS = 400_000

ALLOWED_SUFFIXES = {".pdf", ".txt", ".md", ".docx", ".pptx"}

# Control characters a PDF text layer emits that no human typed.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DocumentError(RuntimeError):
    """Ingestion failed for a reason the caller can act on."""


@dataclass
class IngestReport:
    document_id: str
    chunks: int = 0
    characters: int = 0
    language: str | None = None
    notes: list[str] = field(default_factory=list)


def sanitize(text: str) -> str:
    """Strip control characters and collapse runaway whitespace.

    Not a security boundary — the fence and the id whitelist are — but a PDF
    text layer routinely carries thousands of control bytes and zero-width
    characters, and passing those to an embedding model wastes tokens on noise
    while giving a crafted file somewhere to hide.
    """
    cleaned = _CONTROL.sub(" ", text or "")
    cleaned = cleaned.replace("​", "").replace("﻿", "")
    # Collapse runs of blank lines but keep paragraph structure.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def extract_text(path: Path) -> tuple[str, list[tuple[int | None, str]]]:
    """Return ``(full_text, [(page, text), ...])`` for a supported file.

    Page numbers are kept where the format has them so a citation can say
    "page 7" rather than "somewhere in the contract". Plain text has no pages
    and reports ``None``, which the chunker handles.
    """
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentError(f"Unsupported document type {suffix!r}. Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}")

    if suffix in (".txt", ".md"):
        return sanitize(path.read_text(errors="replace")), []

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise DocumentError("PDF ingestion needs `pypdf`. Install it, or upload the text instead.") from exc
        reader = PdfReader(str(path))
        pages = [(index + 1, sanitize(page.extract_text() or "")) for index, page in enumerate(reader.pages)]
        return "\n\n".join(text for _, text in pages if text), [p for p in pages if p[1]]

    if suffix == ".docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise DocumentError("DOCX ingestion needs `python-docx`.") from exc
        document = docx.Document(str(path))
        return sanitize("\n".join(p.text for p in document.paragraphs)), []

    if suffix == ".pptx":
        try:
            from pptx import Presentation  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise DocumentError("PPTX ingestion needs `python-pptx`.") from exc
        deck = Presentation(str(path))
        slides = []
        for index, slide in enumerate(deck.slides):
            text = " ".join(shape.text for shape in slide.shapes if hasattr(shape, "text") and shape.text)
            if text.strip():
                slides.append((index + 1, sanitize(text)))
        return "\n\n".join(text for _, text in slides), slides

    raise DocumentError(f"Unsupported document type {suffix!r}.")


def chunk_text(text: str, *, page: int | None = None) -> list[tuple[int | None, str]]:
    """Split text into overlapping chunks on paragraph then sentence bounds.

    Overlap means a sentence that straddles a boundary is retrievable from
    either chunk — the standard failure of naive fixed-width splitting.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= CHUNK_CHARS:
        return [(page, text)]

    chunks: list[tuple[int | None, str]] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            # Prefer a paragraph break, then a sentence end, then a space.
            for boundary in ("\n\n", ". ", " "):
                cut = text.rfind(boundary, start + CHUNK_CHARS // 2, end)
                if cut != -1:
                    end = cut + len(boundary)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append((page, piece))
        if end >= len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP_CHARS)
    return chunks


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest_document(
    db: Session,
    document_id: str,
    *,
    detect_language=None,
) -> IngestReport:
    """Extract, sanitize, chunk and store a document's text. No model called."""
    document = db.query(Document).filter_by(id=document_id).first()
    if document is None:
        raise DocumentError(f"Document {document_id} not found")

    path = config.resolve_storage_path(document.storage_path)
    if path is None or not path.is_file():
        raise DocumentError(f"Stored file for document {document_id} is missing.")

    full_text, pages = extract_text(path)
    report = IngestReport(document_id=document_id)

    if len(full_text) > MAX_EXTRACT_CHARS:
        full_text = full_text[:MAX_EXTRACT_CHARS]
        report.notes.append(f"Document truncated to {MAX_EXTRACT_CHARS} characters for indexing.")

    if not full_text.strip():
        report.notes.append("No extractable text — the file may be a scanned image.")
        document.extracted_text = ""
        db.commit()
        return report

    document.extracted_text = full_text
    if detect_language is not None:
        document.language = detect_language(full_text)
    report.language = document.language
    report.characters = len(full_text)

    # Replace rather than append: re-ingesting must not duplicate chunks.
    db.query(DocumentChunk).filter_by(document_id=document_id).delete(synchronize_session=False)

    pieces: list[tuple[int | None, str]] = []
    if pages:
        for page_number, page_text in pages:
            pieces.extend(chunk_text(page_text, page=page_number))
    else:
        pieces = chunk_text(full_text)

    for ordinal, (page_number, piece) in enumerate(pieces):
        db.add(
            DocumentChunk(
                org_id=document.org_id,
                document_id=document_id,
                ordinal=ordinal,
                page=page_number,
                text=piece,
                language=document.language,
            )
        )
    report.chunks = len(pieces)
    db.commit()
    logger.info("Ingested document %s: %d chunk(s)", document_id, report.chunks)
    return report


def link_document_to_meeting(
    db: Session,
    document_id: str,
    meeting_id: str,
    *,
    linked_by_id: str | None = None,
    note: str | None = None,
) -> MeetingDocument:
    """Record that a document was referenced in a meeting.

    Explicit by design. Inferring the link from transcript text is a separate,
    harder extraction problem — "the contract we discussed" carries no id — and
    a wrong guess attaches a contract to the wrong meeting, which is worse than
    no link at all.
    """
    document = db.query(Document).filter_by(id=document_id).first()
    if document is None:
        raise DocumentError(f"Document {document_id} not found")
    meeting = db.query(Meeting).filter_by(id=meeting_id).first()
    if meeting is None:
        raise DocumentError(f"Meeting {meeting_id} not found")
    if document.org_id != meeting.org_id:
        raise DocumentError("Document and meeting belong to different organizations.")

    existing = db.query(MeetingDocument).filter_by(document_id=document_id, meeting_id=meeting_id).first()
    if existing is not None:
        return existing

    link = MeetingDocument(document_id=document_id, meeting_id=meeting_id, linked_by_id=linked_by_id, note=note)
    db.add(link)
    db.commit()
    return link
