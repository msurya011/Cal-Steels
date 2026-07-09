"""
structural_reconstruction.py
Structural Reconstruction Engine — Phases 2–7

Converts a flat list of extracted member dicts into a properly connected,
cleaned, placed, and classified structural model.

Phases
------
  2 — Node Graph      : detect all intersections, build connectivity
  3 — Geometry Cleanup: merge collinear, deduplicate, remove fragments, snap
  4 — Placement       : trim beams to column faces, align endpoints
  5 — Hierarchy       : classify girder / beam / secondary / joist / brace
  6 — Elevation       : assign Y elevations per floor
  7 — Validation      : comprehensive report — floating, duplicate, zero-length

Public API
----------
  result = run_reconstruction(members, floor_elevation_ft, base_elevation_ft)
  result.members        -> cleaned + classified member list
  result.nodes          -> structural node list
  result.connectivity   -> adjacency dict
  result.hierarchy      -> {"girders":[], "beams":[], "secondary":[], ...}
  result.report         -> validation report dict
  result.log            -> list of human-readable phase summaries
"""

from __future__ import annotations
import math
import copy
from dataclasses import dataclass, field
from typing import Optional


# ── Tuning constants ───────────────────────────────────────────────────────────

SNAP_TOL         = 2.0   # ft — endpoints within this collapse to the same node
BEAM_COL_TOL     = 3.0   # ft — beam within this of a column XZ -> intersects it
COLLINEAR_ANG    = 2.5   # deg — max angle difference for collinear test
COLLINEAR_PERP   = 1.5   # ft — max perpendicular offset for collinear test
COLLINEAR_GAP    = 4.0   # ft — max gap between collinear segments to merge
MIN_LENGTH       = 0.5   # ft — segments shorter than this -> removed
DUP_TOL          = 1.5   # ft — endpoint proximity to detect duplicates
GIRDER_MIN_SPAN  = 15.0  # ft — minimum span to classify as primary girder
JOIST_MAX_SPAN   = 14.0  # ft — max span for joist classification
JOIST_DENSITY    = 3     # min parallel near-neighbours for joist classification
TRIM_COL_HALF_W  = 0.6   # ft — half column face width for beam trimming


# ── Geometry helpers ───────────────────────────────────────────────────────────

def _d2(x1, z1, x2, z2) -> float:
    return math.sqrt((x2 - x1) ** 2 + (z2 - z1) ** 2)


def _d3(p1, p2) -> float:
    return math.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2 + (p2[2]-p1[2])**2)


def _angle_deg(x1, z1, x2, z2) -> float:
    return math.degrees(math.atan2(abs(z2 - z1), abs(x2 - x1) + 1e-9))


def _point_to_seg_2d(px, pz, x1, z1, x2, z2) -> tuple[float, float]:
    """
    Returns (perpendicular_distance, parametric_t) from point to segment.
    t=0 -> start, t=1 -> end.
    """
    dx, dz = x2 - x1, z2 - z1
    seg2 = dx * dx + dz * dz
    if seg2 < 1e-9:
        return _d2(px, pz, x1, z1), 0.0
    t = max(0.0, min(1.0, ((px - x1) * dx + (pz - z1) * dz) / seg2))
    return _d2(px, pz, x1 + t * dx, z1 + t * dz), t


def _seg_intersect_2d(x1, z1, x2, z2, x3, z3, x4, z4,
                      tol: float = 0.02) -> Optional[tuple]:
    """
    Parametric 2D line-segment intersection.
    Returns (ix, iz, t, s) or None.  tol extends endpoints slightly.
    """
    dx1, dz1 = x2 - x1, z2 - z1
    dx2, dz2 = x4 - x3, z4 - z3
    denom = dx1 * dz2 - dz1 * dx2
    if abs(denom) < 1e-9:
        return None  # parallel
    t = ((x3 - x1) * dz2 - (z3 - z1) * dx2) / denom
    s = ((x3 - x1) * dz1 - (z3 - z1) * dx1) / denom
    if (-tol <= t <= 1 + tol) and (-tol <= s <= 1 + tol):
        return x1 + t * dx1, z1 + t * dz1, t, s
    return None


def _are_collinear(m1: dict, m2: dict) -> bool:
    """True if two segments lie on the same line within tolerances."""
    a1 = _angle_deg(m1["start"][0], m1["start"][2], m1["end"][0], m1["end"][2])
    a2 = _angle_deg(m2["start"][0], m2["start"][2], m2["end"][0], m2["end"][2])
    if abs(a1 - a2) > COLLINEAR_ANG and abs(abs(a1 - a2) - 180) > COLLINEAR_ANG:
        return False
    # Check perpendicular distance of m2 endpoints to m1's line
    dx, dz = m1["end"][0] - m1["start"][0], m1["end"][2] - m1["start"][2]
    length = math.sqrt(dx * dx + dz * dz)
    if length < 1e-9:
        return False
    nx, nz = -dz / length, dx / length  # unit normal
    for pt in (m2["start"], m2["end"]):
        perp = abs((pt[0] - m1["start"][0]) * nx + (pt[2] - m1["start"][2]) * nz)
        if perp > COLLINEAR_PERP:
            return False
    return True


# ── Phase 2 — Node Graph ───────────────────────────────────────────────────────

class NodeGraph:
    """
    Builds a structural node graph from raw members.

    Node types:
      column_base   — base of column
      column_top    — top of column (= beam floor elevation)
      beam_column   — where a beam crosses a column centre-line
      beam_beam     — where two beams cross each other
      endpoint      — isolated beam endpoint (no collocated column)
    """

    def __init__(self, snap_tol: float = SNAP_TOL):
        self.snap_tol = snap_tol
        self._nodes: list[dict] = []
        self._counter = 0

    # ── internal helpers ──

    def _new_node(self, x, y, z, ntype: str) -> str:
        self._counter += 1
        nid = f"N{self._counter:04d}"
        self._nodes.append({
            "id": nid,
            "x": round(x, 3), "y": round(y, 3), "z": round(z, 3),
            "type": ntype,
            "members": [],
        })
        return nid

    def _find(self, x, y, z) -> Optional[str]:
        for n in self._nodes:
            if _d3([n["x"], n["y"], n["z"]], [x, y, z]) <= self.snap_tol:
                return n["id"]
        return None

    def _get_or_create(self, x, y, z, ntype: str) -> str:
        nid = self._find(x, y, z)
        if nid:
            # Upgrade type if more specific
            node = self._by_id(nid)
            if node["type"] == "endpoint" and ntype != "endpoint":
                node["type"] = ntype
            return nid
        return self._new_node(x, y, z, ntype)

    def _by_id(self, nid: str) -> dict:
        return next(n for n in self._nodes if n["id"] == nid)

    def _attach(self, nid: str, mid: str):
        n = self._by_id(nid)
        if mid not in n["members"]:
            n["members"].append(mid)

    # ── public ──

    def build(self, members: list) -> tuple[list, list, dict]:
        """
        Returns (nodes, members_with_nodes_assigned, connectivity_dict).
        Input members are deep-copied; originals are not mutated.
        """
        members = copy.deepcopy(members)
        columns = [m for m in members if m["type"] == "column"]
        non_col = [m for m in members if m["type"] != "column"]

        # ── Step 1: endpoint nodes for every member ──
        for m in members:
            sx, sy, sz = m["start"]
            ex, ey, ez = m["end"]
            if [sx, sy, sz] == [ex, ey, ez]:
                m["start_node"] = None
                m["end_node"]   = None
                continue
            if m["type"] == "column":
                sn = self._get_or_create(sx, sy, sz, "column_base")
                en = self._get_or_create(ex, ey, ez, "column_top")
            else:
                sn = self._get_or_create(sx, sy, sz, "endpoint")
                en = self._get_or_create(ex, ey, ez, "endpoint")
            m["start_node"] = sn
            m["end_node"]   = en
            self._attach(sn, m["id"])
            self._attach(en, m["id"])

        # ── Step 2: beam-column intersections ──
        # Where a horizontal beam passes within BEAM_COL_TOL of a column's XZ
        col_tops = {}   # column_id -> (cx, cz, floor_y)
        for col in columns:
            col_tops[col["id"]] = (col["start"][0], col["start"][2], col["end"][1])

        for bm in non_col:
            x1, z1 = bm["start"][0], bm["start"][2]
            x2, z2 = bm["end"][0],   bm["end"][2]
            for cid, (cx, cz, fy) in col_tops.items():
                dist, t = _point_to_seg_2d(cx, cz, x1, z1, x2, z2)
                # Interior only — t in (0.05, 0.95) avoids double-counting endpoints
                if dist <= BEAM_COL_TOL and 0.05 < t < 0.95:
                    ix = x1 + t * (x2 - x1)
                    iz = z1 + t * (z2 - z1)
                    nid = self._get_or_create(ix, fy, iz, "beam_column")
                    self._attach(nid, bm["id"])
                    self._attach(nid, cid)

        # ── Step 3: beam-beam intersection nodes ──
        bm_list = non_col[:]
        for i, a in enumerate(bm_list):
            for b in bm_list[i + 1:]:
                # Skip if on significantly different floor levels
                if abs(a["start"][1] - b["start"][1]) > 1.0:
                    continue
                result = _seg_intersect_2d(
                    a["start"][0], a["start"][2],
                    a["end"][0],   a["end"][2],
                    b["start"][0], b["start"][2],
                    b["end"][0],   b["end"][2],
                )
                if result:
                    ix, iz, t, s = result
                    # Interior crossing only
                    if 0.05 < t < 0.95 and 0.05 < s < 0.95:
                        elev = a["start"][1]
                        nid = self._get_or_create(ix, elev, iz, "beam_beam")
                        self._attach(nid, a["id"])
                        self._attach(nid, b["id"])

        # ── Build adjacency from shared nodes ──
        adjacency: dict[str, list[str]] = {m["id"]: [] for m in members}
        for n in self._nodes:
            mids = n["members"]
            for i, a in enumerate(mids):
                for b in mids[i + 1:]:
                    if a in adjacency and b not in adjacency[a]:
                        adjacency[a].append(b)
                    if b in adjacency and a not in adjacency[b]:
                        adjacency[b].append(a)

        connectivity = {"adjacency": adjacency, "node_count": len(self._nodes)}
        return self._nodes, members, connectivity


# ── Phase 3 — Geometry Cleanup ─────────────────────────────────────────────────

class GeometryCleanup:
    """
    Cleans up member geometry after node assignment.

    Operations (in order):
      1. Remove zero/tiny length segments
      2. Remove exact duplicates (same type, profile, endpoints within DUP_TOL)
      3. Merge collinear same-type/profile segments with no gap
      4. Snap all member endpoints to their assigned node positions
    """

    def run(self, members: list, nodes: list) -> tuple[list, list[str]]:
        """
        Returns (cleaned_members, log_lines).
        """
        log: list[str] = []
        n0 = len(members)

        members = self._remove_tiny(members, log)
        members = self._remove_duplicates(members, log)
        members = self._merge_collinear(members, log)
        members = self._snap_to_nodes(members, nodes, log)

        log.insert(0, f"Phase 3 GeometryCleanup: {n0} -> {len(members)} members")
        return members, log

    # ── sub-operations ──

    def _remove_tiny(self, members: list, log: list) -> list:
        before = len(members)
        out = [m for m in members if m["length"] >= MIN_LENGTH
               or m["type"] == "column"]
        removed = before - len(out)
        if removed:
            log.append(f"  Removed {removed} fragment(s) shorter than {MIN_LENGTH} ft")
        return out

    def _remove_duplicates(self, members: list, log: list) -> list:
        kept: list[dict] = []
        dupes = 0
        for m in members:
            is_dup = False
            for k in kept:
                if k["type"] != m["type"]:
                    continue
                # Check both orientations
                fwd = (_d3(k["start"], m["start"]) < DUP_TOL and
                       _d3(k["end"],   m["end"])   < DUP_TOL)
                rev = (_d3(k["start"], m["end"])   < DUP_TOL and
                       _d3(k["end"],   m["start"]) < DUP_TOL)
                if fwd or rev:
                    is_dup = True
                    dupes += 1
                    break
            if not is_dup:
                kept.append(m)
        if dupes:
            log.append(f"  Removed {dupes} duplicate member(s)")
        return kept

    def _merge_collinear(self, members: list, log: list) -> list:
        """
        Merge collinear segments of the same type and profile.
        Only merges if the gap between segment ends is ≤ COLLINEAR_GAP.
        """
        merged_count = 0
        by_group: dict[str, list[dict]] = {}
        for m in members:
            key = f"{m['type']}|{m.get('profile') or ''}"
            by_group.setdefault(key, []).append(m)

        result: list[dict] = []
        used: set[str] = set()

        for group in by_group.values():
            for i, base in enumerate(group):
                if base["id"] in used:
                    continue
                chain = [base]
                used.add(base["id"])
                # Greedily extend chain with collinear neighbours
                changed = True
                while changed:
                    changed = False
                    for other in group:
                        if other["id"] in used:
                            continue
                        if not _are_collinear(chain[-1], other):
                            continue
                        # Check gap between the end of chain[-1] and start of other
                        gap = min(
                            _d3(chain[-1]["end"], other["start"]),
                            _d3(chain[-1]["end"], other["end"]),
                        )
                        if gap <= COLLINEAR_GAP:
                            chain.append(other)
                            used.add(other["id"])
                            merged_count += 1
                            changed = True
                if len(chain) == 1:
                    result.append(base)
                else:
                    # Merge chain into one member spanning all endpoints
                    all_pts = [p for m in chain for p in (m["start"], m["end"])]
                    # Project onto axis of first segment and pick extremes
                    dx = chain[0]["end"][0] - chain[0]["start"][0]
                    dz = chain[0]["end"][2] - chain[0]["start"][2]
                    length_axis = math.sqrt(dx * dx + dz * dz)
                    if length_axis < 1e-6:
                        result.append(base)
                        continue
                    ux, uz = dx / length_axis, dz / length_axis
                    ox, oz = chain[0]["start"][0], chain[0]["start"][2]
                    ts = [(pt[0] - ox) * ux + (pt[2] - oz) * uz for pt in all_pts]
                    t_min, t_max = min(ts), max(ts)
                    new_start = [
                        round(ox + t_min * ux, 3),
                        round(chain[0]["start"][1], 3),
                        round(oz + t_min * uz, 3),
                    ]
                    new_end = [
                        round(ox + t_max * ux, 3),
                        round(chain[0]["start"][1], 3),
                        round(oz + t_max * uz, 3),
                    ]
                    merged = copy.deepcopy(base)
                    merged["start"]      = new_start
                    merged["end"]        = new_end
                    merged["length"]     = round(_d3(new_start, new_end), 2)
                    merged["start_node"] = None   # re-assigned after rebuild
                    merged["end_node"]   = None
                    result.append(merged)

        if merged_count:
            log.append(f"  Merged {merged_count} collinear segment(s)")
        return result

    def _snap_to_nodes(self, members: list, nodes: list, log: list) -> list:
        """Move member endpoints to their assigned node positions.

        Ensures that horizontal and vertical beams are only snapped along their
        longitudinal axis, preventing perpendicular node offsets from bending them.
        """
        node_map = {n["id"]: n for n in nodes}
        snapped = 0
        for m in members:
            if m["type"] == "column":
                for end_key, node_key in (("start", "start_node"), ("end", "end_node")):
                    nid = m.get(node_key)
                    if nid and nid in node_map:
                        n = node_map[nid]
                        m[end_key] = [n["x"], n["y"], n["z"]]
                continue

            # Determine if the member was originally horizontal or vertical in X-Z plane
            dx = m["end"][0] - m["start"][0]
            dz = m["end"][2] - m["start"][2]
            is_h = abs(dz) < 0.1 and abs(dx) > 0.5
            is_v = abs(dx) < 0.1 and abs(dz) > 0.5

            orig_x = [m["start"][0], m["end"][0]]
            orig_z = [m["start"][2], m["end"][2]]

            for i, (end_key, node_key) in enumerate((("start", "start_node"), ("end", "end_node"))):
                nid = m.get(node_key)
                if not nid or nid not in node_map:
                    continue
                n = node_map[nid]
                new_x = n["x"]
                new_y = n["y"]
                new_z = n["z"]

                # Enforce orthogonality: prevent perpendicular axis snapping
                if is_h:
                    new_z = orig_z[i]
                elif is_v:
                    new_x = orig_x[i]

                if _d3(m[end_key], [new_x, new_y, new_z]) > 0.01:
                    m[end_key] = [new_x, new_y, new_z]
                    snapped += 1
        if snapped:
            log.append(f"  Snapped {snapped} endpoint(s) to node positions")
        return members


# ── Phase 4 — Structural Placement ────────────────────────────────────────────

class StructuralPlacement:
    """
    Trims beam endpoints to column faces.
    A beam endpoint that lands within TRIM_COL_HALF_W of a column centre
    is pulled exactly to the column face (column_centre ± TRIM_COL_HALF_W).
    This prevents beams from extending through columns in the 3D view.
    """

    def run(self, members: list, log: list) -> list:
        columns = [m for m in members if m["type"] == "column"]
        col_pts = [(c["start"][0], c["start"][2]) for c in columns]
        trimmed = 0

        for m in members:
            if m["type"] in ("column",):
                continue
            for end_key in ("start", "end"):
                pt = m[end_key]
                px, pz = pt[0], pt[2]
                for cx, cz in col_pts:
                    dist = _d2(px, pz, cx, cz)
                    if 0.0 < dist <= TRIM_COL_HALF_W * 3:
                        # Direction from beam endpoint toward column centre
                        if dist < 1e-6:
                            break
                        dx, dz = (cx - px) / dist, (cz - pz) / dist
                        # Trim: place endpoint at column face
                        new_x = round(cx - dx * TRIM_COL_HALF_W, 3)
                        new_z = round(cz - dz * TRIM_COL_HALF_W, 3)
                        m[end_key] = [new_x, pt[1], new_z]
                        trimmed += 1
                        break

        log.append(f"Phase 4 Placement: trimmed {trimmed} beam endpoint(s) to column faces")
        return members


# ── Phase 5 — Structural Hierarchy ────────────────────────────────────────────

class HierarchyDetector:
    """
    Classifies each member into a structural role:

      column   — vertical support
      girder   — primary span, both ends at column nodes
      beam     — secondary span, one end at column/girder node
      secondary— tertiary span between beams
      joist    — short, densely-packed parallel members
      brace    — diagonal bracing
    """

    def run(self, members: list, nodes: list) -> tuple[list, dict]:
        """
        Returns (members_with_role, hierarchy_summary_dict).
        """
        # Build lookup: node_id -> types of members it connects
        node_member_types: dict[str, set[str]] = {}
        for m in members:
            for nk in ("start_node", "end_node"):
                nid = m.get(nk)
                if nid:
                    node_member_types.setdefault(nid, set()).add(m["type"])

        col_top_nodes = {
            n["id"] for n in nodes if n["type"] == "column_top"
        }

        # First pass — columns and braces are trivial
        for m in members:
            if m["type"] == "column":
                m["role"] = "column"
            elif m["type"] == "brace":
                m["role"] = "brace"
            else:
                m["role"] = None   # assigned below

        # Second pass — girder / beam / secondary
        for m in members:
            if m["role"] is not None:
                continue
            sn = m.get("start_node") or ""
            en = m.get("end_node") or ""
            s_col = sn in col_top_nodes
            e_col = en in col_top_nodes
            span = m["length"]

            if s_col and e_col and span >= GIRDER_MIN_SPAN:
                m["role"] = "girder"
            elif (s_col or e_col) and span >= GIRDER_MIN_SPAN * 0.5:
                m["role"] = "beam"
            else:
                m["role"] = "secondary"

        # Third pass — promote dense short members to joist
        # Joists: short span, same orientation, ≥ JOIST_DENSITY near-parallel neighbours
        self._detect_joists(members)

        # Summary
        summary: dict[str, list[str]] = {
            "girder": [], "beam": [], "secondary": [],
            "joist": [], "column": [], "brace": [],
        }
        for m in members:
            role = m.get("role", "secondary")
            summary.setdefault(role, []).append(m["id"])

        return members, summary

    def _detect_joists(self, members: list):
        candidates = [m for m in members
                      if m.get("role") == "secondary" and m["length"] <= JOIST_MAX_SPAN]
        for m in candidates:
            ang = _angle_deg(m["start"][0], m["start"][2], m["end"][0], m["end"][2])
            parallel_count = 0
            for other in candidates:
                if other["id"] == m["id"]:
                    continue
                oang = _angle_deg(other["start"][0], other["start"][2],
                                  other["end"][0], other["end"][2])
                if abs(ang - oang) < COLLINEAR_ANG:
                    # Near-parallel, close together
                    mid_dist = _d3(
                        [(m["start"][0]+m["end"][0])/2, m["start"][1], (m["start"][2]+m["end"][2])/2],
                        [(other["start"][0]+other["end"][0])/2, other["start"][1], (other["start"][2]+other["end"][2])/2],
                    )
                    if mid_dist <= JOIST_MAX_SPAN * 0.5:
                        parallel_count += 1
            if parallel_count >= JOIST_DENSITY:
                m["role"] = "joist"


# ── Phase 6 — Elevation Engine ─────────────────────────────────────────────────

class ElevationEngine:
    """
    Ensures all members are at correct Y elevations.

    Rules:
      - Columns:  start.y = base_elevation_ft,  end.y = floor_elevation_ft
      - Beams / joists / girders:  all Y = floor_elevation_ft
      - Braces:   Y interpolated between base and floor
    """

    def run(self, members: list, floor_elev: float, base_elev: float,
            log: list) -> list:
        adjusted = 0
        for m in members:
            if m["type"] == "column":
                if abs(m["start"][1] - base_elev) > 0.1 or abs(m["end"][1] - floor_elev) > 0.1:
                    m["start"][1] = round(base_elev, 3)
                    m["end"][1]   = round(floor_elev, 3)
                    adjusted += 1
            elif m["type"] == "brace":
                # Braces connect at base elevation one end, floor the other
                # Keep as-is unless clearly wrong
                pass
            else:
                for end_key in ("start", "end"):
                    if abs(m[end_key][1] - floor_elev) > 0.1:
                        m[end_key][1] = round(floor_elev, 3)
                        adjusted += 1
            # Recompute length after elevation fix
            m["length"] = round(_d3(m["start"], m["end"]), 2)

        log.append(f"Phase 6 Elevation: corrected Y on {adjusted} member endpoint(s), "
                   f"floor={floor_elev}ft base={base_elev}ft")
        return members


# ── Phase 7 — Structural Validation ───────────────────────────────────────────

class StructuralValidator:
    """
    Comprehensive per-member validation report.

    Checks:
      ZERO_LENGTH   — start == end
      SHORT_MEMBER  — length < MIN_LENGTH
      NO_START_NODE — start endpoint not connected to any node
      NO_END_NODE   — end endpoint not connected to any node
      FLOATING      — neither endpoint connected
      DUPLICATE_ID  — duplicate member IDs
      NO_PROFILE    — missing steel section
      ORPHAN_COLUMN — column not in any beam's node list
    """

    def run(self, members: list, nodes: list) -> dict:
        errors:   list[dict] = []
        warnings: list[dict] = []
        member_report: list[dict] = []

        seen_ids: set[str] = set()
        node_member_map: dict[str, set[str]] = {}
        for n in nodes:
            for mid in n["members"]:
                node_member_map.setdefault(mid, set()).add(n["id"])

        for m in members:
            issues: list[str] = []

            if m["id"] in seen_ids:
                errors.append({"code": "DUPLICATE_ID", "member": m["id"]})
            seen_ids.add(m["id"])

            if m["start"] == m["end"]:
                errors.append({"code": "ZERO_LENGTH", "member": m["id"]})
                issues.append("zero-length")
            elif m["length"] < MIN_LENGTH and m["type"] != "column":
                warnings.append({"code": "SHORT_MEMBER", "member": m["id"],
                                  "length": m["length"]})
                issues.append(f"short({m['length']}ft)")

            sn_ok = bool(m.get("start_node"))
            en_ok = bool(m.get("end_node"))
            if not sn_ok:
                warnings.append({"code": "NO_START_NODE", "member": m["id"]})
                issues.append("no-start-node")
            if not en_ok:
                warnings.append({"code": "NO_END_NODE", "member": m["id"]})
                issues.append("no-end-node")
            if not sn_ok and not en_ok and m["type"] != "column":
                errors.append({"code": "FLOATING", "member": m["id"]})
                issues.append("FLOATING")

            if not m.get("profile"):
                warnings.append({"code": "NO_PROFILE", "member": m["id"]})
                issues.append("no-profile")

            status = "ERROR" if any(e["member"] == m["id"] for e in errors) \
                else "WARN" if issues else "OK"
            member_report.append({
                "id":       m["id"],
                "type":     m["type"],
                "role":     m.get("role", "—"),
                "profile":  m.get("profile") or "—",
                "length":   m["length"],
                "start_node": m.get("start_node") or "—",
                "end_node":   m.get("end_node") or "—",
                "status":   status,
                "issues":   issues,
            })

        # Orphan columns — column top not in any beam's node list
        col_tops = {n["id"] for n in nodes if n["type"] == "column_top"}
        beam_nodes = set()
        for m in members:
            if m["type"] != "column":
                for nk in ("start_node", "end_node"):
                    nid = m.get(nk)
                    if nid:
                        beam_nodes.add(nid)
        orphan_cols = col_tops - beam_nodes
        for nid in orphan_cols:
            n = next((x for x in nodes if x["id"] == nid), None)
            col_id = n["members"][0] if n and n["members"] else "?"
            warnings.append({"code": "ORPHAN_COLUMN", "node": nid,
                              "column_member": col_id,
                              "msg": "Column top has no connected beams"})

        type_counts: dict[str, int] = {}
        for m in members:
            type_counts[m["type"]] = type_counts.get(m["type"], 0) + 1

        role_counts: dict[str, int] = {}
        for m in members:
            r = m.get("role") or "unclassified"
            role_counts[r] = role_counts.get(r, 0) + 1

        floating = sum(1 for e in errors if e.get("code") == "FLOATING")
        passes = len(errors) == 0

        return {
            "pass":           passes,
            "errors":         errors,
            "warnings":       warnings,
            "member_report":  member_report,
            "stats": {
                "total_members": len(members),
                "total_nodes":   len(nodes),
                "by_type":       type_counts,
                "by_role":       role_counts,
                "floating":      floating,
                "orphan_columns": len(orphan_cols),
                "no_profile":    sum(1 for m in members if not m.get("profile")),
            },
        }


# ── Public API ─────────────────────────────────────────────────────────────────

@dataclass
class ReconstructionResult:
    members:      list[dict]
    nodes:        list[dict]
    connectivity: dict
    hierarchy:    dict
    report:       dict
    log:          list[str] = field(default_factory=list)


def run_reconstruction(
    members:           list,
    floor_elevation_ft: float = 14.0,
    base_elevation_ft:  float = 0.0,
) -> ReconstructionResult:
    """
    Run the full structural reconstruction pipeline (Phases 2–7).

    Args:
        members:            List of member dicts from structural_schema._convert_member
        floor_elevation_ft: Y elevation for beams/joists/girders
        base_elevation_ft:  Y elevation for column bases

    Returns:
        ReconstructionResult with fully processed model data
    """
    log: list[str] = []

    # ── Phase 2: Node Graph ──────────────────────────────────────────────────
    log.append(f"Phase 2 NodeGraph: processing {len(members)} members "
               f"(snap_tol={SNAP_TOL}ft, beam_col_tol={BEAM_COL_TOL}ft)")
    graph = NodeGraph(snap_tol=SNAP_TOL)
    nodes, members, connectivity = graph.build(members)

    n_col_top    = sum(1 for n in nodes if n["type"] == "column_top")
    n_bm_col     = sum(1 for n in nodes if n["type"] == "beam_column")
    n_bm_bm      = sum(1 for n in nodes if n["type"] == "beam_beam")
    n_endpoint   = sum(1 for n in nodes if n["type"] == "endpoint")
    log.append(f"  Nodes: {len(nodes)} total — "
               f"col_top={n_col_top}  beam×col={n_bm_col}  "
               f"beam×beam={n_bm_bm}  endpoint={n_endpoint}")
    floating_2 = sum(1 for m in members
                     if not m.get("start_node") and not m.get("end_node")
                     and m["type"] != "column")
    log.append(f"  Floating members (no node): {floating_2}")

    # ── Phase 3: Geometry Cleanup ────────────────────────────────────────────
    cleaner = GeometryCleanup()
    members, clean_log = cleaner.run(members, nodes)
    log.extend(clean_log)

    # Rebuild node graph after cleanup (merging may have invalidated nodes)
    if any("Merged" in l or "Removed" in l for l in clean_log):
        log.append("  Rebuilding node graph after geometry changes …")
        graph2 = NodeGraph(snap_tol=SNAP_TOL)
        nodes, members, connectivity = graph2.build(members)
        log.append(f"  Post-cleanup nodes: {len(nodes)}")

    # ── Phase 4: Structural Placement ────────────────────────────────────────
    placer = StructuralPlacement()
    members = placer.run(members, log)

    # ── Phase 5: Hierarchy Detection ─────────────────────────────────────────
    detector = HierarchyDetector()
    members, hierarchy = detector.run(members, nodes)
    log.append("Phase 5 Hierarchy: " +
               "  ".join(f"{k}={len(v)}" for k, v in hierarchy.items() if v))

    # ── Phase 6: Elevation Engine ─────────────────────────────────────────────
    elev = ElevationEngine()
    members = elev.run(members, floor_elevation_ft, base_elevation_ft, log)

    # ── Phase 7: Validation ───────────────────────────────────────────────────
    validator = StructuralValidator()
    report = validator.run(members, nodes)
    status = "PASS" if report["pass"] else f"FAIL ({len(report['errors'])} errors)"
    log.append(f"Phase 7 Validation: {status}  "
               f"warnings={len(report['warnings'])}  "
               f"floating={report['stats']['floating']}")

    return ReconstructionResult(
        members=members,
        nodes=nodes,
        connectivity=connectivity,
        hierarchy=hierarchy,
        report=report,
        log=log,
    )
