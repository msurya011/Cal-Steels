import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import requests

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 1. Load .env file from the current backend directory
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("[ERROR] GEMINI_API_KEY not found in .env file.")
    print(f"Looked in: {env_path}")
    sys.exit(1)

print(f"[OK] Found GEMINI_API_KEY: {api_key[:6]}...{api_key[-4:]}")
print("[INFO] Checking API key with Gemini...")

# Target Gemini model
model_name = "gemini-3.6-flash"


try:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{"text": "Hello Gemini! Please reply with a short 1-sentence confirmation that this API key is working."}]
        }]
    }
    res = requests.post(url, headers=headers, json=payload, timeout=15)
    
    if res.status_code == 200:
        data = res.json()
        reply = data["candidates"][0]["content"]["parts"][0]["text"]
        print(f"\n[SUCCESS] API Key is WORKING! Model ({model_name}) responded:")
        print(f"-> {reply.strip()}\n")
    else:
        print(f"[ERROR] API Error [{res.status_code}]: {res.text}")

except Exception as err:
    print(f"[ERROR] Request failed: {err}")


