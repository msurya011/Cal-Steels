"""
Universal Column & Base Plate Reference Resolver for Foundation Plans.

Cross-page reference resolution specifically for Foundation Plan extractions:
1. Direct Callout Matching: Extracts nearby AISC profiles (W14X176, HSS8X8X1/2) and Base Plate marks (BP-1, BP-7)
   next to each column symbol on the Foundation Plan.
2. Graphical Column Schedule Matching: Matches columns at grid intersections (e.g. A-1, B-5, C-6, D-4)
   against Graphical Column Schedules across the PDF drawing set (e.g. Page 18).
3. Tabular Schedule Matching: Cross-references C1..C8 and BP-1..BP-10 against Schedule Sheets (e.g. Page 8, Page 25).
4. Automatic Ghost Pruning & Deduplication: Filters out false-positive grid crossings and duplicate footing boxes,
   retaining only the exact physical columns defined in the drawing set.
5. Assigns exact structural profiles, weights, base plate specs, and source page to every Foundation column.
"""
from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from app.engineering.shapes import get_weight_per_ft

logger = logging.getLogger(__name__)

# Column mark pattern — matches any column reference seen on real foundation plans:
# C1, C2, C4, C-1, C1A, C-1A, CC1, CC2, CC-1, COL 1, COL-1, BP-1, BP1000
# 1-3 letter prefix + digits covers: C, CC, CL, PU, POST, COL
_MARK_PATTERN = re.compile(
    r"\b(?:COL(?:UMN)?[\s\-_]*)?([A-Z]{1,3}[\s\-_]?\d{1,4}[A-Z]?)\b",
    re.IGNORECASE
)

# AISC Profile pattern (W8x35, W10x33, W10x45, W10x77, W12x79, W12x120, W14x176, HSS6x6x5/16, HSS8x8x1/2)
_AISC_PROFILE_PATTERN = re.compile(
    r"\b((?:W|WT|S|ST|C|MC|M|MT|HP)\s*\d+(?:\.\d+)?\s*[Xx]\s*\d+(?:\.\d+)?|HSS\s*\d+(?:\.\d+)?\s*[Xx]\s*\d+(?:\.\d+)?(?:\s*[Xx]\s*[\d/]+)?|PIPE\s*\d+(?:\.\d+)?(?:\s*STD|\s*X-?S)?|L\s*\d+(?:\.\d+)?\s*[Xx]\s*\d+(?:\.\d+)?(?:\s*[Xx]\s*[\d/]+)?)\b",
    re.IGNORECASE
)

# Base plate mark & dimension pattern (e.g. BP-1, BP1, BP1000, 14"x14"x1", 18"X18"X1 1/4", 1'-2" x 1'-2")
_BP_MARK_PATTERN = re.compile(r"\b(BP[\-_]?\d{1,4}[A-Z]?)\b", re.IGNORECASE)
_BP_DIM_PATTERN = re.compile(r'(\d{1,2}(?:[\'"]|\s*-\s*\d{1,2}(?:\s*[\d/]+)?")?\s*[Xx]\s*\d{1,2}(?:[\'"]|\s*-\s*\d{1,2}(?:\s*[\d/]+)?")?(?:\s*[Xx]\s*[\d/\s]+(?:\s*")?)?)', re.IGNORECASE)
_ANCHOR_PATTERN = re.compile(r'(\(?\d+\)?(?:\s*[\d/]+"\s*DIA|\s*/\s*AB-?\d+)[^\n\r,]*)', re.IGNORECASE)
# Grid location pattern: A-1, A-4, A-2.4, A.7-1, B.2-1, B.6-3.6, C.4-2.2, D-4.4, E-2.2, F-4
_GRID_LOC_PATTERN = re.compile(r"^([A-Z0-9.]+)-([A-Z0-9.]+)$", re.IGNORECASE)


@dataclass
class ResolvedColumnDetail:
    """Exact structural specifications resolved for a Foundation Plan column/baseplate mark."""
    mark: str
    normalized_mark: str
    profile: Optional[str] = None
    weight_per_ft: Optional[float] = None
    base_plate_mark: Optional[str] = None
    base_plate_dims: Optional[str] = None
    anchor_rods: Optional[str] = None
    source_page_idx: Optional[int] = None      # 0-based
    source_page_num: Optional[int] = None      # 1-based (e.g. Page 8, Page 18, Page 25)
    source_sheet_name: Optional[str] = None
    status: str = "unresolved"                 # "resolved" | "unresolved"
    raw_snippet: Optional[str] = None
    confidence_score: int = 0                  # higher score = higher priority


# Column mark token regex — matches any mark reference on foundation plans or schedules:
# C1, CC1, CC2, C1A, CC1A, PU1, COL1, POST1 — 1-3 letter prefix + 1-4 digits + optional suffix
_COL_MARK_RE = re.compile(
    r"^(?:CC?\d{1,3}[A-Z]?|PU\d{1,3}|POST\d{1,3}|COL\d{1,3}|[A-Z]{1,3}\d{1,3}[A-Z]?)$",
    re.IGNORECASE
)

# Concrete Column & Pier mark regex (e.g. CC1, CC2, CC3, CP1, CP2, PIER1, PED1)
# These represent cast-in-place concrete scope, NOT structural steel members.
_CONCRETE_MARK_RE = re.compile(
    r"^(?:CC\d{1,3}[A-Z]?|CP\d{1,3}|PIER\d{1,3}|PED\d{1,3})$",
    re.IGNORECASE
)


def normalize_mark(mark: str) -> str:
    """Normalize a mark token for robust matching.
    Examples: 'C-1' -> 'C1', 'CC-1' -> 'CC1', 'BP-1' -> 'BP1', 'B.7-3' -> 'B.7-3'."""
    if not mark:
        return ""
    m = mark.upper().strip()
    # Grid location format (e.g. A-1, B.7-3) — keep as-is
    if re.match(r"^[A-Z](?:\.[0-9])?-[0-9](?:\.[0-9])?$", m):
        return m
    m = re.sub(r"^COL(?:UMN)?[\s\-_]*", "C", m)
    m = re.sub(r"[\s\-_]+", "", m)
    return m


def scan_pdf_for_column_schedules(doc: fitz.Document) -> List[int]:
    """
    Universally scan any multi-page PDF document to identify candidate Column Schedule pages.
    Does NOT assume any hardcoded page index — checks every page.
    """
    candidate_indices = []
    keywords = [
        "GRAPHICAL COLUMN SCHEDULE",
        "COLUMN SCHEDULE",
        "BASE PLATE SCHEDULE",
        "BASEPLATE SCHEDULE",
        "BASE PLATE DETAILS",
        "BASEPLATE DETAILS",
        "COLUMN DETAILS",
        "COLUMN TYPES",
        "SCHEDULE - COLUMNS",
        "SCHEDULE - BASE PLATES",
        "BASE PLATE & ANCHOR BOLT SCHEDULE",
        "BASE PLATE AND ANCHOR BOLT SCHEDULE",
    ]

    for page_idx in range(len(doc)):
        try:
            page = doc[page_idx]
            text = page.get_text().upper()
            if any(k in text for k in keywords):
                candidate_indices.append(page_idx)
        except Exception as exc:
            logger.warning("Error reading text on page %d: %s", page_idx, exc)

    return candidate_indices


def parse_graphical_column_schedule(page: fitz.Page, page_idx: int) -> Dict[str, ResolvedColumnDetail]:
    """
    Extract Grid Location -> Column Profile mappings from a Graphical Column Schedule sheet (e.g. Page 18, Page 31).
    """
    results: Dict[str, ResolvedColumnDetail] = {}
    words = page.get_text("words")

    grid_words = []
    profile_words = []
    _NON_GRID_PREFIXES = ("ESR-", "CFR-", "TYP-", "NO-", "DETAIL-", "REF-", "SIM-", "S-", "THRU-", "TYP-")

    for w in words:
        txt = w[4].strip()
        g_m = _GRID_LOC_PATTERN.match(txt)
        if g_m and not any(txt.upper().startswith(p) for p in _NON_GRID_PREFIXES):
            if any(c.isalpha() for c in txt) and any(c.isdigit() for c in txt) and len(txt) <= 10:
                grid_words.append((txt.upper(), w[0], w[1], w[2], w[3]))
        p_m = _AISC_PROFILE_PATTERN.search(txt)
        if p_m:
            profile_words.append((p_m.group(1).upper().replace(" ", ""), w[0], w[1], w[2], w[3]))

    for g_txt, gx0, gy0, gx1, gy1 in grid_words:
        gcx = (gx0 + gx1) / 2.0
        col_profiles = [
            (p_txt, px0, py0, px1, py1) for p_txt, px0, py0, px1, py1 in profile_words
            if abs(gcx - (px0 + px1) / 2.0) < 45.0
        ]
        if col_profiles:
            col_profiles.sort(key=lambda x: x[2], reverse=True)
            tier1_profile = col_profiles[0][0]
            wt = get_weight_per_ft(tier1_profile)
            detail = ResolvedColumnDetail(
                mark=g_txt,
                normalized_mark=g_txt,
                profile=tier1_profile,
                weight_per_ft=wt,
                source_page_idx=page_idx,
                source_page_num=page_idx + 1,
                status="resolved",
                confidence_score=15,
            )
            results[g_txt] = detail
            parts = g_txt.split("-")
            if len(parts) == 2:
                rev = f"{parts[1]}-{parts[0]}"
                results[rev] = detail

    return results


def parse_vertical_column_schedule(page: fitz.Page, page_idx: int) -> Dict[str, ResolvedColumnDetail]:
    """
    Extract Column Marks (C1, C2, C3, C4, PU1, PU2) and their assigned profiles from vertical schedule tables.
    """
    results: Dict[str, ResolvedColumnDetail] = {}
    words = page.get_text("words")

    mark_words = []
    for w in words:
        txt = w[4].strip().upper()
        # Match: C1, CC1, CC2, C1A, CC1A, PU1, POST1, COL1
        if _COL_MARK_RE.match(normalize_mark(txt)):
            xc = (w[0] + w[2]) / 2.0
            yc = (w[1] + w[3]) / 2.0
            mark_words.append((normalize_mark(txt), xc, yc, w))

    profile_words = []
    for w in words:
        txt = w[4].strip().upper().replace(" ", "")
        p_m = _AISC_PROFILE_PATTERN.search(txt)
        if p_m:
            prof = p_m.group(1).upper().replace(" ", "")
            xc = (w[0] + w[2]) / 2.0
            yc = (w[1] + w[3]) / 2.0
            profile_words.append((prof, xc, yc, w))

    for m_txt, m_xc, m_yc, m_w in mark_words:
        col_profs = [p for p in profile_words if abs(p[1] - m_xc) < 35.0]
        if col_profs:
            profs_for_mark = [p[0] for p in sorted(col_profs, key=lambda z: z[2])]
            level1_prof = max(profs_for_mark, key=lambda p: get_weight_per_ft(p) or 0)
            wt = get_weight_per_ft(level1_prof)
            n_m = normalize_mark(m_txt)
            detail = ResolvedColumnDetail(
                mark=m_txt,
                normalized_mark=n_m,
                profile=level1_prof,
                weight_per_ft=wt,
                source_page_idx=page_idx,
                source_page_num=page_idx + 1,
                status="resolved",
                confidence_score=12,
            )
            results[n_m] = detail
            results[m_txt] = detail
    return results


def parse_schedule_page_details(page: fitz.Page, page_idx: int) -> Dict[str, ResolvedColumnDetail]:
    """
    Extract all column/baseplate/grid mark -> (profile, baseplate, dims, anchors) mappings from a schedule page.
    """
    results: Dict[str, ResolvedColumnDetail] = {}

    text_upper = page.get_text().upper()
    if any(kw in text_upper for kw in ["COLUMN SCHEDULE", "GRAPHICAL", "COLUMN LOCATIONS", "COLUMN MARK"]):
        graph_results = parse_graphical_column_schedule(page, page_idx)
        results.update(graph_results)

    # Check for vertical column schedules (e.g. Bayhealth Page 3)
    if "COLUMN" in text_upper or "SCHEDULE" in text_upper:
        vert_results = parse_vertical_column_schedule(page, page_idx)
        results.update(vert_results)

    try:
        blocks = page.get_text("blocks")
        for b in blocks:
            block_text = b[4]
            lines = [l.strip() for l in block_text.split("\n") if l.strip()]

            i = 0
            while i < len(lines):
                line = lines[i]
                n_m = normalize_mark(line)

                # Check for BP-X (Base Plate Schedule)
                if re.match(r"^BP\d{1,4}[A-Z]?$", n_m):
                    bp_dims = None
                    anchors = None
                    if i + 2 < len(lines):
                        w = lines[i+1] if i+1 < len(lines) else ""
                        v = lines[i+2] if i+2 < len(lines) else ""
                        t = lines[i+5] if i+5 < len(lines) else ""
                        bp_dims = f"{w} x {v} x {t}".strip(" x")
                        if i + 7 < len(lines):
                            anchors = lines[i+7]

                    score = 8
                    results[n_m] = ResolvedColumnDetail(
                        mark=line,
                        normalized_mark=n_m,
                        profile=None,
                        base_plate_mark=line,
                        base_plate_dims=bp_dims,
                        anchor_rods=anchors,
                        source_page_idx=page_idx,
                        source_page_num=page_idx + 1,
                        status="resolved",
                        raw_snippet=" ".join(lines[i:i+6]),
                        confidence_score=score,
                    )

                # Check for C1, CC1, CC2, C2 etc. (Column Schedule marks)
                # Matches: C\d, CC\d, CL\d and any 1-3 letter prefix + digits
                elif _COL_MARK_RE.match(n_m):
                    profile = None
                    bp_dims = None
                    bp_mark = None
                    anchors = None

                    for lookahead in range(1, min(6, len(lines) - i)):
                        target_line = lines[i + lookahead]
                        if re.match(r"^C\d{1,3}[A-Z]?$", normalize_mark(target_line)):
                            break

                        p_match = _AISC_PROFILE_PATTERN.search(target_line)
                        if p_match and not profile:
                            profile = p_match.group(1).upper().replace(" ", "")

                        bp_d_match = _BP_DIM_PATTERN.search(target_line)
                        if bp_d_match and not bp_dims:
                            bp_dims = bp_d_match.group(1).strip()

                        bp_m_match = _BP_MARK_PATTERN.search(target_line)
                        if bp_m_match and not bp_mark:
                            bp_mark = bp_m_match.group(1).upper()

                        anc_match = _ANCHOR_PATTERN.search(target_line)
                        if anc_match and not anchors:
                            anchors = anc_match.group(1).strip()

                    if profile or bp_dims or bp_mark:
                        score = (10 if profile else 0) + (5 if bp_dims else 0) + (3 if anchors else 0)
                        wt = get_weight_per_ft(profile) if profile else None

                        if n_m not in results or score > results[n_m].confidence_score:
                            results[n_m] = ResolvedColumnDetail(
                                mark=line,
                                normalized_mark=n_m,
                                profile=profile,
                                weight_per_ft=wt,
                                base_plate_mark=bp_mark,
                                base_plate_dims=bp_dims,
                                anchor_rods=anchors,
                                source_page_idx=page_idx,
                                source_page_num=page_idx + 1,
                                status="resolved" if profile else "unresolved",
                                raw_snippet=" ".join(lines[i:i+4]),
                                confidence_score=score,
                            )
                i += 1
    except Exception as exc:
        logger.warning("Text block scanning on page %d failed: %s", page_idx, exc)

    return results


def resolve_foundation_plan_columns(
    pdf_path: str,
    page_idx: int,
    column_member_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Direct spatial association, schedule resolution, and ghost pruning for Foundation Plan columns:
    1. Extracts nearby profile callouts (W14X176, HSS8X8X1/2) and Base Plate marks (BP-1, BP-7) next to each column symbol.
    2. Matches Grid References (A-1, B-5, C-6) against Graphical Column Schedules.
    3. Cross-references Base Plate marks against the document's Schedule sheets.
    4. Deduplicates overlapping detections at the same coordinate.
    5. Prunes unreferenced ghost intersections when a schedule is present in the document.
    """
    if not os.path.exists(pdf_path) or column_member_rows is None:
        return column_member_rows

    try:
        doc = fitz.open(pdf_path)
        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            return column_member_rows

        fp_page = doc[page_idx]
        words = fp_page.get_text("words")
        pw = fp_page.rect.width
        ph = fp_page.rect.height

        # 1. Extract Grid Lines & Real Bubble Labels on Plan
        import main
        bounds = main.find_plan_boundary(fp_page, pw, ph)
        v_lines, h_lines, v_labels, h_labels = main.extract_grid_lines(fp_page, pw, ph, bounds)

        # 2. Pre-extract all profile and BP words on the Plan
        profile_tokens = []
        bp_tokens = []
        col_mark_tokens = []

        mw_w = fp_page.mediabox.width if fp_page.rotation in (90, 270) else fp_page.rect.width
        mw_h = fp_page.mediabox.height if fp_page.rotation in (90, 270) else fp_page.rect.height

        for w in words:
            txt = w[4].strip()
            raw_cx = (w[0] + w[2]) / 2
            raw_cy = (w[1] + w[3]) / 2
            if fp_page.rotation == 90:
                wx = raw_cy / mw_h
                wy = 1.0 - (raw_cx / mw_w)
            elif fp_page.rotation == 180:
                wx = 1.0 - (raw_cx / mw_w)
                wy = 1.0 - (raw_cy / mw_h)
            elif fp_page.rotation == 270:
                wx = 1.0 - (raw_cy / mw_h)
                wy = raw_cx / mw_w
            else:
                wx = raw_cx / mw_w
                wy = raw_cy / mw_h

            p_m = _AISC_PROFILE_PATTERN.search(txt)
            if p_m:
                profile_tokens.append((p_m.group(1).upper().replace(" ", ""), wx, wy))

            bp_m = _BP_MARK_PATTERN.search(txt)
            if bp_m:
                bp_tokens.append((bp_m.group(1).upper(), wx, wy))

            c_m = _MARK_PATTERN.search(txt)
            if c_m and _COL_MARK_RE.match(normalize_mark(c_m.group(1))):
                col_mark_tokens.append((normalize_mark(c_m.group(1)), wx, wy))

        # 3. Scan PDF for Schedule Sheets & Graphical Column Schedules
        global_schedule_index: Dict[str, ResolvedColumnDetail] = {}

        for p_i in range(len(doc)):
            page = doc[p_i]
            txt = page.get_text().upper()
            if any(kw in txt for kw in ["COLUMN SCHEDULE", "GRAPHICAL", "BASE PLATE", "BASEPLATE", "COLUMN MARK", "COLUMN LOCATIONS"]):
                details = parse_schedule_page_details(page, p_i)
                for k, d in details.items():
                    if k not in global_schedule_index or d.confidence_score > global_schedule_index[k].confidence_score:
                        global_schedule_index[k] = d

        doc.close()

        # Helper to find grid label for coordinates
        def find_grid_at_pos(norm_x: float, norm_y: float) -> Optional[Tuple[str, str]]:
            pt_x = norm_x * pw
            pt_y = norm_y * ph
            if not v_labels or not h_labels:
                return None
            best_v = min(v_labels.keys(), key=lambda gx: abs(pt_x - gx), default=None)
            best_h = min(h_labels.keys(), key=lambda gy: abs(pt_y - gy), default=None)
            grid_tol = max(45.0, min(pw, ph) * 0.035)
            if best_v is not None and best_h is not None:
                if abs(pt_x - best_v) <= grid_tol and abs(pt_y - best_h) <= grid_tol:
                    return (v_labels[best_v], h_labels[best_h])
            return None

        # 4. Resolve every existing extracted column
        resolved_rows: List[Dict[str, Any]] = []

        for row in column_member_rows:
            if row.get("kind") != "column":
                resolved_rows.append(row)
                continue

            geo = row.get("geometry") or {}
            cx = geo.get("x", 0)
            cy = geo.get("y", 0)
            raw_cx = geo.get("raw_x", cx)
            raw_cy = geo.get("raw_y", cy)

            existing_sec = row.get("section")
            if existing_sec == "Column" or existing_sec == "Col" or existing_sec == "?":
                existing_sec = None

            _RADIUS = 0.08

            # Priority 1: Grid Location match against Graphical Column Schedule (e.g. A-1 -> W12X120, E-2.2 -> HSS12X12X3/4)
            g_pair = find_grid_at_pos(cx, cy)
            if g_pair is None:
                g_pair = find_grid_at_pos(raw_cx, raw_cy)
            grid_detail = None
            if g_pair:
                v_l, h_l = g_pair
                g_ref1 = f"{v_l}-{h_l}"
                g_ref2 = f"{h_l}-{v_l}"
                geo["grid_ref"] = g_ref1
                grid_detail = global_schedule_index.get(g_ref1) or global_schedule_index.get(g_ref2)

            # Priority 2: Nearby BP mark or Column Mark (e.g. C1, SC1, BP-1)
            nearest_bp = None
            min_bpd = _RADIUS
            for bp, bx, by in bp_tokens:
                d = min(math.hypot(cx - bx, cy - by),
                        math.hypot(raw_cx - bx, raw_cy - by))
                if d < min_bpd:
                    min_bpd = d
                    nearest_bp = bp

            nearest_cmark = None
            min_cmd = _RADIUS
            for cm, cmx, cmy in col_mark_tokens:
                d = min(math.hypot(cx - cmx, cy - cmy),
                        math.hypot(raw_cx - cmx, raw_cy - cmy))
                if d < min_cmd:
                    min_cmd = d
                    nearest_cmark = cm

            mark_detail = (global_schedule_index.get(nearest_cmark) if nearest_cmark else None) or \
                          (global_schedule_index.get(nearest_bp) if nearest_bp else None)

            # Priority 3: Direct profile label if explicitly next to symbol and no schedule profile exists
            nearest_p = None
            min_pd = 0.055
            for p, px, py in profile_tokens:
                d = min(math.hypot(cx - px, cy - py),
                        math.hypot(raw_cx - px, raw_cy - py))
                if d < min_pd:
                    min_pd = d
                    nearest_p = p

            # Determine winning profile & specifications:
            # Schedule grid match & Column marks take priority over incidental framing beam text
            resolved_p = (grid_detail.profile if grid_detail else None) or \
                         (mark_detail.profile if mark_detail else None) or \
                         existing_sec or nearest_p
            winning_bp = (grid_detail.base_plate_mark if grid_detail else None) or \
                         (mark_detail.base_plate_mark if mark_detail else None) or nearest_bp
            winning_src = (grid_detail.source_page_num if grid_detail else None) or \
                          (mark_detail.source_page_num if mark_detail else None)
            winning_dims = (grid_detail.base_plate_dims if grid_detail else None) or \
                           (mark_detail.base_plate_dims if mark_detail else None)
            winning_anchors = (grid_detail.anchor_rods if grid_detail else None) or \
                              (mark_detail.anchor_rods if mark_detail else None)

            # Filter out Concrete Columns / Concrete Piers (CC1, CC2, CP1, etc.)
            # If a candidate is identified by a concrete column/pier mark and has no structural steel shape or steel base plate,
            # exclude it completely from the structural steel takeoff.
            if nearest_cmark and _CONCRETE_MARK_RE.match(nearest_cmark) and not resolved_p and not winning_bp:
                logger.info(f"Skipping concrete column/pier mark {nearest_cmark} at ({cx:.3f}, {cy:.3f}) — concrete scope, not steel")
                continue

            if resolved_p or grid_detail or mark_detail or winning_bp:
                row["section"] = resolved_p
                geo["resolved_profile"] = resolved_p
                geo["base_plate_mark"] = winning_bp
                if winning_src:
                    geo["source_page_num"] = winning_src
                if winning_dims:
                    geo["base_plate_dims"] = winning_dims
                if winning_anchors:
                    geo["anchor_rods"] = winning_anchors
                geo["resolution_status"] = "resolved"
                resolved_rows.append(row)
            else:
                # Retain all physical column candidates as unresolved columns
                row["section"] = None
                geo["resolved_profile"] = None
                geo["resolution_status"] = "unresolved"
                resolved_rows.append(row)

        # 5. Strict Spatial Deduplication: Never allow duplicate markers on the same column
        # Merge any columns that are within 3.5% of page width of each other OR share the exact same grid intersection
        deduped_rows: List[Dict[str, Any]] = []
        for r in resolved_rows:
            if r.get("kind") != "column":
                deduped_rows.append(r)
                continue
            r_geo = r.get("geometry") or {}
            rx = r_geo.get("raw_x", r_geo.get("x", 0))
            ry = r_geo.get("raw_y", r_geo.get("y", 0))
            r_grid = r_geo.get("grid_ref")
            
            # Check if an existing column is already at this physical position or grid intersection
            dup_idx = -1
            for idx, existing in enumerate(deduped_rows):
                if existing.get("kind") != "column":
                    continue
                e_geo = existing.get("geometry") or {}
                ex = e_geo.get("raw_x", e_geo.get("x", 0))
                ey = e_geo.get("raw_y", e_geo.get("y", 0))
                e_grid = e_geo.get("grid_ref")
                
                # Check match by exact grid ref or close proximity
                same_grid = bool(r_grid and e_grid and r_grid == e_grid)
                close_dist = math.hypot(rx - ex, ry - ey) < 0.012
                
                if (same_grid and close_dist) or (close_dist and math.hypot(rx - ex, ry - ey) < 0.008):
                    dup_idx = idx
                    break
            
            if dup_idx >= 0:
                # Merge into existing: keep whichever has the resolved section / better information
                existing = deduped_rows[dup_idx]
                e_geo = existing.get("geometry") or {}
                if not existing.get("section") and r.get("section"):
                    existing["section"] = r.get("section")
                    e_geo["resolved_profile"] = r.get("section")
                if not e_geo.get("base_plate_mark") and r_geo.get("base_plate_mark"):
                    e_geo["base_plate_mark"] = r_geo.get("base_plate_mark")
                if not e_geo.get("grid_ref") and r_grid:
                    e_geo["grid_ref"] = r_grid
            else:
                deduped_rows.append(r)

        column_member_rows.clear()
        column_member_rows.extend(deduped_rows)
        return column_member_rows

    except Exception as exc:
        logger.exception("Error in resolve_foundation_plan_columns: %s", exc)
        return column_member_rows
