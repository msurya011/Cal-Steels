"""
Beam end reaction calculation.

Per the SRS (section 8.2) the reference product supports "Use plan reactions
+ auto-calculate missing" / "Ignore plan reactions" / "Plan reactions only",
with a UDL fallback model driven by a configurable percentage.

Our takeoff schema does not yet capture explicit plan-called-out reactions
(that requires OCR'ing load callouts near each beam, not implemented), so
every reaction today is computed with the UDL model:

    R = w * L * (udl_percent / 100) / 2

`w` (klf) is a configurable *assumed* uniform design load — NOT taken from
the actual structural loads on the drawing. This is intentionally explicit
and surfaced to the user (see build.py warnings) rather than silently
pretending to be a real structural analysis. Replacing this with true
plan-reaction OCR + load-path analysis is tracked as a follow-up.
"""
from __future__ import annotations

from typing import Any, Dict


def compute_beam_reaction_kips(member: Dict[str, Any], config: Dict[str, Any]) -> float:
    """Return the estimated end reaction (kips) for a beam/girder member."""
    reaction_cfg = config.get("beam_end_reaction", {}) or {}
    udl_percent = float(reaction_cfg.get("udl_percent", 50)) / 100.0
    assumed_udl_klf = float(reaction_cfg.get("default_udl_klf", 1.5))

    length_ft = float(member.get("length_ft") or 0)
    if length_ft <= 0:
        return 0.0

    reaction = assumed_udl_klf * length_ft * udl_percent / 2.0
    return round(reaction, 2)
