"""
Column Symbol Classification Engine -- Phase 1 gatekeeper for the Column
Engine, per docs/column-engine-architecture.md.

Runs on the CLUSTERED symbol candidates main.py's detect_column_symbols()
already produces (shape-matched, deduplicated) -- this module's job is not
to find shapes, it's to decide what each already-found shape actually
REPRESENTS before it's allowed to become a column candidate. Everything
downstream (mark-radius filtering, emit_symbol_columns, the Global Column
Database) only ever sees symbols this module has approved.

Honest scope note: some of the requested categories (pile cap vs isolated
footing vs equipment pad, specifically) are genuinely difficult to
distinguish from vector geometry alone without a much richer signal set
(actual pile symbols, hatch-pattern semantics, or a real vision model).
What's implemented here is a defensible, multi-signal heuristic classifier
using every signal realistically available from a PDF's vector + text
layers -- geometry, aspect ratio, size relative to the sheet's own median
footing size, dash/fill state, and nearby text pattern (mark vs detail
callout vs dimension string vs annotation word). It is NOT a trained
classifier and does not claim category-by-category accuracy guarantees;
its real job, and the thing it's verified against real drawings for, is
correctly rejecting the specific false-positive patterns that were
actually observed this session (circular grid bubbles, detail/section
callout bubbles, dimension ticks) while retaining the real footing/column
symbols.
"""
from __future__ import annotations

import math
import re


# ── Categories ───────────────────────────────────────────────────────────
STEEL_COLUMN = "steel_column"
FOOTING_ISOLATED = "footing_isolated"
FOOTING_WALL = "footing_wall"
PILE_CAP = "pile_cap"
EQUIPMENT_PAD = "equipment_pad"
ANNOTATION = "annotation"
CALLOUT_BUBBLE = "callout_bubble"
DETAIL_MARKER = "detail_marker"
DIMENSION_SYMBOL = "dimension_symbol"
GRID_BUBBLE = "grid_bubble"
CENTERLINE_NOTE = "centerline_note"
MISC = "misc"

# Phase 4 taxonomy (2026-07-15 mission: "Instead of one generic 'column',
# classify symbols into categories"). These map 1:1 onto
# column_symbol_library.py's expected_member_type field so a Symbol Library
# match can drive a more specific category than the shape/text rules alone
# would produce. Honest scope note: geometry + nearby text genuinely cannot
# always tell steel vs. concrete vs. built-up apart with certainty -- these
# categories are assigned when the Symbol Library match is confident enough
# to justify them (see the library-match rule below), not guessed.
CONCRETE_COLUMN = "concrete_column"
HSS_COLUMN = "hss_column"
PIPE_COLUMN = "pipe_column"
BUILT_UP_COLUMN = "built_up_column"
PEDESTAL = "pedestal"
PILE = "pile"
FOUNDATION_ONLY = "foundation_only"
EQUIPMENT_SUPPORT = "equipment_support"
ANCHOR_POINT = "anchor_point"
REFERENCE_MARKER = "reference_marker"
UNKNOWN = "unknown"

# A column's base is marked by its footing symbol on a foundation plan --
# CalSteel's architecture treats "steel column" and "isolated footing /
# pile cap" (and now every other physically-a-column category below) as
# the SAME kind of thing for database-write purposes, just drawn/typed
# differently depending on sheet type and firm convention. Wall footings,
# equipment pads/supports, anchor points with no column of their own, bare
# reference markers, and every annotation/callout/dimension/grid-bubble
# category represent something that is NOT itself a physical column and
# must never produce a column candidate.
CATEGORIES_THAT_BECOME_COLUMNS = {
    STEEL_COLUMN, FOOTING_ISOLATED, PILE_CAP,
    CONCRETE_COLUMN, HSS_COLUMN, PIPE_COLUMN, BUILT_UP_COLUMN, PEDESTAL,
}

# Real detail/section callout convention on structural sheets: a number or
# letter, a slash, then a sheet reference -- "3/S301", "A/S502", "1/S-301".
_DETAIL_REF_RE = re.compile(r'^[A-Z0-9]{1,3}\s*/\s*[A-Z]?-?\d{2,4}[A-Z.]*$', re.IGNORECASE)

# A bare grid-line label -- "1", "12", "A", "B.6", "AA" -- is what sits
# inside a GRID bubble at the edge of a sheet, not a column mark. Real
# column/footing marks always have a letter PREFIX (F1, C2, P3); a bare
# number or a bare 1-2 letter token with no digit-prefixed-by-letter
# pattern is much more likely a grid label.
_GRID_LABEL_RE = re.compile(r'^(?:[A-Z]{1,2}(?:\.\d+)?|\d{1,2}(?:\.\d+)?)$', re.IGNORECASE)

# Column/Footing mark pattern: C1, CC1, CC2, F1, P1, PC1, CP1, PU1, POST1, BP1
_MARK_RE = re.compile(r'^(?:[A-Z]{1,3}\d{1,4}[A-Z]?)$', re.IGNORECASE)

# AISC / Structural steel profile callouts (HSS, W, WT, HP, PIPE, C, MC, L)
_PROFILE_RE = re.compile(
    r'^(?:(?:W|WT|HP|C|MC|L)\s*\d+(?:\.\d+)?\s*X\s*\d+(?:\.\d+)?(?:\s*X\s*[\d./]+)?|'
    r'HSS\s*\d+(?:\.\d+)?\s*X\s*\d+(?:\.\d+)?(?:\s*X\s*[\d./]+)?|'
    r'PIPE\s*\d+(?:\.\d+)?(?:\s*STD|\s*X-?S)?)$',
    re.IGNORECASE
)

# Explicit concrete column / concrete pier marks (e.g. CC1, CC2, CP1, PIER1)
_CONCRETE_MARK_RE = re.compile(r'^(?:CC\d{1,3}[A-Z]?|CP\d{1,3}|PIER\d{1,3}|PED\d{1,3})$', re.IGNORECASE)

# Dimension strings: "12'-6"", "3'-9 1/2"", "24'-0"".
_DIMENSION_RE = re.compile(r"^\d+'-\d+(?:\s?\d+/\d+)?\"?$")

_PAD_WORD_RE = re.compile(r'\b(PAD|EQUIP|HOUSEKEEPING|HK)\b', re.IGNORECASE)
_PILE_WORD_RE = re.compile(r'\bPC\d*\b|\bPILE\b', re.IGNORECASE)

# Dimension-centerline callouts ("℄ BEAM", "C/L BEAM", "CL COL") and general
# architectural/reference note text ("SEE ARCH", "TYP", "SIM", "N.T.S.",
# "ELEVATOR SILL", "MATCH LINE") -- live-confirmed false positives
# (2026-07-20): a dimension-centerline callout and an "ELEVATOR SILL" note,
# both near the sheet's top edge, were pulled in as columns by a since-
# reverted grid-envelope-widening heuristic that treated their coincidental
# alignment with the real grid as structural evidence. The durable fix is to
# recognize this TEXT for what it is -- a note/callout, not a structural
# mark -- so no future geometric heuristic (wider envelope, looser shape
# tolerance, etc.) can reintroduce the same false positive through a
# different path. Checked with the same TIGHT radius as the split detail-
# bubble check (this label sits directly on/beside the candidate, not
# somewhere generally nearby on a dense sheet).
_CENTERLINE_RE = re.compile(r'^(?:℄|C\s*/\s*L|CL)$', re.IGNORECASE)
_NOTE_WORD_RE = re.compile(
    r'\b(SEE\s*ARCH|SEE\s*STRUCT|SEE\s*DETAIL|SEE\s*PLAN|MATCH\s*LINE|N\.?T\.?S\.?|'
    r'TYP(?:ICAL)?|SIM(?:ILAR)?|ELEVATOR|SILL|VERIFY\s+IN\s+FIELD|V\.?I\.?F\.?|'
    r'CONT(?:INUOUS)?|U\.?N\.?O\.?)\b', re.IGNORECASE
)

# 2026-07-17: live-verified on the Congress Heights foundation plan --
# _DETAIL_REF_RE only matches a detail callout written as ONE token
# ("3/S301"), but a real detail/section-reference bubble is very commonly
# typeset as its own detail number stacked over the sheet number on two
# separate lines ("4" over "S0300"), which PyMuPDF extracts as two
# SEPARATE words with no slash at all -- so _DETAIL_REF_RE never matches
# either one, and if the bubble itself happens to be drawn with straight
# lines rather than a true curve (common for a diamond/hex bubble outline),
# rule 1 below (which also requires has_curve) never even gets evaluated.
# This was confirmed live: a real "4/S0300" detail bubble on that sheet was
# being accepted as steel_column, with accept_rules=["ih_pattern"] (no
# curve) and nearby_text=["S0300", "4"]. A bare short mark-like token
# sitting immediately next to a bare sheet-number token is unambiguous
# evidence of a split two-line detail bubble regardless of curve/shape --
# no real column or footing mark is ever labeled with a raw sheet number.
#
# 2026-07-17, confirmed on a SECOND real project (Bayhealth Sussex, S1.00):
# the "S0300"-style 4-digit format above doesn't cover every firm's sheet-
# numbering convention -- this drawing labels detail bubbles "3" over
# "S2.03" (a dotted format: S + 1-2 digits + '.' + 1-3 digits), which the
# original digits-only pattern didn't match, so that bubble was still
# slipping through as a real footing_isolated candidate. Widened to accept
# either convention rather than add a second, parallel regex -- both are
# the same underlying signal (a token starting with S followed by sheet-
# number digits, optionally with a decimal sub-number).
_SHEET_REF_RE = re.compile(r'^S-?\d{1,4}(\.\d{1,3})?[A-Z]?$', re.IGNORECASE)


def _nearby_words(words: list[tuple], cx: float, cy: float, radius: float) -> list[str]:
    out = []
    for w in words:
        wx, wy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        if math.hypot(cx - wx, cy - wy) < radius:
            out.append((w[4] or "").strip())
    return out


def classify_and_filter_symbols(
    symbols: list[dict], page, is_foundation_plan: bool = False,
) -> tuple[list[dict], list[dict]]:
    """
    Classify every symbol in `symbols` (each must already carry cx, cy,
    bbox, has_curve, is_dashed -- see detect_column_symbols' clustering
    loop) and split them into (approved, rejected). Approved symbols get a
    `category` and `classifier_confidence` field added; rejected symbols
    are returned separately (with the same fields) purely for diagnostics/
    logging, never passed downstream.
    """
    if not symbols:
        return [], []

    try:
        words = page.get_text("words")
    except Exception:
        words = []

    # Nearby-word search radius, self-calibrated the same way the mark-
    # proximity filter is (see filter_foundation_symbols_by_marks): a fixed
    # pixel radius doesn't generalize across sheets of different scale.
    # Use the median symbol size on THIS sheet as the basis -- a callout or
    # mark is always found within a few symbol-widths of its target, real
    # measured relationship, not an arbitrary constant.
    sizes = [max(s["bbox"][2] - s["bbox"][0], s["bbox"][3] - s["bbox"][1]) for s in symbols]
    sizes.sort()
    median_size = sizes[len(sizes) // 2] if sizes else 15.0
    search_radius = max(80.0, median_size * 12.0)

    approved, rejected = [], []
    for s in symbols:
        cx, cy = s["cx"], s["cy"]
        x0, y0, x1, y1 = s["bbox"]
        w, h = x1 - x0, y1 - y0
        aspect = w / h if h > 0 else 1.0
        nearby = _nearby_words(words, cx, cy, search_radius)
        nearby_upper = [t.upper() for t in nearby]
        # Tight radius for the split two-line detail-bubble check (1b) --
        # the generic search_radius above (80-240pt on a typical sheet) is
        # for "is there a mark/dimension/pad-word somewhere near this
        # symbol", which is far too loose for "these two words are the two
        # lines of THIS bubble's own label": on a dense sheet it was
        # matching a real pier's nearby grid/dimension number against an
        # unrelated detail bubble's sheet-number elsewhere on the page,
        # rejecting 93 of 94 real symbols as false detail markers (measured
        # live -- see _SHEET_REF_RE comment). A real two-line bubble label
        # has both lines essentially centered on the bubble itself.
        tight_radius = max(14.0, median_size * 1.5)
        nearby_tight_upper = [t.upper() for t in _nearby_words(words, cx, cy, tight_radius)]

        category, confidence, reason = _classify_one(
            s, aspect, w, h, nearby_upper, is_foundation_plan,
            nearby_tight_upper=nearby_tight_upper,
        )

        s["category"] = category
        s["classifier_confidence"] = confidence
        s["classifier_reason"] = reason

        if category in CATEGORIES_THAT_BECOME_COLUMNS:
            approved.append(s)
        else:
            rejected.append(s)

    return approved, rejected


def _classify_one(
    s: dict, aspect: float, w: float, h: float,
    nearby_upper: list[str], is_foundation_plan: bool,
    nearby_tight_upper: list[str] | None = None,
) -> tuple[str, float, str]:
    has_curve = s.get("has_curve", False)
    is_dashed = s.get("is_dashed", False)
    symbol_type = s.get("symbol", "")
    # The real "is this an I/H column icon" signal -- see main.py's
    # clustering loop. symbol_type from refine_column_geometry defaults to
    # "I" for almost any non-circle shape (including generic footing
    # outlines), so it is NOT used here as column evidence on its own.
    has_ih_pattern = s.get("has_ih_pattern", False)
    accept_rules = set(s.get("accept_rules", []))

    has_mark = any(_MARK_RE.match(t) or _PROFILE_RE.match(t) for t in nearby_upper)
    has_detail_ref = any(_DETAIL_REF_RE.match(t) for t in nearby_upper)
    # 2026-07-20: has_mark above uses the WIDE search_radius (up to 80-360pt
    # on a typical sheet -- see the caller). That's the right radius for
    # "is there a mark somewhere in the neighborhood" signals (has_grid_
    # label_only, has_dimension), but it's the WRONG radius for "does THIS
    # symbol have its OWN structural mark" -- live-verified on the sasa
    # foundation plan: a dimension-centerline callout ("℄ BEAM / SEE ARCH")
    # and a leader-line/general-note callout near the sheet's dense right
    # margin each coincidentally had some unrelated REAL column's "F1"/"C2"
    # mark fall within the wide radius, which fed has_mark=True into rules
    # 6b/6c/7 below and inflated pure annotation clutter to 0.7-0.9
    # confidence -- high enough to bypass the grid-envelope safety gate in
    # emit_symbol_columns. A real column/footing's own label is drawn
    # immediately on or beside it (same reasoning as the tight_radius split-
    # detail-bubble check above); a mark that's only found several symbol-
    # widths away belongs to a DIFFERENT symbol, not this one. Every
    # confidence-boosting "+ real mark nearby" branch below now requires
    # this tight-radius match, not the wide one.
    has_mark_tight = any(_MARK_RE.match(t) or _PROFILE_RE.match(t) for t in (nearby_tight_upper or nearby_upper))
    # 2026-07-17: the GENERAL, content-independent signal for a detail/
    # section-reference bubble -- a circle/hex/diamond bisected by a
    # horizontal divider line is the universal AIA/NCS drafting convention
    # for this callout, regardless of what firm drew the sheet or how it
    # numbers its details ("3/S301", "4" over "S0300", "4" over "S2.03",
    # or any other scheme). Detecting the SHAPE (main.py's has_divider_bar,
    # computed from the cluster's own line geometry) instead of matching
    # specific text formats is what makes this generalize across every
    # drawing instead of needing a new regex per PDF -- two separate text-
    # pattern fixes this session each broke on the next real project's own
    # numbering convention, which is exactly the failure mode a geometric
    # check doesn't have.
    has_divider_bar = bool(s.get("has_divider_bar"))
    # Split two-line detail bubble text ("4" over "S0300") kept as a
    # SECONDARY signal only -- catches the rare case where the divider is
    # drawn as something other than a clean single line (e.g. a filled
    # rule or a table-cell border), so it's defense-in-depth, not the
    # primary mechanism.
    _tight = nearby_tight_upper if nearby_tight_upper is not None else nearby_upper
    has_split_detail_ref = (
        any(_GRID_LABEL_RE.match(t) for t in _tight)
        and any(_SHEET_REF_RE.match(t) for t in _tight)
    )
    has_grid_label_only = (
        any(_GRID_LABEL_RE.match(t) for t in nearby_upper) and not has_mark
    )
    has_dimension = any(_DIMENSION_RE.match(t) for t in nearby_upper)
    has_pad_word = any(_PAD_WORD_RE.search(t) for t in nearby_upper)
    has_pile_word = any(_PILE_WORD_RE.search(t) for t in nearby_upper)
    # "SEE ARCH", "SEE STRUCT", etc. are almost always typeset as two
    # separate PDF word tokens ("SEE" then "ARCH"), not one -- same reason
    # the split detail-bubble check above pairs two tight-radius tokens
    # instead of requiring one combined string match.
    _SEE_REF_WORDS = {"ARCH", "STRUCT", "STRUCTURAL", "DETAIL", "PLAN", "NOTE", "NOTES"}
    has_see_ref = "SEE" in _tight and any(t in _SEE_REF_WORDS for t in _tight)
    has_centerline_or_note = (
        any(_CENTERLINE_RE.match(t) for t in _tight)
        or any(_NOTE_WORD_RE.search(t) for t in _tight)
        or has_see_ref
    )

    # 1. Detail/section callout bubbles -- PRIMARY signal: the bubble's own
    #    geometry (a horizontal divider bar bisecting the shape) is the
    #    universal drafting convention for this callout and doesn't depend
    #    on what either number says or how this particular firm formats
    #    its sheet numbers. Requires the shape to look like a bubble at all
    #    (curve, or a small enough symbol that a straight-sided diamond/
    #    hex bubble is plausible) so a genuinely divided real symbol
    #    (unlikely, but not impossible) isn't caught on geometry alone.
    if has_divider_bar and (has_curve or max(w, h) <= 30.0):
        return DETAIL_MARKER, 0.9, "shape bisected by a horizontal divider bar -- universal detail/section-reference bubble convention, independent of text"

    # 1c. Detail/section callout bubbles via text: circular symbol + a
    #     detail-reference text pattern ("3/S301") -- kept as a secondary
    #     signal for bubbles whose divider wasn't detected as a clean line.
    if has_curve and has_detail_ref:
        return DETAIL_MARKER, 0.9, "circular shape + detail-reference text (e.g. '3/S301')"

    # 1d. Split two-line detail bubble text ("4" + "S0300"/"S2.03") --
    #     secondary/fallback signal, see has_split_detail_ref comment above.
    if has_split_detail_ref:
        return DETAIL_MARKER, 0.85, "bare number/letter + bare sheet-number token nearby -- split detail-reference bubble (text fallback)"

    # 1e. Dimension-centerline callouts ("℄", "C/L") and general
    #     architectural/reference note text ("SEE ARCH", "TYP", "SIM",
    #     "ELEVATOR SILL", ...) sitting directly on/beside the candidate --
    #     not a structural mark, regardless of what shape rule matched it.
    #     Only fires when there's no real F/P/C mark also nearby (a real
    #     footing can legitimately sit near a "TYP" note without being one).
    #     See _CENTERLINE_RE/_NOTE_WORD_RE for the concrete false positives
    #     this closes (2026-07-20).
    if has_centerline_or_note and not has_mark_tight:
        return CENTERLINE_NOTE, 0.85, "nearby text is a centerline/reference-note callout, not a structural mark"

    # 2. Grid bubbles: circular symbol + a BARE grid label (no letter-
    #    prefixed mark) is the sheet's own grid-line bubble, not a column.
    if has_curve and has_grid_label_only:
        return GRID_BUBBLE, 0.85, "circular shape + bare grid label, no F/P/C mark nearby"

    # 3. Dimension symbols: shape sits right next to a dimension string
    #    and has no real fill/mark evidence of its own.
    if has_dimension and not has_mark and (has_curve or w < 10 or h < 10):
        return DIMENSION_SYMBOL, 0.7, "adjacent to a dimension string, no column mark nearby"

    # 4. Continuous wall footing: extreme aspect ratio (much longer in one
    #    direction than the other) -- a real column/footing symbol is
    #    roughly square; a wall footing is a long strip.
    if aspect > 4.0 or aspect < 0.25:
        return FOOTING_WALL, 0.75, f"extreme aspect ratio ({aspect:.1f}), consistent with a wall strip"

    # 5. Equipment pad: nearby text explicitly says so.
    if has_pad_word:
        return EQUIPMENT_PAD, 0.8, "nearby text mentions PAD/EQUIP/HOUSEKEEPING"

    # 6. Pile cap: nearby text explicitly references a pile mark.
    if has_pile_word:
        return PILE_CAP, 0.65, "nearby text references a pile/PC mark"

    # 6b. Footing outline takes priority over the I/H-pattern signal on
    #     foundation plans. A real isolated footing is commonly drawn as an
    #     outline (dashed or solid square/rect) with the column's own I/H
    #     tick mark drawn INSIDE it to show where the column lands on the
    #     footing. Because of the EPS=30 cluster-widening fix, that outline
    #     sub-path and the inner tick-mark sub-path get merged into ONE
    #     symbol cluster, so has_ih_pattern legitimately ends up True for a
    #     genuine footing too -- it is not a reliable steel-column-vs-footing
    #     discriminator by itself on a foundation plan. Whether an
    #     outline was actually matched (accept_rules) is the more specific
    #     signal, so check it first and let the plain I/H-only case (rule 7,
    #     no outline sub-match) fall through to STEEL_COLUMN as before.
    # Ground-truth fix (2026-07-17, Stage 6 -- found via a live debug
    # endpoint after three code-only theories in a row measured zero
    # effect): "fragmented_outline" is a SEPARATE accept_rule tag from
    # "foundation_outline" -- main.py's dash/fragment-rescue pass
    # (detect_column_symbols, built specifically for projects that draw
    # footings as many separate dash-tick line objects instead of one
    # clean 4-line/rectangle path) tags its finds "fragmented_outline",
    # and this rule only ever checked for "foundation_outline". Real
    # confirmed impact: on this exact project, 35 of 36 rejected
    # candidates were fragmented_outline-tagged real footing shapes,
    # falling through to MISC because neither string matched the other.
    # It was previously masked by coincidence, not fixed: a cluster often
    # ALSO merged with a nearby "re"-primitive sub-path that satisfied the
    # old (buggy, since-removed) unconditional _has_IH_pattern accept, so
    # has_ih_pattern ended up True for the same cluster anyway and rule 7
    # below rescued it under the wrong category (STEEL_COLUMN instead of
    # FOOTING_ISOLATED). Both tags mean the same real-world thing -- a
    # footing outline -- just detected via two different geometry paths.
    _outline_rules = accept_rules & {"foundation_outline", "fragmented_outline"}
    if (_outline_rules and 0.4 < aspect < 2.5 and has_mark_tight):
        if any(_CONCRETE_MARK_RE.match(t) for t in _tight):
            return CONCRETE_COLUMN, 0.85, "concrete column/pier mark (CC/CP) - concrete scope"
        if any(_PROFILE_RE.match(t) for t in _tight):
            return STEEL_COLUMN, 0.85, "square-ish outline with steel column profile nearby"
        return PEDESTAL if not is_foundation_plan else FOOTING_ISOLATED, 0.75, "square-ish pedestal/footing outline + real structural mark nearby"

    if (is_foundation_plan and _outline_rules and 0.4 < aspect < 2.5):
        return FOOTING_ISOLATED, 0.45, "square-ish outline on a foundation plan, no readable mark nearby -- guessed"

    # 6c. Universal Symbol Library match (Phase 2/4). By this point every
    #     false-positive pattern actually observed and root-caused this
    #     session (detail bubbles, grid bubbles, dimension ticks, wall
    #     footings, pads, piles) has already been ruled out above, so a
    #     confident Symbol Library match here is trustworthy evidence for
    #     symbol styles the older accept_rules-only logic (rules 7/7b)
    #     never covered on its own -- square+dot, square+diamond,
    #     square+cross, square+inner-square, circle-in-footing-with-I/H,
    #     diamond-in-footing, etc. A real mark nearby is still required
    #     when the match's own library confidence is moderate (some entries,
    #     e.g. a bare hollow square, are intentionally weak on shape alone
    #     -- see column_symbol_library.py's notes); a very high-confidence
    #     match (>=0.75, i.e. an entry the library itself considers close
    #     to unambiguous) is allowed to stand without a mark, matching how
    #     rule 7 already treats a verified I/H pattern.
    library_conf = s.get("library_confidence") or 0.0
    expected_type = s.get("expected_member_type")
    _LIBRARY_CATEGORY = {
        "steel_column": STEEL_COLUMN, "concrete_column": CONCRETE_COLUMN,
        "hss_column": HSS_COLUMN, "pipe_column": PIPE_COLUMN,
        "built_up_column": BUILT_UP_COLUMN, "pedestal": PEDESTAL,
        "foundation_only": FOOTING_ISOLATED,
    }
    if expected_type in _LIBRARY_CATEGORY and (
        library_conf >= 0.75 or (has_mark_tight and library_conf >= 0.55)
    ):
        cat = _LIBRARY_CATEGORY[expected_type]
        conf = round(min(0.95, library_conf + (0.1 if has_mark_tight else 0.0)), 2)
        return cat, conf, (
            f"Symbol Library match '{s.get('library_name')}' "
            f"({s.get('outer_boundary')}/{s.get('inner_geometry')}/{s.get('fill_type')})"
            + (" + real mark nearby" if has_mark_tight else "")
        )

    # 7. Real steel column plan symbol: the I/H flange+web PATTERN (verified
    #    parallel-flange + perpendicular-web line geometry, see
    #    _has_IH_pattern in main.py) is the single strongest positive
    #    signal there is -- this IS the plan-view icon for a steel column.
    #    NOTE: symbol_type=="I" alone is NOT used here -- it's
    #    refine_column_geometry's default for almost any non-circle shape
    #    (including a generic 4-line footing outline), so it can't
    #    distinguish a real column icon from a footing outline on its own.
    #    (Foundation-plan footing outlines are already routed to
    #    FOOTING_ISOLATED above, before this rule is reached.)
    if has_ih_pattern and not has_curve:
        conf = 0.9 if has_mark_tight else 0.65
        return STEEL_COLUMN, conf, "verified I/H flange+web pattern" + (" + real mark nearby" if has_mark_tight else "")

    if "filled_rect" in accept_rules and not has_curve:
        conf = 0.85 if has_mark_tight else 0.55
        return STEEL_COLUMN, conf, "solid filled plan mark" + (" + real mark nearby" if has_mark_tight else "")

    # 8. (Isolated-footing check moved up to 6b, above rule 7, so it takes
    #    priority over the I/H-pattern signal -- see 6b's comment for why.)

    # 9. Anything with a curve and no other positive signal is almost
    #    always page furniture (arrows, leader-line elbows, north-arrow
    #    circles, revision clouds) rather than a structural symbol.
    if has_curve:
        return ANNOTATION, 0.5, "circular/curved shape with no structural signal (mark/detail-ref/grid-label)"

    # 10. Conservative default: reject rather than guess. A false negative
    #     (a real column classified as misc) is recoverable -- it shows up
    #     as a missing column and someone notices. A false positive column
    #     silently entering the database is much harder to catch.
    return MISC, 0.3, "no matching classification signal -- rejected by conservative default"
