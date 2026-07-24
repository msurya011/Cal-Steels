"""
Column Schedule parser -- Phase 4 of the Column Engine.

Column Schedule pages are TABLES, not plan drawings: they carry the
engineering metadata (section profile per floor segment, base plate, anchor
rods, remarks) for each column mark. This is architecturally a SEPARATE
extraction path from the vector plan-drawing pipeline in main.py -- verified
live against SteelGenie (its own "Column Schedule" sheet reported
Column: 0, Beam: 0 in its Sheet Summary, meaning it explicitly does not run
the normal plan-drawing member-extraction pipeline against schedule sheets).
See docs/column-engine-architecture.md section 2.3.

Two real schedule layouts have been observed on real project sheets so far:

  1. MARK-BY-FLOOR (observed live on SteelGenie, sheet S0400): column marks
     are one axis (e.g. C-5A, C-4A), floor levels are the other axis
     (High Roof / Low Roof / Foundation), each cell holds that mark's
     profile for that floor segment -- a column can change section partway
     up. Not yet available in a local test PDF; this parser's handling of
     it is designed from the live observation but not yet round-trip tested
     against a real file of this exact layout (see open question in the
     architecture doc).

  2. MARK-BY-TYPE (found and verified locally: "#Structural binder.pdf",
     page 17, "Base Plate Schedule and Details"): each row is one column
     TYPE/profile (not an individual physical column mark), mapped to a
     baseplate mark, elevation, and remarks; a second table on the same
     page gives the baseplate mark its full geometry (dimensions, anchor
     rod count/diameter/projection/length, weld size). This is column
     *type* data (applies to every column of that profile), not per-mark
     data -- merge logic must handle both.

No fixed column-index assumptions: every table's columns are identified by
FUZZY HEADER KEYWORD matching (see _HEADER_KEYWORDS below), because real
schedules vary in column order and exact wording between projects. This
follows the mission's "no magic numbers, drawing-relative" principle applied
to tables instead of geometry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Header keyword classification ──────────────────────────────────────────
# Each field maps to a list of substrings (checked case-insensitively,
# whitespace-normalized) that a header cell is scored against. A header cell
# can match more than one field's keywords; the classifier picks the field
# whose keyword match is most specific (longest matching keyword) to avoid
# e.g. "BASEPLATE EL." being classified as a generic "PLATE" match instead of
# "ELEVATION".
_HEADER_KEYWORDS: dict[str, list[str]] = {
    "mark": ["column mark", "col mark", "col. mark", "mark"],
    # NOTE: bare "column" is deliberately NOT a keyword here -- it matches
    # inside ordinary note paragraphs ("...FOR W SHAPES...COLUMNS...")
    # constantly on real sheets, which is what corrupted the first version
    # of this parser (whole paragraphs got classified as column_type
    # headers). Only specific, compound phrases count.
    "column_type": ["column type", "col type", "col. type"],
    "profile": ["section", "profile", "shape", "size"],
    "floor_segment": ["floor", "level", "roof", "story", "storey"],
    "base_plate_mark": ["baseplate type", "base plate type", "bp type",
                         "plate type", "plate mark", "baseplate mark",
                         "base plate mark"],
    "base_plate_elevation": ["baseplate el", "base plate el", "basepl el",
                              "bp el", "plate elevation", "elevation"],
    "plate_dim_b": ["b (in)", "b(in)", " b "],
    "plate_dim_n": ["n (in)", "n(in)", " n "],
    "plate_dim_tp": ["tp (in)", "tp(in)", "thickness"],
    "anchor_number": ["number", "no. of anchors", "qty"],
    "anchor_dia": ["dia. (in)", "dia (in)", "diameter", "rod dia"],
    "anchor_projection": ["projection"],
    "anchor_length": ["length"],
    "weld_size": ["weld size", "weld"],
    "material": ["grade", "material", "astm"],
    "remarks": ["remarks", "notes", "comment"],
    "orientation": ["orientation", "rotation"],
}

_MARK_TOKEN_RE = re.compile(r'^[A-Z]{1,3}-?\d{1,3}[A-Z]?$')


def _norm(s) -> str:
    if s is None:
        return ""
    return re.sub(r'\s+', ' ', str(s)).strip().lower()


def _classify_header_scored(cell_text: str) -> tuple[str, int] | None:
    """Return (field_name, matched_keyword_length) for the most specific
    field a header cell matches, or None. The keyword length is exposed so
    callers scanning a whole header block can prefer a strong, specific
    match (exact "REMARKS") over a weak, coincidental one (generic "NOTES"
    inside an unrelated "COLUMN GENERAL NOTES" section heading) regardless
    of which cell happens to be scanned first or last -- this is what fixed
    a real bug where a later, weaker match was silently overwriting an
    earlier, correct one.

    Header cells are short (a real header is a word or two, never a
    multi-sentence note paragraph) -- reject long text up front so a stray
    keyword occurring inside a notes paragraph can't get misclassified as
    a header, which is what corrupted the first version of this parser."""
    t = _norm(cell_text)
    if not t or len(t) > 40:
        return None
    best_field = None
    best_len = 0
    for field_name, keywords in _HEADER_KEYWORDS.items():
        for kw in keywords:
            if kw in t and len(kw) > best_len:
                best_field = field_name
                best_len = len(kw)
    return (best_field, best_len) if best_field else None


def _classify_header(cell_text: str) -> str | None:
    """Convenience wrapper for callers that only need the field name."""
    scored = _classify_header_scored(cell_text)
    return scored[0] if scored else None


# A real identity cell (mark, column type label, base-plate mark) is a
# short structural-drawing token -- "C2", "C2A", "BP1", "HSS8X8X3/8",
# "W12X40" -- never a multi-line note or a section-heading paragraph like
# "E.\nCOLUMN SPLICE DETAIL". Reject anything containing a newline or
# longer than 20 characters as "not a real identity value" -- this is the
# single biggest guard against the paragraph-text contamination seen in
# testing.
def _looks_like_identity_token(s: str) -> bool:
    t = (s or "").strip()
    if not t or "\n" in t or len(t) > 20:
        return False
    return bool(re.match(r'^[A-Za-z0-9./\-# ]+$', t))


@dataclass
class ScheduleRecord:
    """One normalized row of engineering data from a Column Schedule table."""
    mark: str | None = None
    column_type: str | None = None          # profile used as the row identity
                                             # instead of a mark, on
                                             # mark-by-type layout sheets
    profile: str | None = None
    floor_segment: str | None = None
    base_plate_mark: str | None = None
    base_plate_elevation: str | None = None
    plate_dims: dict = field(default_factory=dict)   # {b, n, tp}
    anchor_rods: dict = field(default_factory=dict)  # {number, dia, projection, length}
    weld_size: str | None = None
    material: str | None = None
    remarks: str | None = None
    orientation: str | None = None
    source_page_idx: int | None = None
    source_table_bbox: tuple | None = None
    confidence: float = 0.0

    def identity_key(self) -> str | None:
        """The key to merge this record into the Global Column Database by.
        Prefer a real mark; fall back to column_type/profile for
        mark-by-type sheets (matches ALL columns of that profile, not one
        physical column -- caller must treat that differently, see
        merge_schedules_into_columns)."""
        return self.mark or self.column_type or self.profile


# Forward-fill for merged identity cells (mark/column_type/base_plate_mark
# spanning multiple rows) now happens inline in parse_column_schedule_page,
# scoped per blank-row-delimited section -- see the fill_state loop there.
# A page-wide forward-fill (the original approach here) let one section's
# value bleed into a completely unrelated section below it once
# find_tables() had merged multiple visual tables into one logical table.


def find_schedule_tables(page) -> list[dict]:
    """
    Locate tables on this page that look like Column/Base-Plate Schedule
    tables (not just any table -- a page can have many small unrelated
    tables, like the "Typical Anchor Rod Clearance" reference table seen on
    a real sheet). A table is treated as a schedule candidate if its header
    row/first data rows classify at least 2 distinct schedule fields via
    _classify_header, AND at least one row's identity-column cell looks
    like a real mark/profile token (not blank, not a note paragraph).

    Returns a list of {"table": <PyMuPDF Table>, "field_cols": {field: idx}}.
    """
    try:
        found = page.find_tables()
    except Exception:
        return []

    candidates = []
    for t in found.tables:
        try:
            rows = t.extract()
        except Exception:
            continue
        if not rows or len(rows) < 2:
            continue

        # Header may span more than one physical row (e.g. "ANCHOR RODS"
        # spanning "NUMBER / DIA / PROJECTION / LENGTH" beneath it) -- scan
        # the first few rows and let any cell in them vote for a field on
        # its column index; last non-empty vote per column wins (mirrors
        # reading top-to-bottom, more specific sub-header overriding a
        # generic parent header directly above it).
        n_cols = max(len(r) for r in rows[:4])
        field_cols: dict[str, int] = {}
        field_col_scores: dict[str, int] = {}
        for r in rows[:4]:
            for ci, cell in enumerate(r):
                scored = _classify_header_scored(cell)
                if not scored:
                    continue
                f, score = scored
                if score > field_col_scores.get(f, -1):
                    field_cols[f] = ci
                    field_col_scores[f] = score

        if len(field_cols) < 2:
            continue  # not enough recognizable schedule columns

        candidates.append({"table": t, "rows": rows, "field_cols": field_cols,
                            "n_cols": n_cols})

    return candidates


def parse_column_schedule_page(page, page_idx: int | None = None) -> list[ScheduleRecord]:
    """
    Parse every schedule-like table on this page into normalized
    ScheduleRecords. Handles both observed layouts (mark-by-floor,
    mark-by-type) through the same field-keyword classification -- which
    layout a given table is doesn't need to be known ahead of time, it falls
    out of which identity field (mark vs column_type) actually got
    populated.
    """
    records: list[ScheduleRecord] = []

    for cand in find_schedule_tables(page):
        rows = cand["rows"]
        field_cols = cand["field_cols"]
        n_cols = cand["n_cols"]

        identity_field = "mark" if "mark" in field_cols else (
            "column_type" if "column_type" in field_cols else "profile")
        identity_col = field_cols.get(identity_field)
        if identity_col is None:
            continue

        header_row_count = 0
        for r in rows:
            header_row_count += 1
            if header_row_count >= 4:
                break
            if any(_classify_header(c) for c in r):
                continue
            else:
                header_row_count -= 1
                break

        # PyMuPDF's find_tables() will happily merge multiple visually
        # SEPARATE tables (and stray page furniture in between) into one
        # logical table object if they're column-aligned -- confirmed on a
        # real sheet, where a 39-row "table" actually contained the column-
        # type table, several paragraphs of notes, the base-plate schedule,
        # and unrelated detail-callout labels, all sharing the same rough
        # column x-positions by coincidence. A row that's completely blank
        # across every field we recognize is treated as a section break:
        # forward-fill state resets there, so a mark/type from one section
        # can never leak into an unrelated section below a blank gap.
        fill_state: dict[str, str] = {}
        for r in rows[header_row_count:]:
            all_blank = all(
                not _norm(r[ci]) if ci < len(r) else True
                for ci in field_cols.values()
            )
            if all_blank:
                fill_state = {}
                continue

            for f in ("mark", "column_type", "base_plate_mark"):
                ci = field_cols.get(f)
                if ci is None or ci >= len(r):
                    continue
                v = r[ci]
                if v is not None and _looks_like_identity_token(str(v)):
                    fill_state[f] = str(v).strip()
                elif f in fill_state:
                    r[ci] = fill_state[f]  # apply carried-forward value

            if identity_col >= len(r):
                continue
            identity_val = r[identity_col]
            identity_val = str(identity_val).strip() if identity_val is not None else ""
            if not _looks_like_identity_token(identity_val):
                continue

            def _get(field_name, max_len=60):
                ci = field_cols.get(field_name)
                if ci is None or ci >= len(r):
                    return None
                v = r[ci]
                if v in (None, ""):
                    return None
                v = str(v).strip()
                # Guard every field, not just the field_name, not just the identity column -- a
                # multi-sentence note paragraph landing in e.g. "remarks" is
                # plausible real data (remarks CAN be a full sentence), but
                # a note landing in "profile" or "base_plate_mark" (which
                # should always be a short token) means the table got
                # mis-segmented and this cell isn't trustworthy.
                if field_name in ("profile", "base_plate_mark", "column_type",
                                   "weld_size", "material", "orientation") and len(v) > max_len:
                    return None
                return v

            rec = ScheduleRecord(
                mark=_get("mark"),
                column_type=_get("column_type"),
                profile=_get("profile") or (_get("column_type")
                                             if "profile" not in field_cols else None),
                floor_segment=_get("floor_segment"),
                base_plate_mark=_get("base_plate_mark"),
                base_plate_elevation=_get("base_plate_elevation"),
                plate_dims={
                    k: _get(f"plate_dim_{k}") for k in ("b", "n", "tp")
                    if _get(f"plate_dim_{k}")
                },
                anchor_rods={
                    k: _get(f"anchor_{k}") for k in ("number", "dia", "projection", "length")
                    if _get(f"anchor_{k}")
                },
                weld_size=_get("weld_size"),
                material=_get("material"),
                remarks=_get("remarks", max_len=500),
                orientation=_get("orientation"),
                source_page_idx=page_idx,
                source_table_bbox=tuple(cand["table"].bbox) if cand["table"].bbox else None,
                confidence=min(1.0, 0.3 + 0.1 * len(field_cols)),
            )
            # A record needs to carry SOMETHING beyond its identity to be
            # worth keeping (a stray row with just a mark and nothing else
            # is almost always a rendering/merge artifact, not real data).
            if any([rec.profile, rec.base_plate_mark, rec.anchor_rods,
                    rec.remarks, rec.floor_segment]):
                records.append(rec)

    return records


def is_schedule_page(page) -> bool:
    """Cheap pre-check before running the (more expensive) table extraction:
    does this page's text even mention a column/baseplate schedule? Mirrors
    the is_foundation_plan text-sniff pattern already used in main.py."""
    try:
        t = page.get_text().upper()
    except Exception:
        return False
    return ("COLUMN SCHEDULE" in t) or ("BASE PLATE SCHEDULE" in t) or ("BASEPLATE SCHEDULE" in t)
