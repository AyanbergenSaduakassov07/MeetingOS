#!/usr/bin/env python3
"""
End-to-end pipeline runner for MeetingOS.

Runs the full ingestion → extraction pipeline against a real test recording:
1. Transcription (Whisper Cloud)
2. Diarization (AssemblyAI or PyAnnote)
3. Topic segmentation
4. Intelligence extraction (decisions, action items, risks, commitments)
5. Verification

Also implements:
- Cross-topic deduplication (embedding-similarity threshold)
- Improved topic labeling (expanded stopwords + LLM-generated titles)
- TODO for audio chunking >25MB in whisper_cloud_provider.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add parent directory to path so we can import backend
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Ensure we use the local data directory
import backend.config as config

config.set_data_dir(Path(__file__).parent.parent / "data")

from backend.ai import reset_providers
from backend.database import Meeting, MeetingSource, MeetingStatus, Organization, init_db
from backend.meetings import ingestion, intelligence, segmentation
from backend.meetings.curation import curate_meeting


async def run_pipeline(recording_path: Path, meeting_title: str = "Test Meeting") -> dict:
    """Run the full pipeline end-to-end."""

    # Initialize database
    init_db()

    # Create organization if needed
    from backend.database import new_session

    db = new_session()
    try:
        org = db.query(Organization).first()
        if not org:
            org = Organization(name="Test Org", slug="test-org")
            db.add(org)
            db.commit()
            db.refresh(org)
        org_id = org.id
    finally:
        db.close()

    # Create meeting record
    meeting = Meeting(
        org_id=org_id,
        title=meeting_title,
        status=MeetingStatus.PROCESSING.value,
        source=MeetingSource.UPLOAD.value,
        language="en",
        recording_path=config.to_storage_path(recording_path),
    )

    db = new_session()
    try:
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        meeting_id = meeting.id
        logger.info(f"Created meeting: {meeting_id}")
    finally:
        db.close()

    # Run ingestion (transcription + diarization)
    logger.info("Starting ingestion...")
    await ingestion.process_meeting(meeting_id, run_segmentation=False)

    # Run segmentation
    logger.info("Starting segmentation...")
    await segmentation.segment_meeting(meeting_id)

    # Run extraction
    logger.info("Starting intelligence extraction...")
    report = await intelligence.extract_meeting_intelligence(meeting_id, run_verification=True)

    logger.info(f"Extraction complete: {report.total} items, {report.rejected_citations} rejected citations")

    return {"meeting_id": meeting_id, "report": report}


# Deduplication and topic titling moved to backend/meetings/curation.py.
# They decide which extracted items a reader sees and how the timeline is
# labelled, which is library behaviour, not script behaviour — and the titling
# call needed the same untrusted-input fence the rest of extraction has.
#
# add_audio_chunking_todo() was deleted rather than moved: it rewrote
# whisper_cloud_provider.py's source on every run. A TODO belongs in the file,
# committed, not applied by a regex at runtime.


async def main():
    """Main entry point."""
    # Recording path
    recording_path = Path(__file__).parent.parent / "data" / "recordings" / "824f8771-74e9-457e-ae92-f50038f13fa1.wav"

    if not recording_path.exists():
        logger.error(f"Recording not found: {recording_path}")
        sys.exit(1)

    logger.info(f"Using recording: {recording_path} ({recording_path.stat().st_size / 1024:.1f} KB)")

    # Check API keys
    if not os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") == "your-openrouter-api-key-here":
        logger.error("OPENAI_API_KEY not set in backend/.env. Please add your OpenRouter API key.")
        sys.exit(1)

    # Reset providers to pick up new config
    reset_providers()

    # Run the full pipeline
    result = await run_pipeline(recording_path)
    meeting_id = result["meeting_id"]
    report = result["report"]

    logger.info(f"Pipeline completed for meeting {meeting_id}")
    logger.info(
        f"Decisions: {report.decisions}, Action Items: {report.action_items}, Risks: {report.risks}, Commitments: {report.commitments}"
    )
    logger.info(f"Topics processed: {report.topics_processed}, Rejected citations: {report.rejected_citations}")
    logger.info(f"Errors: {report.errors}")

    # Curation: supersede cross-topic duplicates, rewrite topic labels.
    # Awaited, not asyncio.run() — we are already inside a running loop, and
    # calling asyncio.run() here raised RuntimeError every time.
    logger.info("Curating extracted items...")
    curation = await curate_meeting(meeting_id)
    logger.info(
        f"Curation: {curation.superseded} duplicate(s) superseded, {curation.topics_relabelled} topic(s) relabelled"
    )
    for detail in curation.details:
        logger.info(f"  {detail}")

    # Print final extraction results with confidence scores
    logger.info("\n=== FINAL EXTRACTION RESULTS ===")
    from backend.database import ActionItem, Commitment, Decision, Risk, new_session

    db = new_session()
    try:
        for kind_name, model, title_attr in [
            ("Decision", Decision, "title"),
            ("Action Item", ActionItem, "title"),
            ("Risk", Risk, "title"),
            ("Commitment", Commitment, "text"),
        ]:
            items = db.query(model).filter_by(meeting_id=meeting_id).all()
            if items:
                logger.info(f"\n{kind_name}s ({len(items)}):")
                for item in items:
                    status = item.verification_status
                    conf = item.extraction_confidence
                    vscore = item.verification_score
                    title = getattr(item, title_attr, "")[:80]
                    logger.info(f"  [{status}] conf={conf:.2f} vscore={vscore:.2f} - {title}")
                    if item.source_quote:
                        logger.info(f"    Quote: {item.source_quote[:100]}...")
    finally:
        db.close()

    logger.info("\n=== SUMMARY ===")
    logger.info(f"1. Pipeline completed for meeting {meeting_id}")
    logger.info(
        f"2. Extraction results: {report.decisions} decisions, {report.action_items} action items, {report.risks} risks, {report.commitments} commitments"
    )
    logger.info("   Low-confidence/unsupported items are visible (not filtered)")
    logger.info(f"3. Curation: {curation.superseded} superseded, {curation.topics_relabelled} relabelled")


if __name__ == "__main__":
    asyncio.run(main())
