"""
Universal Structural Column Symbol Library -- Phase 1 of the Column
Classification Engine mission (2026-07-15).

Honest scope note up front: this catalog is built from general knowledge of
how AISC/SDS2/Tekla-style structural drawings conventionally represent
columns, footings, and pedestals, PLUS the concrete symbol styles the user
has directly pointed out from real project drawings this session. It is NOT
yet cross-validated against a live behavioral study of SteelGenie itself
(that's Phase 6, tracked separately -- it requires driving the live app,
which needs explicit computer-use permission, not something to assume).
Treat every entry's `confidence` as a starting prior to be corrected once
real projects are run through the pipeline and reviewed, not a proven
accuracy number.

Each entry describes one COMBINATION of (outer_boundary, inner_geometry,
fill_type) -- the actual unit real drawings vary on. A single "column"
category is not enough because the same physical thing (a steel column
landing on an isolated footing) is drawn differently by different firms/
CAD systems: some show the footing outline with the column tick inside it,
some show only the column tick, some show only the footing outline, some
show neither and rely purely on a mark + grid intersection.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SymbolDefinition:
    id: str
    name: str
    outer_boundary: str          # square | rectangle | diamond | circle | octagon | none
    inner_geometry: str          # filled_square | empty_square | circle | diamond | cross |
                                  # i_shape | h_shape | parallel_bars | single_line |
                                  # double_line | dot | inner_square | none
    fill_type: str                # filled | hollow | dashed | mixed
    common_usage: str
    expected_member_type: str     # steel_column | concrete_column | hss_column |
                                   # pipe_column | built_up_column | pedestal | pile |
                                   # foundation_only | equipment_support | anchor_point |
                                   # reference_marker
    confidence: float             # prior weight this combo gets in feature scoring, 0-1
    notes: str = ""
    aliases: tuple = field(default_factory=tuple)


# ── The catalog ─────────────────────────────────────────────────────────
# Grouped by outer boundary for readability; lookup is by
# (outer_boundary, inner_geometry, fill_type) with graceful fallback (see
# lookup_symbol below) when the exact fill_type isn't known at query time.
SYMBOL_LIBRARY: list[SymbolDefinition] = [

    # ── Square outer boundary ───────────────────────────────────────────
    SymbolDefinition(
        id="sq_hollow_none", name="Hollow square outline",
        outer_boundary="square", inner_geometry="none", fill_type="hollow",
        common_usage="Isolated footing / pier outline on a foundation plan, "
                      "drawn without a separate column tick mark -- the "
                      "square IS the footing symbol.",
        expected_member_type="foundation_only", confidence=0.55,
        notes="Weak on its own (a dimension box or plain annotation square "
              "looks identical) -- needs a real F/P mark nearby to be "
              "trustworthy. See column_validation_engine mark_match signal.",
    ),
    SymbolDefinition(
        id="sq_filled_none", name="Filled (solid black) square",
        outer_boundary="square", inner_geometry="none", fill_type="filled",
        common_usage="Steel column plan mark drawn as a simple solid square "
                      "rather than an I/H icon -- common on smaller/simpler "
                      "framing plans and some SDS2 exports.",
        expected_member_type="steel_column", confidence=0.75,
    ),
    SymbolDefinition(
        id="sq_hollow_dot", name="Square with center dot",
        outer_boundary="square", inner_geometry="dot", fill_type="hollow",
        common_usage="Pier/pedestal footing with the column's own center-"
                      "point marked -- common where the footing size and the "
                      "bearing column are drawn as two separate concentric "
                      "elements.",
        expected_member_type="pedestal", confidence=0.6,
    ),
    SymbolDefinition(
        id="sq_hollow_diamond", name="Square with inscribed diamond",
        outer_boundary="square", inner_geometry="diamond", fill_type="hollow",
        common_usage="Footing outline with a rotated-square (diamond) "
                      "column/pedestal mark inside -- seen on projects "
                      "distinguishing a square footing from a diamond-plan "
                      "pedestal or a rotated HSS column.",
        expected_member_type="hss_column", confidence=0.6,
    ),
    SymbolDefinition(
        id="sq_hollow_cross", name="Square with center cross",
        outer_boundary="square", inner_geometry="cross", fill_type="hollow",
        common_usage="Footing outline with a crosshair marking the column's "
                      "exact bearing point -- common Tekla/erection-plan "
                      "convention for showing anchor-bolt-pattern center "
                      "independent of the footing's own geometry.",
        expected_member_type="anchor_point", confidence=0.55,
    ),
    SymbolDefinition(
        id="sq_hollow_ih", name="Square (footing) with I/H column tick",
        outer_boundary="square", inner_geometry="i_shape", fill_type="hollow",
        common_usage="THE most common foundation-plan convention observed "
                      "this session: dashed/hollow footing outline with the "
                      "actual steel column's I/H plan-view icon drawn at its "
                      "center to show exactly where the column lands on the "
                      "footing.",
        expected_member_type="steel_column", confidence=0.85,
        aliases=("sq_hollow_hshape",),
    ),
    SymbolDefinition(
        id="sq_hollow_innersquare", name="Square with concentric inner square",
        outer_boundary="square", inner_geometry="inner_square", fill_type="hollow",
        common_usage="Footing outline with a smaller square pedestal/base-"
                      "plate outline inside it -- distinguishes footing size "
                      "from base plate size on the same symbol.",
        expected_member_type="pedestal", confidence=0.6,
    ),
    SymbolDefinition(
        id="sq_filled_innersquare", name="Filled square with hollow inner square",
        outer_boundary="square", inner_geometry="inner_square", fill_type="mixed",
        common_usage="Concrete column drawn in plan as a solid-fill square "
                      "with a lighter/hollow rebar-cage or core outline "
                      "inside -- typical concrete-column plan convention "
                      "(distinct from the steel I/H icon).",
        expected_member_type="concrete_column", confidence=0.65,
    ),

    # ── Diamond outer boundary ──────────────────────────────────────────
    SymbolDefinition(
        id="dia_hollow_none", name="Hollow diamond outline",
        outer_boundary="diamond", inner_geometry="none", fill_type="hollow",
        common_usage="Footing/pier outline drawn as a diamond (rotated "
                      "square) rather than an axis-aligned square -- either "
                      "a genuinely diamond-shaped footing or a square "
                      "footing on a rotated/skewed portion of the grid.",
        expected_member_type="foundation_only", confidence=0.5,
    ),
    SymbolDefinition(
        id="dia_hollow_ih", name="Diamond with I/H column tick",
        outer_boundary="diamond", inner_geometry="i_shape", fill_type="hollow",
        common_usage="Same convention as sq_hollow_ih but on a diamond-"
                      "shaped footing/pier outline.",
        expected_member_type="steel_column", confidence=0.8,
    ),

    # ── Circle outer boundary ───────────────────────────────────────────
    SymbolDefinition(
        id="circ_hollow_none", name="Circle inside/around footing",
        outer_boundary="circle", inner_geometry="none", fill_type="hollow",
        common_usage="Round pier/caisson footing, OR a grid/detail-callout "
                      "bubble -- genuinely ambiguous from shape alone. Must "
                      "be disambiguated by nearby text (a real F/P/C mark vs. "
                      "a detail reference or bare grid label) -- see "
                      "column_symbol_classifier's detail-ref / grid-label "
                      "rules, which take priority over this library entry.",
        expected_member_type="foundation_only", confidence=0.35,
        notes="Deliberately low base confidence -- this is the single most "
              "common source of false positives (grid bubbles, detail "
              "callouts) observed this session. Context signals must carry "
              "this one, not geometry alone.",
    ),
    SymbolDefinition(
        id="circ_hollow_ih", name="Circle with I/H column tick",
        outer_boundary="circle", inner_geometry="i_shape", fill_type="hollow",
        common_usage="Round pier/caisson with the bearing steel column's "
                      "I/H icon inside it -- this specific combination (a "
                      "real structural icon inside the circle, not just "
                      "text) is a much stronger positive signal than a bare "
                      "circle.",
        expected_member_type="steel_column", confidence=0.75,
    ),
    SymbolDefinition(
        id="circ_filled_none", name="Filled circle (solid dot/pier mark)",
        outer_boundary="circle", inner_geometry="none", fill_type="filled",
        common_usage="Pipe column plan mark, or a small solid pier/pile "
                      "location dot.",
        expected_member_type="pipe_column", confidence=0.55,
    ),

    # ── Octagon outer boundary (uncommon but real) ──────────────────────
    SymbolDefinition(
        id="oct_hollow_none", name="Octagon outline",
        outer_boundary="octagon", inner_geometry="none", fill_type="hollow",
        common_usage="Uncommon; seen on some architectural-precast or "
                      "chamfered-pedestal details representing a chamfered "
                      "square pier.",
        expected_member_type="pedestal", confidence=0.4,
    ),

    # ── No outer boundary at all -- mark/grid-intersection only ─────────
    SymbolDefinition(
        id="none_none_none", name="No symbol -- mark and/or grid intersection only",
        outer_boundary="none", inner_geometry="none", fill_type="none",
        common_usage="Some projects/firms omit a drawn footing or column "
                      "icon entirely and rely purely on a text mark (e.g. "
                      "\"C2\") sitting at a grid intersection to indicate a "
                      "column. This is the case CalSteel's shape-based "
                      "detector cannot see AT ALL by definition -- it has to "
                      "be recovered from the mark+grid signals alone (a "
                      "column-mark-shaped token sitting exactly on a grid "
                      "crossing with no nearby competing geometry).",
        expected_member_type="reference_marker", confidence=0.3,
        notes="Not produced by detect_column_symbols' shape scan (there is "
              "no shape to scan) -- this entry documents the case for "
              "Phase 2 onward: a future mark+grid-only detection pass, "
              "separate from the shape-based pipeline, is needed to cover "
              "it. Flagged, not yet implemented.",
    ),
]

_LOOKUP: dict[tuple[str, str, str], SymbolDefinition] = {
    (s.outer_boundary, s.inner_geometry, s.fill_type): s for s in SYMBOL_LIBRARY
}


def lookup_symbol(outer_boundary: str, inner_geometry: str,
                   fill_type: str = "hollow") -> SymbolDefinition | None:
    """
    Exact match first; if the fill_type at query time is uncertain (shape
    detection can tell outer/inner geometry more reliably than fill state
    on every PDF exporter), fall back to ANY fill_type for the same
    outer/inner combo rather than returning nothing -- geometry match is
    the stronger signal of the two.
    """
    key = (outer_boundary, inner_geometry, fill_type)
    if key in _LOOKUP:
        return _LOOKUP[key]
    for s in SYMBOL_LIBRARY:
        if s.outer_boundary == outer_boundary and s.inner_geometry == inner_geometry:
            return s
    return None


def all_symbols() -> list[SymbolDefinition]:
    return list(SYMBOL_LIBRARY)
