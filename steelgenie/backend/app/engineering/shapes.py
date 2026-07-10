"""
Section-property lookups used by the build engine.

Prefers the `sections` library table (seeded AISC shapes, see
app/services/database.py _load_db) and falls back to parsing weight-per-foot
directly out of the shape designation (e.g. "W12X26" -> 26 lb/ft), which
covers any AISC W/C/MC/S/HP/WT/MT/ST shape even if it isn't in the seed data.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.services.database import get_db

logger = logging.getLogger(__name__)

_WEIGHT_RE = re.compile(r"^(?:W|C|MC|S|HP|WT|MT|ST)\d+(?:\.\d+)?[Xx](\d+(?:\.\d+)?)$")

# Fallback nominal weight-per-ft for shape families whose designation doesn't
# encode weight directly (HSS/pipe/angle/plate accessories). Approximate,
# used only when the shape isn't in the sections library.
_FAMILY_DEFAULT_WT_PER_FT = {
    "HSS": 10.0,
    "PIPE": 8.0,
    "L": 3.5,
    "PL": 0.0,  # plates are weighed by area, not length — handled separately
}


def get_weight_per_ft(section: Optional[str]) -> Optional[float]:
    """Return lb/ft for a shape designation, or None if unknown."""
    if not section:
        return None
    section = section.strip().upper()

    m = _WEIGHT_RE.match(section)
    if m:
        return float(m.group(1))

    try:
        db = get_db()
        row = db.table("sections").select("weight_per_ft").eq("designation", section).maybe_single().execute()
        if row and row.data:
            return float(row.data.get("weight_per_ft") or 0)
    except Exception as exc:
        logger.warning("Section weight lookup failed for %r: %s", section, exc)

    for prefix, wt in _FAMILY_DEFAULT_WT_PER_FT.items():
        if section.startswith(prefix):
            return wt

    return None


def get_depth_in(section: Optional[str]) -> Optional[float]:
    """Return nominal depth (in) for a shape, used for connection/plate sizing."""
    if not section:
        return None
    section = section.strip().upper()

    try:
        db = get_db()
        row = db.table("sections").select("depth_in").eq("designation", section).maybe_single().execute()
        if row and row.data and row.data.get("depth_in"):
            return float(row.data["depth_in"])
    except Exception as exc:
        logger.warning("Section depth lookup failed for %r: %s", section, exc)

    # Fall back to the leading number in the designation (nominal depth, in).
    m = re.match(r"^(?:W|C|MC|S|HP|WT|MT|ST)(\d+(?:\.\d+)?)", section)
    if m:
        return float(m.group(1))
    return None


def section_type_of(section: Optional[str]) -> Optional[str]:
    if not section:
        return None
    m = re.match(r"^([A-Z]+)", section.strip().upper())
    return m.group(1) if m else None


def plate_weight_lbs(length_in: float, width_in: float, thickness_in: float) -> float:
    """Steel plate weight: 490 lb/ft^3 -> 3.4028 lb per (in^2 x in thickness)."""
    volume_in3 = length_in * width_in * thickness_in
    return round(volume_in3 * 0.2833, 2)  # 0.2833 lb/in^3 for mild steel
