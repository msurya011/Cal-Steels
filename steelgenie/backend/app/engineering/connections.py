"""
Connection design rule engine.

Selects a simple shear connection (bolted double angle or shear tab) sized to
the beam-end reaction, using published AISC-style allowable single-shear
bolt values (ASD, A325-N threads-included, per AISC Steel Construction
Manual Table 7-1) and a plate/angle-thickness priority list from project
configuration.

ACCURACY CAVEAT: these bolt capacities are standard textbook allowable
values used to make the engine deterministic end-to-end; they are not a
substitute for a stamped connection design. Replacing them with full AISC
360 Chapter J bolt/weld/block-shear/bearing checks (with LRFD phi-factors)
is tracked in the roadmap (SRS "Improvement Opportunities") before this
engine is used for anything beyond estimating quantities.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.engineering import shapes

# ASD allowable single-shear capacity (kips/bolt), A325-N, AISC Table 7-1 style values.
_BOLT_SHEAR_KIPS_ASD = {
    0.625: 6.63,
    0.75: 9.30,
    0.875: 12.70,
    1.0: 16.50,
}
# LRFD available strength is materially higher than ASD allowable (phi=0.75 vs Omega=2.00);
# approximate the ratio rather than re-deriving nominal strength here.
_LRFD_MULTIPLIER = 1.6

_MIN_BOLTS = 2
_MAX_BOLTS = 8


def _bolt_capacity_kips(diameter_in: float, design_method: str) -> float:
    base = _BOLT_SHEAR_KIPS_ASD.get(diameter_in, _BOLT_SHEAR_KIPS_ASD[0.75])
    return base * _LRFD_MULTIPLIER if design_method == "LRFD" else base


def _select_bolts(reaction_kips: float, config: Dict[str, Any]) -> Tuple[int, float]:
    design_method = config.get("design_method", "ASD")
    priorities = (config.get("size_priorities") or {}).get("bolt_diameters") or [0.75, 0.875, 1.0]

    for diameter in priorities:
        capacity = _bolt_capacity_kips(diameter, design_method)
        for n in range(_MIN_BOLTS, _MAX_BOLTS + 1):
            if n * capacity >= reaction_kips:
                return n, diameter

    # Demand exceeds the largest priority option — cap out at max bolts/largest diameter.
    largest = max(priorities) if priorities else 1.0
    return _MAX_BOLTS, largest


def _select_plate_thickness(bolt_count: int, connection_type: str, config: Dict[str, Any]) -> float:
    key = "shear_tab_thickness" if connection_type == "shear_tab" else "double_angle_thickness"
    priorities = (config.get("size_priorities") or {}).get(key) or [0.375, 0.5, 0.625, 0.75]
    # Step up plate thickness as bolt count/demand grows (simplified bearing rule of thumb).
    idx = min(len(priorities) - 1, bolt_count // 3)
    return priorities[idx]


def design_simple_connection(
    member: Dict[str, Any],
    reaction_kips: float,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Design a simple (shear-only) beam-end connection.
    Returns connection metadata + accessory item specs (plates, bolts, welds).
    """
    connection_type = (config.get("connection_types") or {}).get("beam_column", "bolted_double_angle")
    materials = config.get("materials") or {}
    plate_grade = materials.get("PLATE", "A50")
    bolt_spec = materials.get("BOLT", "F3125A325N")
    electrode = materials.get("ELECTRODE", "E70XX")

    bolt_count, bolt_diameter = _select_bolts(reaction_kips, config)
    plate_thickness = _select_plate_thickness(bolt_count, connection_type, config)

    depth_in = shapes.get_depth_in(member.get("section")) or 12.0
    plate_length_in = round(max(6.0, 3.0 * (bolt_count - 1) + 3.0), 2)  # 3" bolt gauge + edge distance
    plate_width_in = 4.0 if connection_type == "bolted_double_angle" else 3.5

    accessories: List[Dict[str, Any]] = []

    if connection_type == "bolted_double_angle":
        # Two angles per connection, symmetric about the web.
        angle_weight = shapes.plate_weight_lbs(plate_length_in, plate_width_in, 0.3125) * 2
        accessories.append({
            "category": "Angles",
            "section_type": "L",
            "section": f'L4x3-1/2x5/16 x {plate_length_in}"',
            "grade": plate_grade,
            "qty": 2,
            "weight_lbs": round(angle_weight, 2),
        })
    else:
        plate_weight = shapes.plate_weight_lbs(plate_length_in, plate_width_in, plate_thickness)
        accessories.append({
            "category": "Plates",
            "section_type": "PL",
            "section": f'PL{plate_thickness}x{plate_width_in}x{plate_length_in}',
            "grade": plate_grade,
            "qty": 1,
            "weight_lbs": plate_weight,
        })

    accessories.append({
        "category": "Bolts",
        "section_type": "HS",
        "section": f'{bolt_diameter}"x2" {bolt_spec}',
        "grade": bolt_spec,
        "qty": bolt_count,
        "weight_lbs": 0.0,
    })

    weld_studs = 0
    if config.get("labor_codes", {}).get("enabled") and member.get("kind") == "beam":
        # Composite-deck stud spacing rule of thumb: 1 stud / 2 ft of beam length.
        length_ft = float(member.get("length_ft") or 0)
        weld_studs = max(0, round(length_ft / 2))
        if weld_studs:
            accessories.append({
                "category": "Weld Studs",
                "section_type": "WS",
                "section": '3/4"x4" Weld Stud',
                "grade": materials.get("WELD_STUD", "A108"),
                "qty": weld_studs,
                "weight_lbs": 0.0,
            })

    return {
        "connection_type": connection_type,
        "reaction_kips": reaction_kips,
        "bolt_count": bolt_count,
        "bolt_diameter_in": bolt_diameter,
        "plate_thickness_in": plate_thickness,
        "electrode": electrode,
        "weld_studs": weld_studs,
        "accessories": accessories,
        "capacity_kips": round(bolt_count * _bolt_capacity_kips(bolt_diameter, config.get("design_method", "ASD")), 2),
    }
