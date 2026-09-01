"""
Full Project, Drawing, and Member Sync to Supabase
===================================================
Syncs all drawings, scale ratios, beam/column members, and physical lengths
from saved_projects.json to Supabase.
"""

import os
import json
import uuid
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

def sync_full():
    supa_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    client = create_client(supa_url, service_key)

    json_path = "saved_projects.json"
    if not os.path.exists(json_path):
        print("No saved_projects.json found.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        projects = json.load(f)

    # Get owner_id
    u_res = client.table("users").select("id").limit(1).execute()
    user_id = u_res.data[0]["id"] if u_res.data else None
    print(f"Syncing with user_id: {user_id}")

    for p in projects:
        pid = p.get("id")
        pname = p.get("name") or "Untitled Project"
        fname = p.get("filename") or "Drawing.pdf"
        scale_ratio = p.get("scale_ratio") or 96
        scale_label = p.get("scale") or "1/8\" = 1'-0\""
        raw_members = p.get("members") or []

        print(f"\n==========================================")
        print(f"Project: {pname} (ID: {pid})")
        print(f"  Filename: {fname}")
        print(f"  Scale: {scale_label} (Ratio: {scale_ratio})")
        print(f"  Members count: {len(raw_members)}")
        print(f"==========================================")

        # 1. Upsert Project
        client.table("projects").upsert({
            "id": pid,
            "name": pname,
            "owner_id": user_id,
            "status": "in_progress",
            "design_standard": "AISC",
            "unit_system": "imperial"
        }, on_conflict="id").execute()

        # 2. Upsert Drawing
        # Check if drawing exists for this project
        d_res = client.table("drawings").select("id").eq("project_id", pid).execute()
        if d_res.data:
            drawing_id = d_res.data[0]["id"]
        else:
            drawing_id = str(uuid.uuid4())
            client.table("drawings").insert({
                "id": drawing_id,
                "project_id": pid,
                "filename": fname,
                "storage_key": f"drawings/{pid}/{fname}",
                "page_count": 1,
                "status": "ready"
            }).execute()

        # 3. Upsert Page
        p_res = client.table("pages").select("id").eq("drawing_id", drawing_id).execute()
        if p_res.data:
            page_id = p_res.data[0]["id"]
            client.table("pages").update({
                "scale_num": float(scale_ratio),
                "scale_label": scale_label,
                "status": "built"
            }).eq("id", page_id).execute()
        else:
            page_id = str(uuid.uuid4())
            client.table("pages").insert({
                "id": page_id,
                "drawing_id": drawing_id,
                "idx": 0,
                "title": "Sheet 1",
                "scale_num": float(scale_ratio),
                "scale_label": scale_label,
                "status": "built"
            }).execute()

        # 4. Upsert Members
        if raw_members:
            # Delete old members for this page first to avoid duplicates
            client.table("members").delete().eq("page_id", page_id).execute()

            member_rows = []
            for m in raw_members:
                prof = m.get("profile") or "UNKNOWN"
                kind = "column" if m.get("is_column") or m.get("type") == "column" else "beam"
                length_ft = m.get("length_ft") or 0.0

                member_rows.append({
                    "id": str(uuid.uuid4()),
                    "page_id": page_id,
                    "kind": kind,
                    "section": prof,
                    "grade": "A992" if kind == "beam" else "A500",
                    "status": "verified" if m.get("confirmed") else "active",
                    "source": "ai",
                    "length_ft": round(float(length_ft), 2) if length_ft else None,
                    "geometry": {
                        "bx1": m.get("bx1"), "by1": m.get("by1"),
                        "bx2": m.get("bx2"), "by2": m.get("by2"),
                        "x": m.get("x"), "y": m.get("y"),
                        "lx": m.get("lx"), "ly": m.get("ly"),
                        "w": m.get("w"), "h": m.get("h"),
                        "color": m.get("color")
                    },
                    "confidence": 0.95
                })

            # Batch insert members
            batch_size = 50
            for i in range(0, len(member_rows), batch_size):
                batch = member_rows[i:i + batch_size]
                client.table("members").insert(batch).execute()
                print(f"  -> Uploaded batch {i // batch_size + 1} ({len(batch)} members with physical lengths & AISC sections)")

    print("\n[SUCCESS] All projects, drawings, and member lengths synced to Supabase!")

if __name__ == "__main__":
    sync_full()
