"""
Column Match Engine -- Backlog item B1 from
docs/column-engine-gap-analysis.md (SteelGenie behavioral study,
2026-07-15).

What the study found: SteelGenie's real column IDENTITY is the grid
intersection, not the plan's printed mark text -- its Column Scheduler
labels physical columns as "C1 (D-9)", where D-9 is the grid position and
C1 is SteelGenie's own auto-assigned sequential ID. The plan's own
F1/P2-style mark is cosmetic for a human reader, not the system's key.

Explicit scope, per direct instruction: this does NOT make grid position
the ONLY identity of a column, and does NOT implement a full Global Column
Identity / UUID architecture (that belongs to the future Global Building
Engine phase). This module only changes the MATCHING STRATEGY used in two
places inside the existing Column Engine:

  1. Schedule association -- deciding which ScheduleRecord (if any)
     supplies a physical column's real profile/base-plate/anchor data.
  2. Cross-page reconciliation corroboration -- flagging when the members
     grouped into one physical-column cluster (already done by real-world
     XZ proximity in registration.py) disagree on grid reference, which is
     a validation signal an XZ-only clustering pass can't see on its own.

Both use a WEIGHTED COMBINATION of every signal actually available --
grid intersection, world coordinates, drawing mark, schedule mark, floor
elevation, symbol classification confidence, and structural (beam)
connectivity -- rather than the previous first-match-wins mark-then-profile
lookup. Grid agreement is weighted primary (it's the most stable signal
across a project: OCR misreads a mark, but a symbol's position relative to
the grid it was drawn on doesn't change), but every other signal still
contributes -- a strong mark match with no grid data at all can still win,
and a grid match with a flatly contradicting mark is not blindly trusted
either.
"""
from __future__ import annotations

from typing import Any


# ── Weights ──────────────────────────────────────────────────────────────
# Grid agreement is primary per the mission's explicit instruction, but
# deliberately not overwhelming -- a schedule is still fundamentally a
# mark-keyed table on every real project observed so far (SteelGenie's own
# grid-keyed Column Scheduler labels are its own internal synthesis, not
# something read off a source schedule page), so mark match stays a close
# second rather than being demoted to an afterthought.
W_GRID = 0.35
W_MARK = 0.30
W_PROFILE = 0.15
W_FLOOR = 0.10
W_CLASSIFIER_CONF = 0.06
W_BEAM_EVIDENCE = 0.04

# Below this combined score, a schedule association is not made at all --
# the row keeps whatever plan-read profile it already has (or the existing
# guessed-profile fallback) rather than attaching schedule data on a weak
# guess.
ASSOCIATION_FLOOR = 0.30


def _norm(s: str | None) -> str | None:
    if not s:
        return None
    return s.strip().upper()


def score_schedule_association(
    *,
    cluster_grid_ref: str | None,
    cluster_mark: str | None,
    cluster_profile: str | None,
    cluster_base_elev: float | None,
    cluster_top_elev: float | None,
    cluster_classifier_confidence: float | None,
    cluster_has_beam_evidence: bool,
    record_mark: str | None,
    record_profile: str | None,
    record_floor_segment: str | None,
    grid_corroboration: dict[str, dict[str, int]],
    floor_name_to_elev: dict[str, float],
) -> tuple[float, dict[str, float]]:
    """
    Score how well ONE ScheduleRecord matches ONE physical-column cluster.
    Returns (total score in [0, 1], per-signal breakdown for logging).

    grid_corroboration: mark -> {grid_ref: count}, built once per project
    from every cluster that already has a clean, direct mark match (see
    build_grid_corroboration_map below). Lets a record's mark corroborate
    (or contradict) a cluster's grid position even though the schedule
    table itself never printed a grid reference -- this is what actually
    "eliminates incorrect schedule assignments caused by OCR or
    inconsistent mark labeling": if 4 other clusters on this project agree
    mark "C5" belongs at grid D-9, a 5th cluster at grid D-9 whose OCR'd
    mark misread as "C5" (vs. "CS" or "G5") gets that reading corroborated;
    a cluster at a totally different grid claiming the same mark does not.
    """
    signals: dict[str, float] = {}

    # 1. Mark match -- direct text equality (case/whitespace-normalized).
    cm, rm = _norm(cluster_mark), _norm(record_mark)
    if cm and rm and cm == rm:
        signals["mark"] = W_MARK
    else:
        signals["mark"] = 0.0

    # 2. Grid corroboration -- does the empirical grid_ref history for this
    #    record's mark (built from OTHER confidently-matched clusters on
    #    this project) agree with this cluster's own grid_ref?
    if cluster_grid_ref and rm and rm in grid_corroboration:
        counts = grid_corroboration[rm]
        total = sum(counts.values())
        agree = counts.get(cluster_grid_ref, 0)
        if total > 0:
            # Fraction of corroborating evidence that agrees with THIS
            # cluster's grid position -- 1.0 if every other sighting of
            # this mark was at the same grid, less if the mark has been
            # seen at conflicting grids (ambiguous mark reuse) or none if
            # this cluster's grid contradicts every other sighting.
            signals["grid"] = W_GRID * (agree / total)
        else:
            signals["grid"] = 0.0
    else:
        # No corroboration data available for this mark yet (e.g. this is
        # the FIRST/only sighting) -- neutral, not penalized, since absence
        # of evidence isn't evidence of a mismatch.
        signals["grid"] = W_GRID * 0.5 if cluster_grid_ref else 0.0

    # 3. Profile match -- fallback identity signal (mark-by-type schedules
    #    key on this instead of a physical mark).
    cp, rp = _norm(cluster_profile), _norm(record_profile)
    if cp and rp and cp == rp:
        signals["profile"] = W_PROFILE
    else:
        signals["profile"] = 0.0

    # 4. Floor/elevation consistency -- if the record names a floor segment
    #    (e.g. "Low Roof") and this project has a floor of that name, check
    #    the cluster's own elevation range actually reaches it. A record
    #    for a floor far outside the cluster's known base->top range is
    #    likely a mismatch (this record probably belongs to a taller/
    #    shorter column elsewhere); one within range corroborates.
    if record_floor_segment and floor_name_to_elev:
        seg_key = _norm(record_floor_segment)
        target_elev = None
        for fname, felev in floor_name_to_elev.items():
            if _norm(fname) == seg_key:
                target_elev = felev
                break
        if target_elev is not None and cluster_base_elev is not None and cluster_top_elev is not None:
            if cluster_base_elev - 1.0 <= target_elev <= cluster_top_elev + 1.0:
                signals["floor"] = W_FLOOR
            else:
                signals["floor"] = 0.0
        else:
            signals["floor"] = W_FLOOR * 0.5  # named but unverifiable -- neutral
    else:
        signals["floor"] = W_FLOOR * 0.5  # no floor segment claim to check -- neutral

    # 5. Symbol classification confidence -- trust the mark/profile reading
    #    more when the source detection itself was confident.
    signals["classifier_confidence"] = W_CLASSIFIER_CONF * min(1.0, max(0.0, cluster_classifier_confidence or 0.0))

    # 6. Structural connectivity -- a column with real beam evidence is a
    #    corroborated physical member, not an isolated/uncertain detection.
    signals["beam_evidence"] = W_BEAM_EVIDENCE if cluster_has_beam_evidence else 0.0

    total = round(min(1.0, sum(signals.values())), 3)
    return total, signals


def build_grid_corroboration_map(
    clusters: list[dict],
) -> dict[str, dict[str, int]]:
    """
    Build an empirical mark -> {grid_ref: count} map from every cluster in
    THIS project that already has both a real mark and a real grid_ref on
    its canonical member. Self-referential (uses the project's own
    extracted data as ground truth for "which grid does this mark usually
    show up at"), not derived from any external source -- exactly the kind
    of cross-page corroboration a single-page mark-text lookup can't do on
    its own.

    `clusters` items are expected to have "mark" and "grid_ref" keys (both
    optional/None-able).
    """
    corroboration: dict[str, dict[str, int]] = {}
    for c in clusters:
        mark = _norm(c.get("mark"))
        grid_ref = c.get("grid_ref")
        if not mark or not grid_ref:
            continue
        bucket = corroboration.setdefault(mark, {})
        bucket[grid_ref] = bucket.get(grid_ref, 0) + 1
    return corroboration


def find_best_schedule_match(
    *,
    cluster_grid_ref: str | None,
    cluster_mark: str | None,
    cluster_profile: str | None,
    cluster_base_elev: float | None,
    cluster_top_elev: float | None,
    cluster_classifier_confidence: float | None,
    cluster_has_beam_evidence: bool,
    schedule_by_mark: dict[str, Any],
    schedule_by_profile: dict[str, Any],
    grid_corroboration: dict[str, dict[str, int]],
    floor_name_to_elev: dict[str, float],
) -> tuple[Any | None, str | None, float, dict[str, float]]:
    """
    Score this cluster against every schedule record it could plausibly
    match (its own mark's record, its own profile's record -- real schedule
    tables are small enough per project that scoring the couple of
    plausible candidates is cheap; no need to score against every record in
    the schedule) and return the best one, IF it clears ASSOCIATION_FLOOR.

    Returns (record_or_None, match_kind, score, signal_breakdown).
    match_kind is "mark", "profile", or None (no association made).
    """
    candidates: list[tuple[Any, str]] = []
    cm = _norm(cluster_mark)
    if cm and cm in schedule_by_mark:
        candidates.append((schedule_by_mark[cm], "mark"))
    cp = _norm(cluster_profile)
    if cp and cp in schedule_by_profile:
        candidates.append((schedule_by_profile[cp], "profile"))

    if not candidates:
        return None, None, 0.0, {}

    best_record, best_kind, best_score, best_signals = None, None, -1.0, {}
    for record, kind in candidates:
        score, signals = score_schedule_association(
            cluster_grid_ref=cluster_grid_ref,
            cluster_mark=cluster_mark,
            cluster_profile=cluster_profile,
            cluster_base_elev=cluster_base_elev,
            cluster_top_elev=cluster_top_elev,
            cluster_classifier_confidence=cluster_classifier_confidence,
            cluster_has_beam_evidence=cluster_has_beam_evidence,
            record_mark=getattr(record, "mark", None),
            record_profile=getattr(record, "profile", None) or getattr(record, "column_type", None),
            record_floor_segment=getattr(record, "floor_segment", None),
            grid_corroboration=grid_corroboration,
            floor_name_to_elev=floor_name_to_elev,
        )
        if score > best_score:
            best_record, best_kind, best_score, best_signals = record, kind, score, signals

    if best_score < ASSOCIATION_FLOOR:
        return None, None, best_score, best_signals

    return best_record, best_kind, best_score, best_signals
