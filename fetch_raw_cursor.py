
import sqlite3
import json
import base64
import requests
from pathlib import Path

def fetch_cursor_raw():
    db_path = Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    if not db_path.exists():
        print(f"DB not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken'")
    row = cursor.fetchone()
    conn.close()

    if not row:
        print("Token not found")
        return
    
    access_token = row[0]
    
    # JWT parsing
    jwt_payload = access_token.split(".")[1]
    jwt_payload += "=" * (4 - len(jwt_payload) % 4)
    decoded = json.loads(base64.b64decode(jwt_payload))
    sub = decoded.get("sub", "")
    user_id = sub.split("|")[-1] if "|" in sub else sub
    cookie = f"WorkosCursorSessionToken={user_id}%3A%3A{access_token}"

    url = "https://cursor.com/api/usage-summary"
    resp = requests.get(
        url,
        headers={
            "Accept": "application/json",
            "Cookie": cookie,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        },
        timeout=30,
    )
    
    print(json.dumps(resp.json(), indent=2))

if __name__ == "__main__":
    fetch_cursor_raw()
