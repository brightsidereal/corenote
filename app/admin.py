"""
admin.py — จัดการ users (รัน manually)

สร้าง user ใหม่:
  python admin.py create --name "Supawit"

ดู users ทั้งหมด:
  python admin.py list
"""

import uuid, secrets, sys
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = "postgresql://postgres:postgres@localhost:5433/corenote"

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def create_user(name: str) -> dict:
    con = get_conn()
    cur = con.cursor(cursor_factory=RealDictCursor)
    user = {
        "id": str(uuid.uuid4()),
        "api_key": secrets.token_urlsafe(32),
        "name": name,
    }
    cur.execute("""
        INSERT INTO users (id, api_key, name)
        VALUES (%(id)s, %(api_key)s, %(name)s)
    """, user)
    con.commit()
    cur.close()
    con.close()
    return user

def list_users():
    con = get_conn()
    cur = con.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, name, api_key, created_at FROM users ORDER BY created_at")
    users = cur.fetchall()
    cur.close()
    con.close()
    return [dict(u) for u in users]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python admin.py create --name NAME")
        print("       python admin.py list")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "create":
        name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else "user"
        user = create_user(name)
        print(f"\n✓ user created")
        print(f"  name   : {user['name']}")
        print(f"  id     : {user['id']}")
        print(f"  api_key: {user['api_key']}")
        print(f"\nส่ง api_key นี้ให้ user เพื่อใช้ใน header: x-api-key")

    elif cmd == "list":
        users = list_users()
        print(f"\n{len(users)} users:")
        for u in users:
            print(f"  {u['name']:20} {u['api_key'][:20]}...  ({u['created_at']})")