"""
structural_schema.py
Converts /analyse member output → standardized 3D structural JSON model.

Coordinate system (Three.js / Y-up):
  X = drawing left→right (feet)
  Y = elevation in feet  — beams/joists at floor_elevation_ft, columns 0→floor_elevation_ft
  Z = drawing top→bottom inverted (feet)  ← PDFs have Y=0 at top

Framing plans represent a FLOOR LEVEL, not the ground.  Every beam and joist is
placed at floor_elevation_ft on the Y axis so that columns (0→floor_elevation_ft)
frame up to meet them, producing a recognisable building floor rather than a flat
plan lying on the ground.

Public:
  build_structural_model(members, page_width_pts, page_height_pts,
                         scale_ratio, source, page,
                         floor_elevation_ft=12.0) → dict
"""
import math
from typing import Optional
from structural_reconstruction import run_reconstruction

# ── Constants ─────────────────────────────────────────────────────────────────

# Default storey height used when floor_elevation_ft is auto-derived from page index.
# Callers can override by passing floor_elevation_ft explicitly to build_structural_model.
FLOOR_HEIGHT_FT = 14.0

# pts-per-foot from scale ratio:  864 / scale_ratio
#   1/8" scale (96:1) → 864/96 = 9.0 pt/ft
#   3/32" scale (128:1) → 864/128 = 6.75 pt/ft
def _ppf(scale_ratio: float) -> float:
    return 864.0 / scale_ratio

# Endpoints within this distance (ft) collapse to the same connectivity node
NODE_SNAP_FT = 2.0

_TYPE_PREFIX = {"beam": "B", "joist": "J", "brace": "BR", "column": "C"}


# ── Coordinate conversion ─────────────────────────────────────────────────────

def _frac_to_3d(fx: float, fy: float, w_ft: float, h_ft: float, elev: float = 0.0) -> list:
    """Fractional PDF coords [0,1]² → 3D model [x, elev, z] in feet."""
    return [round(fx * w_ft, 3), round(elev, 3), round((1.0 - fy) * h_ft, 3)]


# ── Member normalisation ──────────────────────────────────────────────────────

def _norm_type(raw: str) -> str:
    if raw == "column": return "column"
    if raw in ("brace", "vertical_brace", "horizontal_brace"): return "brace"
    if raw == "joist": return "joist"
    return "beam"


def _member_id(mtype: str, idx: int) -> str:
    return f"{_TYPE_PREFIX.get(mtype, 'M')}{idx + 1:03d}"


def _convert_member(
    m: dict, idx: int, w_ft: float, h_ft: float, source: str, page: int,
    floor_elev: float = 12.0,
    base_elev: float = 0.0,
) -> Optional[dict]:
    mtype = _norm_type(m.get("type", ""))
    mid   = _member_id(mtype, idx)

    # Columns MUST be perfectly vertical (same X,Z; only Y varies base_elev→floor_elev).
    # bx1/by1/bx2/by2 on a column is the symbol bounding box on the drawing,
    # NOT the base/top of the physical column — use its centre for X,Z.
    if mtype == "column":
        if m.get("bx1") is not None:
            # Centre of the symbol bounding box gives the column grid point
            cx_frac = (m["bx1"] + m["bx2"]) / 2.0
            cy_frac = (m["by1"] + m["by2"]) / 2.0
        else:
            cx_frac = m.get("x", 0.5)
            cy_frac = m.get("y", 0.5)
        base  = _frac_to_3d(cx_frac, cy_frac, w_ft, h_ft, base_elev)
        start = base[:]
        end   = [base[0], floor_elev, base[2]]
    elif m.get("bx1") is not None:
        # Beams / joists / braces: both endpoints at floor elevation
        start = _frac_to_3d(m["bx1"], m["by1"], w_ft, h_ft, floor_elev)
        end   = _frac_to_3d(m["bx2"], m["by2"], w_ft, h_ft, floor_elev)
    else:
        # Degenerate: centre-only data; flagged in validation
        cx_frac = m.get("x", 0.0)
        cy_frac = m.get("y", 0.0)
        pt      = _frac_to_3d(cx_frac, cy_frac, w_ft, h_ft, floor_elev)
        start, end = pt[:], pt[:]

    sx, sy, sz = start
    ex, ey, ez = end
    length = m.get("length_ft") or m.get("length") or round(
        math.sqrt((ex-sx)**2 + (ey-sy)**2 + (ez-sz)**2), 2
    )

    angle = m.get("angle_deg") or m.get("angle_from_h")
    if angle is None:
        dx, dz = ex - sx, ez - sz
        angle = round(math.degrees(math.atan2(abs(dz), abs(dx) + 1e-9)), 1)

    orientation = m.get("beam_dir") or ("H" if abs(ex-sx) >= abs(ez-sz) else "V")

    return {
        "id":               mid,
        "type":             mtype,
        "profile":          m.get("profile") or m.get("section_label") or None,
        "start":            start,
        "end":              end,
        "length":           round(float(length), 2),
        "angle_deg":        round(float(angle), 1),
        "orientation":      orientation,
        # Brace-specific metadata
        "config":           m.get("config"),
        "confidence":       m.get("confidence"),
        "role":             m.get("role"),
        "detection_method": m.get("detection_method"),
        # Provenance
        "source":           source,
        "page":             page,
        # Connectivity — filled by _build_connectivity
        "start_node":       None,
        "end_node":         None,
    }


# ── Connectivity graph ────────────────────────────────────────────────────────

def _build_connectivity(members: list) -> tuple:
    nodes: list  = []   # {"id", "x", "y", "z", "members": [...]}
    adjacency    = {m["id"]: [] for m in members}

    def _node(x, y, z) -> str:
        for n in nodes:
            if math.sqrt((n["x"]-x)**2 + (n["y"]-y)**2 + (n["z"]-z)**2) <= NODE_SNAP_FT:
                return n["id"]
        nid = f"N{len(nodes)+1:03d}"
        nodes.append({"id": nid, "x": round(x,2), "y": round(y,2), "z": round(z,2), "members": []})
        return nid

    for m in members:
        sx, sy, sz = m["start"]
        ex, ey, ez = m["end"]
        if [sx, sy, sz] == [ex, ey, ez]:
            continue  # degenerate — no connectivity
        sn = _node(sx, sy, sz)
        en = _node(ex, ey, ez)
        m["start_node"] = sn
        m["end_node"]   = en
        for n in nodes:
            if n["id"] in (sn, en) and m["id"] not in n["members"]:
                n["members"].append(m["id"])

    for n in nodes:
        mids = n["members"]
        for i, a in enumerate(mids):
            for b in mids[i+1:]:
                if b not in adjacency[a]: adjacency[a].append(b)
                if a not in adjacency[b]: adjacency[b].append(a)

    return nodes, {"adjacency": adjacency, "node_count": len(nodes)}


# ── Validation ────────────────────────────────────────────────────────────────

def _validate(members: list, nodes: list) -> dict:
    errors, warnings = [], []

    seen = set()
    for m in members:
        if m["id"] in seen:
            errors.append({"code": "DUPLICATE_ID", "member": m["id"], "msg": f"Duplicate member ID {m['id']}"})
        seen.add(m["id"])

    for m in members:
        if m["start"] == m["end"] and m["type"] != "column":
            errors.append({"code": "NO_GEOMETRY", "member": m["id"],
                           "msg": "Identical start/end — no endpoint data was available for this member"})
        elif m["length"] < 0.5:
            warnings.append({"code": "SHORT_MEMBER", "member": m["id"],
                             "msg": f"Length {m['length']}ft is unusually short"})

    no_profile = [m["id"] for m in members if not m.get("profile")]
    if no_profile:
        warnings.append({"code": "NO_PROFILE", "count": len(no_profile),
                         "members": no_profile[:10],
                         "msg": f"{len(no_profile)} member(s) have no steel section profile"})

    unconnected = [m["id"] for m in members
                   if m["type"] != "column" and not m.get("start_node")]
    if unconnected:
        warnings.append({"code": "UNCONNECTED", "count": len(unconnected),
                         "members": unconnected[:10],
                         "msg": f"{len(unconnected)} member(s) share no endpoints with other members"})

    type_counts: dict = {}
    for m in members:
        type_counts[m["type"]] = type_counts.get(m["type"], 0) + 1

    return {
        "pass":     len(errors) == 0,
        "errors":   errors,
        "warnings": warnings,
        "stats": {
            "total_members": len(members),
            "total_nodes":   len(nodes),
            "by_type":       type_counts,
            "no_profile":    len(no_profile),
        },
    }


# ── Gap analysis ──────────────────────────────────────────────────────────────

def _gap_analysis(members: list) -> dict:
    gaps = []
    type_set = {m["type"] for m in members}

    if "column" not in type_set:
        gaps.append({"item": "columns", "impact": "HIGH",
                     "msg": "No columns detected. Column extraction requires vector I/H cross-section symbols."})

    if "joist" not in type_set:
        gaps.append({"item": "joists", "impact": "MEDIUM",
                     "msg": "No joists detected. Joist extraction requires dense hatch-pattern recognition."})

    gaps.append({"item": "elevations", "impact": "HIGH",
                 "msg": "All members placed at Y=0. Multi-level models require elevation drawings."})

    no_profile_cnt = sum(1 for m in members if not m.get("profile"))
    if no_profile_cnt:
        gaps.append({"item": "member_profiles", "impact": "MEDIUM",
                     "msg": f"{no_profile_cnt} member(s) missing steel section — BOM takeoff will be incomplete."})

    gaps.append({"item": "connections", "impact": "HIGH",
                 "msg": "Connection details (bolts, welds, end plates) are not extracted."})

    gaps.append({"item": "structural_hierarchy", "impact": "MEDIUM",
                 "msg": "Floor/level assignment unknown. Story elevations required for multi-story models."})

    gaps.append({"item": "ifc_mapping", "impact": "LOW",
                 "msg": "IFC entity mapping not implemented (IfcBeam, IfcColumn, IfcMember). Required for BIM."})

    return {"missing": gaps, "total_gaps": len(gaps)}


# ── Public API ────────────────────────────────────────────────────────────────

def build_structural_model(
    members: list,
    page_width_pts: float,
    page_height_pts: float,
    scale_ratio: float,
    source: str,
    page: int,
    floor_elevation_ft: float = 14.0,
    base_elevation_ft: float = 0.0,
) -> dict:
    """
    Convert /analyse member list into the standardized structural JSON schema.

    Args:
        members:            list of member dicts from /analyse response
        page_width_pts:     PDF page width in PyMuPDF points
        page_height_pts:    PDF page height in PyMuPDF points
        scale_ratio:        drawing scale (e.g. 96 for 1/8"=1', 64 for 3/16"=1')
        source:             filename of the source drawing
        page:               0-indexed page number
        floor_elevation_ft: Y elevation for beams/joists/braces (top of storey).
                            Auto-derived from page index by the /model endpoint:
                            (page_index + 1) * FLOOR_HEIGHT_FT
        base_elevation_ft:  Y elevation for column bases (bottom of storey).
                            Auto-derived: page_index * FLOOR_HEIGHT_FT
    """
    ppf   = _ppf(scale_ratio)
    w_ft  = page_width_pts  / ppf
    h_ft  = page_height_pts / ppf

    print(f"\n[DEBUG 3D PIPELINE] source={source!r}  page={page}  scale_ratio={scale_ratio}")
    print(f"  page size:  {page_width_pts:.1f} x {page_height_pts:.1f} pts")
    print(f"  ppf:        {ppf:.4f} pts/ft")
    print(f"  world dims: {w_ft:.2f} ft wide  x  {h_ft:.2f} ft tall")
    print(f"  elevations: base={base_elevation_ft} ft  floor={floor_elevation_ft} ft")

    model_members = []
    for idx, m in enumerate(members):
        mm = _convert_member(
            m, idx, w_ft, h_ft, source, page,
            floor_elev=floor_elevation_ft,
            base_elev=base_elevation_ft,
        )
        if mm:
            model_members.append(mm)

    # ── Debug: first 3 beams ─────────────────────────────────────────────────
    beam_dbg = [mm for mm in model_members if mm["type"] == "beam"][:3]
    for mm in beam_dbg:
        raw = next((m for i, m in enumerate(members)
                    if _member_id(_norm_type(m.get("type","")), i) == mm["id"]), None)
        if raw and raw.get("bx1") is not None:
            raw_pts = (
                round(raw["bx1"] * page_width_pts, 1), round(raw["by1"] * page_height_pts, 1),
                round(raw["bx2"] * page_width_pts, 1), round(raw["by2"] * page_height_pts, 1),
            )
            frac = (raw["bx1"], raw["by1"], raw["bx2"], raw["by2"])
        else:
            raw_pts = frac = "no bbox"
        print(f"\n  [{mm['id']}]  profile={mm['profile']}")
        print(f"    raw PDF pts (x1,y1,x2,y2): {raw_pts}")
        print(f"    fractions   (fx1,fy1,fx2,fy2): {frac}")
        print(f"    world ft  start={mm['start']}  end={mm['end']}")
        print(f"    length={mm['length']} ft  angle={mm['angle_deg']}°")

    # ── Fix 2: per-page member bounding box (actual structural footprint) ────
    xs = [p[0] for mm in model_members for p in (mm["start"], mm["end"])]
    zs = [p[2] for mm in model_members for p in (mm["start"], mm["end"])]
    if xs:
        member_bbox = {
            "min_x": round(min(xs), 2), "max_x": round(max(xs), 2),
            "min_z": round(min(zs), 2), "max_z": round(max(zs), 2),
            "span_x": round(max(xs) - min(xs), 2),
            "span_z": round(max(zs) - min(zs), 2),
        }
        print(f"\n  MEMBER BBOX:")
        print(f"    X: {member_bbox['min_x']} → {member_bbox['max_x']} ft  (span {member_bbox['span_x']} ft)")
        print(f"    Z: {member_bbox['min_z']} → {member_bbox['max_z']} ft  (span {member_bbox['span_z']} ft)")
    else:
        member_bbox = None
    print("[DEBUG END]\n")

    # ── Structural Reconstruction Engine (Phases 2–7) ───────────────────────
    recon = run_reconstruction(
        model_members,
        floor_elevation_ft=floor_elevation_ft,
        base_elevation_ft=base_elevation_ft,
    )

    print("\n[RECONSTRUCTION LOG]")
    for line in recon.log:
        print(" ", line)
    print()

    gap_analysis = _gap_analysis(recon.members)

    return {
        "schema_version":     "1.0",
        "source":             source,
        "page":               page,
        "scale_ratio":        scale_ratio,
        "floor_elevation_ft": floor_elevation_ft,
        "base_elevation_ft":  base_elevation_ft,
        "units":              "feet",
        "page_dims":          {"width_ft": round(w_ft, 2), "height_ft": round(h_ft, 2)},
        "member_bbox":        member_bbox,
        "nodes":              recon.nodes,
        "members":            recon.members,
        "connectivity":       recon.connectivity,
        "hierarchy":          recon.hierarchy,
        "validation":         recon.report,
        "gap_analysis":       gap_analysis,
        "reconstruction_log": recon.log,
    }
