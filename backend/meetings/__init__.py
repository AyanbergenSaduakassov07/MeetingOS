"""Meeting processing pipeline: ingestion, segmentation, intelligence, verification."""

from .copilot import CopilotAnswer, CopilotError, answer_question
from .ingestion import process_meeting, schedule_processing
from .intelligence import ExtractionReport, extract_meeting_intelligence
from .segmentation import detect_boundaries, segment_meeting
from .verifier import VerificationReport, verify_meeting

__all__ = [
    "CopilotAnswer",
    "CopilotError",
    "ExtractionReport",
    "VerificationReport",
    "answer_question",
    "detect_boundaries",
    "extract_meeting_intelligence",
    "process_meeting",
    "schedule_processing",
    "segment_meeting",
    "verify_meeting",
]
