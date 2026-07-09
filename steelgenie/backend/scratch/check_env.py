import os
from dotenv import load_dotenv

load_dotenv()
print("SUPABASE_URL:", os.getenv("SUPABASE_URL"))
print("SUPABASE_ANON_KEY:", os.getenv("SUPABASE_ANON_KEY"))
print("SUPABASE_SERVICE_ROLE_KEY:", os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

try:
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        client = create_client(url, key)
        print("Successfully created Supabase client!")
        # Try listing users or testing connection
        users = client.auth.admin.list_users()
        print("Users count:", len(users.users) if users else "None")
        for u in users.users[:5]:
            print(f"- {u.email} (id: {u.id})")
    else:
        print("URL or Service Role Key missing!")
except Exception as e:
    print("Error:", e)
