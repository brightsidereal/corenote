from fastapi import Header
from psycopg2.extras import RealDictCursor
from app.database import get_conn
from app.errors import UnauthorizedError

def get_current_user(x_api_key: str = Header(...)) -> dict:
    with get_conn() as con:
        cur = con.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name, email FROM users WHERE api_key = %s", (x_api_key,))
        user = cur.fetchone()
        cur.close()

    if not user:
        raise UnauthorizedError()
    return dict(user)