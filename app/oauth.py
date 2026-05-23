import uuid, secrets
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
import httpx

from app.config import settings
from app.database import get_conn

router = APIRouter()

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
REDIRECT_URI = f"{settings.base_url}/auth/callback"

@router.get("/auth/login")
def login():
    params = {
        "client_id":     settings.google_client_id,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "offline",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{query}")

@router.get("/auth/callback")
async def callback(code: str):
    async with httpx.AsyncClient() as client:
        token_res = await client.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        })
        token_data = token_res.json()

        userinfo_res = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {token_data['access_token']}"}
        )
        userinfo = userinfo_res.json()

    email = userinfo["email"]
    name  = userinfo.get("name", email)

    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT id, api_key FROM users WHERE email = %s", (email,))
        existing = cur.fetchone()

        if existing:
            user_id, api_key = existing
        else:
            user_id = str(uuid.uuid4())
            api_key = secrets.token_urlsafe(32)
            cur.execute("""
                INSERT INTO users (id, api_key, name, email)
                VALUES (%s, %s, %s, %s)
            """, (user_id, api_key, name, email))
            con.commit()
        cur.close()

    return {"message": "login สำเร็จ", "name": name, "email": email, "api_key": api_key}

@router.get("/auth/me")
def me(api_key: str):
    from psycopg2.extras import RealDictCursor
    from app.errors import NotFoundError
    with get_conn() as con:
        cur = con.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name, email, created_at FROM users WHERE api_key = %s", (api_key,))
        user = cur.fetchone()
        cur.close()
    if not user:
        raise NotFoundError("user")
    return dict(user)