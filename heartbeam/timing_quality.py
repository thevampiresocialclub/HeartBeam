"""Review tolerances; these never relax strict editing or change saved timing."""

OVERLAP_WARNING_MS = 100


def overlap_needs_review(start_ms, end_ms, next_start_ms):
    """Ignore small boundary overlaps, but always flag backwards word order."""
    return next_start_ms < start_ms or end_ms-next_start_ms > OVERLAP_WARNING_MS + 1e-6
