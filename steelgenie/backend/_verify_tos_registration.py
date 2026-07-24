"""
Standalone execution check for the TOS-based floor clustering + registration
engine (app/engineering/registration.py). Runs against an isolated temp
local_db.json so it never touches real project data.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app.services.database as dbmod

tmp_db = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
tmp_db.close()
dbmod._DB_FILE = tmp_db.name

from app.engineering import registration as reg

db = dbmod.get_db()

PROJECT_ID = "proj-1"
db.table("drawings").insert({"id": "draw-a", "project_id": PROJECT_ID, "filename": "Binder-A.pdf", "storage_key": "x"}).execute()
db.table("drawings").insert({"id": "draw-b", "project_id": PROJECT_ID, "filename": "Binder-B.pdf", "storage_key": "x"}).execute()

db.table("pages").insert({
    "id": "page-a", "drawing_id": "draw-a", "idx": 30, "title": "Partial Level 04 Framing Plan - Zone A",
    "sheet_no": "S134.A", "tos_ft": 12.0, "scale_num": 96, "status": "built",
}).execute()
db.table("pages").insert({
    "id": "page-b", "drawing_id": "draw-b", "idx": 5, "title": "Partial Level 04 Framing Plan - Zone B",
    "sheet_no": "S134.B", "tos_ft": 12.0, "scale_num": 96, "status": "built",
}).execute()
db.table("pages").insert({
    "id": "page-c", "drawing_id": "draw-a", "idx": 31, "title": "Roof Framing Plan",
    "sheet_no": "S135", "tos_ft": 26.0, "scale_num": 96, "status": "built",
}).execute()

for (x, y) in [(0.2, 0.2), (0.2, 0.8), (0.8, 0.2), (0.8, 0.8)]:
    db.table("members").insert({
        "page_id": "page-a", "kind": "column", "section": "W12X26", "status": "active",
        "geometry": {"x": x, "y": y},
    }).execute()

for (x, y) in [(0.1, 0.2), (0.1, 0.8), (0.6, 0.2), (0.6, 0.8)]:
    db.table("members").insert({
        "page_id": "page-b", "kind": "column", "section": "W12X26", "status": "active",
        "geometry": {"x": x, "y": y},
    }).execute()

db.table("members").insert({
    "page_id": "page-c", "kind": "column", "section": "W10X19", "status": "active",
    "geometry": {"x": 0.5, "y": 0.5},
}).execute()

print("=== cluster_pages_into_floors ===")
cluster_result = reg.cluster_pages_into_floors(PROJECT_ID)
print(cluster_result)

floors = db.table("floors").select("*").eq("project_id", PROJECT_ID).execute().data
links = db.table("page_floor_links").select("*").execute().data
print(f"\nfloors created: {len(floors)}")
for f in floors:
    linked_pages = [l["page_id"] for l in links if l["floor_id"] == f["id"]]
    print(f"  floor {f['name']!r} elevation_ft={f['elevation_ft']} pages={linked_pages}")

assert len(floors) == 2, f"expected 2 floors, got {len(floors)}"
floor_12 = next(f for f in floors if f["elevation_ft"] == 12.0)
floor_26 = next(f for f in floors if f["elevation_ft"] == 26.0)
pages_on_12 = {l["page_id"] for l in links if l["floor_id"] == floor_12["id"]}
pages_on_26 = {l["page_id"] for l in links if l["floor_id"] == floor_26["id"]}
assert pages_on_12 == {"page-a", "page-b"}, f"expected page-a + page-b merged on TOS-12 floor, got {pages_on_12}"
assert pages_on_26 == {"page-c"}, f"expected page-c alone on TOS-26 floor, got {pages_on_26}"
print("\nPASS: two different-drawing sheets sharing TOS 12'-0\\\" merged into ONE floor;")
print("      the TOS 26'-0\\\" sheet correctly landed on its own separate floor.")

print("\n=== register_floor (TOS 12 floor, 2 sheets) ===")
reg_result = reg.register_floor(floor_12["id"])
print(reg_result)
assert reg_result["registered"] == 2

regs = {r["page_id"]: r for r in db.table("page_registrations").select("*").execute().data}
print("\npage_registrations:")
for pid, r in regs.items():
    print(f"  {pid}: tx={r['tx_ft']:.2f} ty={r['ty_ft']:.2f} method={r['method']} confidence={r['confidence']}")

anchor_pid = next(pid for pid, r in regs.items() if r["anchor"])
other_pid = "page-b" if anchor_pid == "page-a" else "page-a"
print(f"\nanchor={anchor_pid} other={other_pid}")
assert regs[other_pid]["method"] == "tile", f"expected tile method, got {regs[other_pid]['method']}"
assert regs[other_pid]["confidence"] > 0
assert regs[other_pid]["tx_ft"] > 0, "expected the tiled page offset away from the anchor"

print("\n=== global geometry sanity: zones must NOT overlap ===")
members_a = db.table("members").select("*").eq("page_id", "page-a").execute().data
members_b = db.table("members").select("*").eq("page_id", "page-b").execute().data
gx_a = [m["geometry"]["global"]["gx_ft"] for m in members_a]
gx_b = [m["geometry"]["global"]["gx_ft"] for m in members_b]
range_a = (min(gx_a), max(gx_a))
range_b = (min(gx_b), max(gx_b))
print(f"page-a global gx range {range_a[0]:.2f} .. {range_a[1]:.2f} ft")
print(f"page-b global gx range {range_b[0]:.2f} .. {range_b[1]:.2f} ft")
no_overlap = range_a[1] < range_b[0] or range_b[1] < range_a[0]
assert no_overlap, f"BUG: ranges overlap: {range_a} vs {range_b}"
print("PASS: Zone A and Zone B are laterally tiled with no overlap once merged.")

print("\n=== extract_grids_for_page ===")
grids_a = db.table("grids").select("*").eq("page_id", "page-a").execute().data
print(f"page-a grids: {[(g['axis'], g['label'], round(g['position'],2)) for g in grids_a]}")
assert len(grids_a) == 4

print("\nALL CHECKS PASSED.")
os.unlink(tmp_db.name)
