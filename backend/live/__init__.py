"""Live captions and translation for meetings in progress.

See docs/live-interpretation/ARCHITECTURE.md. One ``LiveRuntime`` per running
session lives in this process; the transcript it produces is ordinary
``TranscriptSegment`` rows, so the post-meeting pipeline needs no live path.
"""
