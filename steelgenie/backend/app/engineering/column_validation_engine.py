"""
Column Validation Engine.

Sits between "a shape looks like a column" (detect_column_symbols' geometry
matching + the Symbol Classification Engine's category call) and "this is
allowed to become a real column" (written into a page's members, and later
the Global Column Database). Geometry-only detection was shown live to
still let circular annotation bubbles, detail markers, and stray marks
through on real drawings -- root cause: some PDF exporters draw a circle as
many short straight line segments rather than a real bezier/arc primitive,
so it can dodge the classifier's has_curve-based rules without actually
being a curve in the PDF's own path data. Rather than chasing shape
detection further, this module cross-checks every candidate against
independent STRUCTURAL evidence -- the same evidence a structural engineer
would actually use to tell a real column mark from sheet furniture:

  - grid intersection proximity   (real columns sit on/near the structural grid)
  - footing/column relationship   (the Symbol Classification Engine's own
                                    category + confidence)
  - mark-label match, distance-weighted (not just "some mark was in range")
  - beam connectivity             (framing plans only)
  - Column Schedule corroboration (global/cross-page stage only)

No single weak signal decides accept or reject alone. A candidate is only
rejected when its COMBINED score falls below REJECT_FLOOR -- i.e. multiple
independent signals are simultaneously absent. This is intentionally
conservative: a real column with weak evidence stays in as "need_review"
(recoverable -- a human notices a missing/dim column and can promote it);
a false positive silently entering the Global Column Database is much
harder to catch after the fact.
"""
from __future__ import annotations

# Below this combined score, a candidate is rejected outright -- not even
# written as "need_review". Calibrated deliberately low: one real signal
# (e.g. a mark sitting right on the symbol, or a confident steel_column
# classification) is enough to clear it even with everything else absent.
REJECT_FLOOR = 0.22

# Between REJECT_FLOOR and this, a candidate is written but flagged
# need_review rather than active -- kept in the database (visible, editable)
# but not presented as a confirmed structural fact.
REVIEW_FLOOR = 0.55


def score_column_candidate(
    *,
    has_grid_intersection: bool,
    grid_snap_dist_pt: float | None,
    bay_size_pt: float | None,
    classifier_category: str | None,
    classifier_confidence: float | None,
    nearest_mark_dist_pt: float | None,
    mark_radius_pt: float | None,
    beam_end_count: int,
    is_foundation_plan: bool,
    schedule_matched: bool = False,
) -> tuple[float, dict, bool]:
    """
    Composite structural-context score in [0, 1] for one column candidate.

    Callers that don't have a signal available yet (e.g. page-level
    extraction has no Column Schedule data -- that only exists once every
    page of the project has been collected at registration.py's global
    sync stage) simply omit/default it; a missing signal contributes 0
    rather than being estimated, so it never falsely inflates a score.

    Returns (score, signal breakdown dict for logging/debugging, passed).
    `passed` is score >= REJECT_FLOOR -- callers decide what to do with a
    passing-but-low score (typically: write as need_review, not active).
    """
    signals: dict[str, float] = {}

    # 1. Grid intersection proximity (weight 0.20). Real structural columns
    #    are placed AT grid intersections; annotation bubbles, detail
    #    markers, and dimension ticks are scattered wherever there's room
    #    on the sheet, with no relationship to the grid at all.
    if has_grid_intersection and grid_snap_dist_pt is not None and bay_size_pt:
        closeness = max(0.0, 1.0 - min(1.0, grid_snap_dist_pt / max(bay_size_pt, 1.0)))
        signals["grid_intersection"] = 0.20 * closeness
    else:
        signals["grid_intersection"] = 0.0

    # 2. Footing/column relationship (weight 0.20), from the Symbol
    #    Classification Engine's own category + confidence -- that module
    #    is what's actually responsible for shape-vs-meaning, so this
    #    trusts its confidence directly instead of re-deriving it.
    # Phase 4 taxonomy (column_symbol_classifier.py / column_symbol_library.py)
    # -- every category that represents an actual physical column base,
    # not just the original steel_column/footing_isolated/pile_cap set.
    _COLUMN_CATEGORIES = {
        "steel_column", "footing_isolated", "pile_cap", "concrete_column",
        "hss_column", "pipe_column", "built_up_column", "pedestal",
    }
    if classifier_category in _COLUMN_CATEGORIES:
        signals["footing_relationship"] = 0.20 * (classifier_confidence or 0.5)
    else:
        signals["footing_relationship"] = 0.0

    # 3. Mark-label match (weight 0.25), distance-weighted. A mark sitting
    #    right on top of the symbol is much stronger evidence than one at
    #    the edge of the mark-radius filter's tolerance (which is itself
    #    already a loose, density-calibrated radius -- see
    #    filter_foundation_symbols_by_marks -- not a tight one).
    if nearest_mark_dist_pt is not None and mark_radius_pt:
        closeness = max(0.0, 1.0 - min(1.0, nearest_mark_dist_pt / max(mark_radius_pt, 1.0)))
        signals["mark_match"] = 0.25 * closeness
    else:
        signals["mark_match"] = 0.0

    # 4. Beam connectivity (weight 0.15). Only meaningful on framing plans
    #    -- a foundation plan has no beams by definition, so this signal is
    #    given neutral half-credit there rather than penalizing every
    #    single foundation-plan candidate for something that sheet type
    #    structurally never has.
    if is_foundation_plan:
        signals["beam_connectivity"] = 0.15 * 0.5
    else:
        signals["beam_connectivity"] = 0.15 * min(1.0, beam_end_count / 2.0)

    # 5. Column Schedule corroboration (weight 0.20). Only available once
    #    every page of the project has been collected -- page-level callers
    #    (main.py, before any other page is even known) simply pass False;
    #    registration.py's global sync stage passes the real answer once
    #    schedule data has been parsed and matched by mark.
    signals["schedule_match"] = 0.20 if schedule_matched else 0.0

    score = round(min(1.0, sum(signals.values())), 3)
    return score, signals, score >= REJECT_FLOOR
