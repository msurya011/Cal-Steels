"""
Seed AISC Shapes into Supabase
==============================
Uploads the complete AISC 15 & 16 Shape Database into Supabase 'aisc_shapes' table.
"""

import os
import json
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

def seed_supabase_aisc():
    supa_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    client = create_client(supa_url, service_key)

    json_path = os.path.join("data", "aisc_v16_shapes.json")
    if not os.path.exists(json_path):
        print(f"File not found: {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        db = json.load(f)

    print(f"Loaded {len(db)} shapes from JSON. Preparing to seed Supabase...")

    # Check if aisc_shapes table exists in Supabase
    try:
        rows = []
        for des, info in db.items():
            rows.append({
                "designation": des,
                "shape_type": info.get("type", "W"),
                "weight_lb_ft": info.get("weight_lb_ft", 0.0),
                "depth_in": info.get("depth_in"),
                "flange_w_in": info.get("flange_w_in"),
                "web_t_in": info.get("web_t_in"),
                "flange_t_in": info.get("flange_t_in"),
                "area_sq_in": info.get("area_sq_in")
            })

        # Upsert in batches of 50
        batch_size = 50
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            client.table("aisc_shapes").upsert(batch, on_conflict="designation").execute()
            print(f"  -> Upserted batch {i // batch_size + 1} ({len(batch)} shapes)")

        print("AISC Shape Database successfully seeded to Supabase!")

    except Exception as e:
        print("Note on Supabase aisc_shapes table:", e)
        print("You can create the 'aisc_shapes' table in Supabase SQL editor using:")
        print("""
CREATE TABLE IF NOT EXISTS aisc_shapes (
  designation   TEXT PRIMARY KEY,
  shape_type    TEXT NOT NULL,
  weight_lb_ft  NUMERIC(8,2) NOT NULL,
  depth_in      NUMERIC(8,2),
  flange_w_in   NUMERIC(8,2),
  area_sq_in    NUMERIC(8,2),
  created_at    TIMESTAMPTZ DEFAULT now()
);
        """)

if __name__ == "__main__":
    seed_supabase_aisc()
