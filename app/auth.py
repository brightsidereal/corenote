from fastapi import Header
from psycopg.rows import dict_row
from app.database import get_conn
from app.errors import UnauthorizedError

def get_current_user(x_api_key: str = Header(...)) -> dict:
    with get_conn() as con:
        row = con.execute(
            "SELECT id, name, email FROM users WHERE api_key = %s",
            (x_api_key,)
        ).fetchone()

    if not row:
        raise UnauthorizedError()
    return dict(zip(["id", "name", "email"], row))