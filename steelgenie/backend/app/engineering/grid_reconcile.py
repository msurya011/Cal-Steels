"""
Reconcile the Gemini vision pass against the deterministic vector pass.

Division of labour
------------------
The two passes are good at different things, and the reconciliation exists to
take the best of each rather than to pick a winner:

  * The DETERMINISTIC pass reads the PDF's own vector geometry. When it finds
    a grid, the coordinate is exact -- there is nothing to be more accurate
    than. But it only sees grids whose bubble is real vector text sitting on a
    real vector circle, so it misses grids on a scanned page, on a flattened
    export, or wherever the bubble was drawn as an image.

  * The GEMINI pass reads the sheet the way an estimator does, so it finds
    grids the vector pass cannot see, and it reads the printed dimension
    strings and the scale note. But its coordinates are normalised estimates
    from a downscaled raster -- at 2048 px on a D-size sheet, one pixel is
    already about 2 inches at 1/8" scale, so its positions are never the
    thing to measure with.

Hence the rule this module enforces:

    GEOMETRY DECIDES WHERE. VISION DECIDES WHAT EXISTS.

A grid found by both is snapped to the vector coordinate and marked
"both" -- the strongest state. A grid only Gemini saw is kept, with its
estimated position and a source of "vision_only", so a consumer can weight it
down or route it for review. A grid only the vector pass saw is kept as
"geometry_only" -- which usually means Gemini missed it, and is worth
surfacing because the prompt asks for high recall.

Disagreements are recorded, never silently resolved.

Chain reconciliation
--------------------
Gemini is asked to return long multi-grid dimensions separately from
adjacent-pair bays. A long run must equal the sum of the bays it covers. That
check needs no external ground truth -- both numbers come off the sheet -- and
it is the one test that reliably catches a MISSED grid, which is otherwise
invisible: a missing grid does not produce a wrong-looking number, it produces
one plausible bay where there should have been two.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

# A Gemini position (0-1000, from a <=2048px render) is worth about this much
# in page points before it stops being meaningful. Anything inside this of a
# vector grid is the same grid.
SNAP_TOL_FRAC_OF_MEDIAN_BAY = 0.35

# Chain closure tolerance: a long dimension must equal the sum of its parts.
CHAIN_TOL_INCHES = 1.0

# Upper bound on a single dimension. Overall building runs on these sheets
# reach ~160 ft; 400 leaves generous headroom while still catching a dropped
# apostrophe, which multiplies a reading by ten.
MAX_PLAUSIBLE_FT = 400.0


_DIM = re.compile(
    r"""^\s*\(?\s*
        (?:(?P<feet>\d+)\s*['’]\s*)?
        (?:[-–]\s*)?
        (?:(?P<inches>\d+)\s*)?
        (?:(?P<num>\d+)\s*/\s*(?P<den>\d+)\s*)?
        (?:["”])?\s*\)?\s*$""",
    re.VERBOSE,
)


def parse_feet(text: Optional[str]) -> Optional[float]:
    """
    Feet-inch-fraction string to decimal feet. Returns None for anything that
    is not a dimension, including "EQ".

    Two sanity rejects, both for OCR noise rather than for malformed input:

      * an inch component of 12 or more is not a dimension, it is a misread;
      * a span beyond MAX_PLAUSIBLE_FT is not a bay on a framing plan.

    Be clear about what the second one does and does not do. On the Milesburg
    sheet, 17'-10" was read as "170' - 3"" -- a dropped apostrophe shifts the
    magnitude tenfold and the result still parses cleanly. 170 ft is NOT
    caught here, and should not be: real overall runs on these sheets reach
    158 ft, so any bound tight enough to reject 170 would reject legitimate
    dimensions. The bound only stops the grossly absurd.

    A magnitude misread is therefore not a parsing problem and has no parsing
    fix. check_chains() is what catches it: 170' - 3" cannot be reconciled
    against the bays it spans, and the chain closure fails loudly.
    """
    if not text:
        return None
    t = " ".join(str(text).split())
    if t.upper() in ("EQ", "EQUAL"):
        return None
    m = _DIM.match(t)
    if not m or not any(m.groupdict().values()):
        return None
    feet = float(m.group("feet") or 0)
    inches = float(m.group("inches") or 0)
    if inches >= 12:
        return None
    if m.group("num") and m.group("den"):
        den = int(m.group("den"))
        if den == 0:
            return None
        inches += float(Fraction(int(m.group("num")), den))
    if feet == 0 and inches == 0:
        return None
    total = feet + inches / 12.0
    if total > MAX_PLAUSIBLE_FT:
        return None
    return round(total, 5)


def format_feet(v: float) -> str:
    """Decimal feet back to a drawing-style string, rounded to 1/16"."""
    total_sixteenths = round(v * 12 * 16)
    feet, rem = divmod(total_sixteenths, 12 * 16)
    inches, sixteenths = divmod(rem, 16)
    if sixteenths == 0:
        return f"{feet}' - {inches}\""
    frac = Fraction(sixteenths, 16)
    return f"{feet}' - {inches} {frac.numerator}/{frac.denominator}\""


def _sort_key(label: str) -> Tuple[int, float]:
    """
    Collation value for a grid designator: 8.4 sorts between 8 and 9, B.9
    between B and C, and 10 after 9 rather than between 1 and 2.

    Returns (family, value) rather than a bare number because letter and
    number values overlap -- B is 1 and so is grid 1. Within one axis that
    never matters, since an axis is all letters or all numbers, but any list
    holding both would interleave them. The family tag keeps the two runs
    separate: alpha (0) before numeric (1), each internally ordered.
    """
    label = str(label).strip().upper()
    m = re.match(r"^([A-Z])(?:\.(\d+))?$", label)
    if m:
        return (0, (ord(m.group(1)) - 65) + (float("0." + m.group(2)) if m.group(2) else 0.0))
    m = re.match(r"^(\d+)(?:\.(\d+))?$", label)
    if m:
        return (1, float(m.group(1)) + (float("0." + m.group(2)) if m.group(2) else 0.0))
    return (2, 0.0)


# ---------------------------------------------------------------------------
# Grid reconciliation
# ---------------------------------------------------------------------------

def reconcile_grids(vector_grids: List[Dict[str, Any]],
                    gemini_grids: List[Dict[str, Any]],
                    page_extent_pts: float,
                    coord_key: str) -> List[Dict[str, Any]]:
    """
    Merge one axis.

    vector_grids: from run_deterministic_geometry_pass -- {"label", "x"|"y",
                  "coord_source", ...}, coordinates in PDF points.
    gemini_grids: from the vision pass -- {"label", "line_position", ...},
                  line_position normalised 0-1000.
    coord_key:    "x" or "y", whichever the vector records use for this axis.

    Returns one record per grid, sorted along the axis.
    """
    by_label: Dict[str, Dict[str, Any]] = {}

    for g in vector_grids:
        label = str(g["label"]).strip()
        by_label[label] = {
            "label": label,
            "sort_key": _sort_key(label),
            "coord_pts": float(g[coord_key]),
            "source": "geometry_only",
            "coord_authority": "vector_geometry",
            "coord_source": g.get("coord_source"),
            "is_sub_grid": bool(g.get("is_secondary")),
            "vision_coord_pts": None,
            "position_delta_pts": None,
        }

    # Median bay from the vector pass gives the snap tolerance a physical
    # meaning -- a fixed point tolerance would be far too tight on a 1/16"
    # sheet and far too loose on a 1/2" detail.
    coords = sorted(r["coord_pts"] for r in by_label.values())
    gaps = [b - a for a, b in zip(coords, coords[1:]) if b - a > 1.0]
    median_bay = sorted(gaps)[len(gaps) // 2] if gaps else page_extent_pts * 0.1
    snap_tol = max(median_bay * SNAP_TOL_FRAC_OF_MEDIAN_BAY, 4.0)

    for g in gemini_grids:
        label = str(g.get("label", "")).strip()
        if not label:
            continue
        pos = g.get("line_position")
        vision_pts = (float(pos) / 1000.0 * page_extent_pts) if pos is not None else None

        existing = by_label.get(label)
        if existing is not None:
            # Same grid, seen twice. Geometry keeps the coordinate; the vision
            # estimate is retained only so a gross disagreement is visible.
            existing["source"] = "both"
            existing["vision_coord_pts"] = None if vision_pts is None else round(vision_pts, 2)
            if vision_pts is not None:
                delta = abs(vision_pts - existing["coord_pts"])
                existing["position_delta_pts"] = round(delta, 2)
                existing["position_disagreement"] = delta > snap_tol
            continue

        # Gemini found a grid the vector pass did not. Keep it -- this is the
        # scanned-sheet and flattened-export case the vision pass exists for --
        # but never let its estimate masquerade as a measured coordinate.
        by_label[label] = {
            "label": label,
            "sort_key": _sort_key(label),
            "coord_pts": vision_pts,
            "source": "vision_only",
            "coord_authority": "vision_estimate",
            "coord_source": None,
            "is_sub_grid": bool(g.get("is_sub_grid")) or ("." in label),
            "vision_coord_pts": None if vision_pts is None else round(vision_pts, 2),
            "position_delta_pts": None,
        }

    out = [r for r in by_label.values() if r["coord_pts"] is not None]
    out.sort(key=lambda r: r["coord_pts"])
    return out


# ---------------------------------------------------------------------------
# Chain reconciliation
# ---------------------------------------------------------------------------

def check_chains(bay_dimensions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Every "total_building" dimension must equal the sum of the
    "consecutive_bay" dimensions it spans.

    This is the check that catches a MISSED grid. A missing grid does not make
    a number look wrong -- it silently merges two bays into one plausible span.
    The long dimension is the only thing on the sheet that disagrees.
    """
    bays = [b for b in bay_dimensions if b.get("track") != "total_building"]
    totals = [b for b in bay_dimensions if b.get("track") == "total_building"]

    # Index consecutive bays by ordered label pair.
    bay_by_pair: Dict[Tuple[str, str], float] = {}
    for b in bays:
        v = parse_feet(b.get("dimension_text"))
        if v is None:
            continue
        f, t = str(b.get("from_grid")).strip(), str(b.get("to_grid")).strip()
        bay_by_pair[(f, t)] = v
        bay_by_pair[(t, f)] = v

    results = []
    for tot in totals:
        stated = parse_feet(tot.get("dimension_text"))
        f, t = str(tot.get("from_grid")).strip(), str(tot.get("to_grid")).strip()
        mids = [str(m).strip() for m in (tot.get("intermediate_grids") or [])]
        walk = [f] + mids + [t]

        parts, missing = [], []
        for a, b in zip(walk, walk[1:]):
            v = bay_by_pair.get((a, b))
            if v is None:
                missing.append(f"{a}->{b}")
            else:
                parts.append(v)

        summed = round(sum(parts), 5) if parts else None
        entry = {
            "span": f"{f} -> {t}",
            "stated_text": tot.get("dimension_text"),
            "stated_ft": stated,
            "sum_of_parts_ft": summed,
            "parts_found": len(parts),
            "parts_missing": missing,
        }
        if stated is not None and summed is not None and not missing:
            delta_in = (summed - stated) * 12.0
            entry["delta_inches"] = round(delta_in, 2)
            entry["pass"] = abs(delta_in) <= CHAIN_TOL_INCHES
            if not entry["pass"]:
                entry["diagnosis"] = (
                    "sum exceeds the stated run -- a bay is double counted or a "
                    "dimension was misread"
                    if delta_in > 0 else
                    "sum falls short of the stated run -- a grid between these two "
                    "was probably missed"
                )
        else:
            entry["pass"] = None
            entry["diagnosis"] = ("could not evaluate: "
                                  + ("missing bays " + ", ".join(missing) if missing
                                     else "unparseable dimension text"))
        results.append(entry)
    return results


def summarise(grids_v: List[Dict[str, Any]], grids_h: List[Dict[str, Any]],
              chains: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One-glance verdict for a sheet."""
    allg = grids_v + grids_h
    def count(src):
        return sum(1 for g in allg if g["source"] == src)
    evaluated = [c for c in chains if c.get("pass") is not None]
    return {
        "grids_total": len(allg),
        "confirmed_by_both": count("both"),
        "geometry_only": count("geometry_only"),
        "vision_only": count("vision_only"),
        "position_disagreements": sum(1 for g in allg if g.get("position_disagreement")),
        "chain_checks_run": len(evaluated),
        "chain_checks_passed": sum(1 for c in evaluated if c["pass"]),
        "chain_checks_failed": [c for c in evaluated if not c["pass"]],
        "verdict": (
            "FAIL - chain closure" if any(not c["pass"] for c in evaluated)
            else "REVIEW - vision-only grids present" if count("vision_only")
            else "PASS" if evaluated
            else "UNVERIFIED - no multi-grid dimension to check against"
        ),
    }
