"""
Supabase Connection & Schema Test
=================================
Tests live connection to the user's Supabase instance (rgzwokozwprvmavewxbl).
"""

import os
from dotenv import load_dotenv

load_dotenv()

def test_conn():
    print("Testing Supabase connection...")
    supa_url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    print(f"Supabase URL: {supa_url}")
    print(f"Anon Key Present: {bool(anon_key)}")
    print(f"Service Key Present: {bool(service_key)}")

    try:
        from supabase import create_client
        client = create_client(supa_url, service_key or anon_key)
        print("Connected to Supabase client successfully!")

        # Check existing tables
        try:
            res = client.table("projects").select("id").limit(1).execute()
            print("Successfully queried 'projects' table! Data:", res.data)
        except Exception as e:
            print("Notice: 'projects' table check:", e)

    except Exception as e:
        print("Supabase Python SDK connection error:", e)

if __name__ == "__main__":
    test_conn()
