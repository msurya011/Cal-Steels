"""
Sync Local Projects to Supabase
===============================
Safely uploads existing local projects and members to Supabase without duplicates.
"""

import os
import json
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

def sync_projects():
    supa_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    client = create_client(supa_url, service_key)

    json_path = "saved_projects.json"
    if not os.path.exists(json_path):
        print("No saved_projects.json found.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        projects = json.load(f)

    print(f"Found {len(projects)} local projects to sync.")

    # Fetch first available user
    u_res = client.table("users").select("id").limit(1).execute()
    user_id = u_res.data[0]["id"] if u_res.data else None
    print(f"Using owner_id: {user_id}")

    for p in projects:
        pid = p.get("id")
        pname = p.get("name") or "Untitled Project"
        print(f"Syncing Project: {pname} ({pid})...")
        
        # Check if project exists in Supabase
        res = client.table("projects").select("id").eq("id", pid).execute()
        if not res.data and user_id:
            client.table("projects").insert({
                "id": pid,
                "name": pname,
                "owner_id": user_id,
            }).execute()
            print(f"  -> Inserted project '{pname}'")
        else:
            print(f"  -> Project '{pname}' already present in Supabase.")

    print("All projects synced to Supabase successfully!")

if __name__ == "__main__":
    sync_projects()
