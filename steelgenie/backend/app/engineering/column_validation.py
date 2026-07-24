"""
Column Engine reliability checks -- Phase 1 (confidence scoring) and
Phase 6 (validation) of the mission brief.

Honest scope note: this module computes and surfaces signals a human can
act on (confidence scores, flagged anomalies). It does NOT claim to
guarantee any particular accuracy percentage -- that would require a much
larger corpus of real, ground-truth-labeled projects than what's available
to test against. What it does guarantee: nothing fails silently. A
column that looks wrong gets a low confidence score and/or a logged
validation issue instead of being rendered as if it were certain.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_column_confidence(
    *,
    canonical_member: dict,
    schedule_match_kind: str | None,
    has_beam_evidence: bool,
    n_source_extractions: int,
) -> float:
    """
    Confidence score in [0, 1] for one physical column in the Global Column
    Database, combining every signal actually available at sync time:

      - geometry / extraction confidence of the canonical source member
        (already computed per-member during extraction -- e.g.
        emit_symbol_columns' has_label_match + off_grid + beam-endpoint
        scoring for framing-plan columns)
      - whether the canonical member had a real label (not unlabeled/guessed)
      - schedule match: a real MARK match is strong corroboration; a
        profile/type-only match is weaker (applies to every column of that
        profile, not verified for this specific physical column)
      - beam connectivity: does *something else* (a beam) actually land at
        this column's position at some floor, or does it exist purely as an
        isolated plan symbol?
      - how many independent page extractions agree this column exists here
        (the same physical column showing up on both a foundation plan and
        a framing plan is much stronger evidence than appearing once)

    This does not replace per-member confidence computed at extraction time
    (main.py's emit_symbol_columns scoring) -- it's the GLOBAL confidence
    for the deduplicated column, which extraction-time scoring can't know
    (it only sees one page at a time).
    """
    score = 0.0

    member_confidence = canonical_member.get("confidence")
    if isinstance(member_confidence, (int, float)):
        score += 0.35 * min(1.0, max(0.0, member_confidence))
    else:
        geo = canonical_member.get("geometry") or {}
        if not geo.get("unlabeled") and not geo.get("size_unknown"):
            score += 0.25

    if schedule_match_kind == "mark":
        score += 0.30
    elif schedule_match_kind == "profile":
        score += 0.12

    if has_beam_evidence:
        score += 0.20

    if n_source_extractions >= 2:
        score += 0.15
    elif n_source_extractions >= 1:
        score += 0.05

    return round(min(1.0, score), 3)


def check_schedule_count_anomaly(
    project_id: str,
    *,
    columns_written: int,
    schedule_marks_found: int,
    db: Any,
) -> dict | None:
    """
    Compare the number of physical columns actually written to the Global
    Column Database against the number of distinct marks the Column
    Schedule says should exist. A large mismatch in either direction is a
    strong signal something is wrong with extraction (over-detection is
    the failure mode seen repeatedly this session; under-detection --
    e.g. a mark-radius regression silently dropping real columns -- is
    just as real a risk and just as important to catch).

    No schedule data at all means this check can't run (not every project
    will have a schedule page uploaded/extracted yet) -- returns None
    rather than a false anomaly.

    Writes a row to the `validation_issues` table (auto-created by the
    mock DB like any other table) instead of just logging, so the frontend
    can surface it rather than it only existing in server logs.
    """
    if schedule_marks_found <= 0:
        return None

    ratio = columns_written / schedule_marks_found if schedule_marks_found else 0.0
    # Same tolerance band in both directions -- over-detection (duplicates,
    # false positives) and under-detection (a too-strict filter silently
    # dropping real columns) are equally serious failure modes.
    if 0.7 <= ratio <= 1.3:
        return None

    issue = {
        "project_id": str(project_id),
        "type": "schedule_count_mismatch",
        "severity": "warning" if 0.5 <= ratio <= 2.0 else "error",
        "message": (
            f"Column Schedule lists {schedule_marks_found} distinct mark(s), "
            f"but extraction produced {columns_written} column(s) in the "
            f"Global Column Database (ratio {ratio:.2f}). "
            + ("Likely over-detection (duplicates or false positives)."
               if columns_written > schedule_marks_found else
               "Likely under-detection (a filter may be rejecting real columns).")
        ),
        "schedule_marks_found": schedule_marks_found,
        "columns_written": columns_written,
    }
    try:
        db.table("validation_issues").insert(issue).execute()
    except Exception as exc:
        logger.warning("Could not persist validation issue: %s", exc)
    logger.warning("[VALIDATION] %s", issue["message"])
    return issue


def validate_column_row(row: dict) -> list[str]:
    """
    Phase 1 item 7 / Phase 6 checks scoped to a single column row, run
    right before it would be written/rendered. Returns a list of problem
    codes (empty list = passes). Callers decide what to do with a failing
    row (reject entirely vs. flag+render with a warning) -- this function
    only detects, it doesn't decide policy.
    """
    problems = []

    if row.get("gx_ft") is None or row.get("gy_ft") is None:
        problems.append("missing_world_coordinate")

    base = row.get("base_elev_ft")
    top = row.get("top_elev_ft")
    if base is not None and top is not None:
        if top < base:
            problems.append("impossible_elevation")  # column shrinks going up
        if abs(top - base) < 1e-6 and base != 0:
            # Zero-height column above grade with no evidence of ever
            # continuing anywhere -- likely an isolated/orphan detection,
            # not a real structural column (a real ground-floor column with
            # base==top==0 is a legitimate "not yet connected to framing"
            # case and shouldn't be flagged the same way).
            problems.append("zero_height_above_grade")

    if not row.get("mark") and not row.get("profile"):
        problems.append("no_mark_no_profile")  # nothing to identify this column by at all

    return problems
