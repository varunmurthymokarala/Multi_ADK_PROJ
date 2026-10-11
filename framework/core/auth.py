"""Auth: local email/password users + Google ID-token login. SQLite + JWT."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import sqlite3
import time
from email.mime.text import MIMEText
from dataclasses import dataclass

import httpx
import jwt

from .config import DB_PATH, JWT_ALG, JWT_SECRET

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_VERIFY_URL = "https://oauth2.googleapis.com/tokeninfo"

# Gmail SMTP for password-reset emails (Gmail app password, not the login password).
# Both unset = local dev mode: the reset code is returned to the UI instead.
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()
RESET_TTL_SECONDS = 15 * 60


@dataclass
class User:
    id: str
    name: str
    email: str
    picture: str = ""
    provider: str = "local"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, "
        "password_hash TEXT DEFAULT '', picture TEXT DEFAULT '', "
        "provider TEXT DEFAULT 'local', created_at REAL NOT NULL)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS password_resets ("
        "id TEXT PRIMARY KEY, email TEXT NOT NULL, code_hash TEXT NOT NULL, "
        "expires_at REAL NOT NULL, used INTEGER DEFAULT 0)"
    )
    return c


def _hash(password: str, salt: str = "") -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def _check(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
        return hmac.compare_digest(_hash(password, salt), stored)
    except Exception:
        return False


def _row_to_user(row) -> User:
    return User(id=row["id"], name=row["name"], email=row["email"],
                picture=row["picture"] or "", provider=row["provider"] or "local")


def get_user_by_email(email: str) -> User | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
        return _row_to_user(row) if row else None


def get_user_by_id(user_id: str) -> User | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None


def create_local_user(name: str, email: str, password: str) -> User:
    email = email.strip().lower()
    if get_user_by_email(email):
        raise ValueError("An account with this email already exists. Please log in.")
    user = User(id=secrets.token_hex(12), name=name.strip() or email.split("@")[0],
                email=email, provider="local")
    with _conn() as c:
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                  (user.id, user.name, user.email, _hash(password), "", "local", time.time()))
    return user


def verify_local_user(email: str, password: str) -> User:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if not row or not row["password_hash"] or not _check(password, row["password_hash"]):
        raise ValueError("Invalid email or password.")
    return _row_to_user(row)


def upsert_google_user(info: dict) -> User:
    email = (info.get("email") or "").lower()
    if not email:
        raise ValueError("Google account has no email.")
    existing = get_user_by_email(email)
    name = info.get("name") or email.split("@")[0]
    picture = info.get("picture") or ""
    if existing:
        with _conn() as c:
            c.execute("UPDATE users SET name=?, picture=? WHERE id=?", (name, picture, existing.id))
        existing.name, existing.picture = name, picture
        return existing
    user = User(id=secrets.token_hex(12), name=name, email=email, picture=picture, provider="google")
    with _conn() as c:
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                  (user.id, user.name, user.email, "", picture, "google", time.time()))
    return user


async def verify_google_id_token(id_token: str) -> dict:
    """Verify via Google's tokeninfo endpoint (no extra deps)."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(GOOGLE_VERIFY_URL, params={"id_token": id_token})
        if r.status_code != 200:
            raise ValueError("Google sign-in failed. Please try again.")
        info = r.json()
    if GOOGLE_CLIENT_ID and info.get("aud") != GOOGLE_CLIENT_ID:
        raise ValueError("Google token was issued for a different app.")
    if info.get("email") is None:
        raise ValueError("Google account has no email.")
    return info


def make_token(user: User) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user.id, "email": user.email, "name": user.name,
                       "picture": user.picture, "iat": now, "exp": now + 60 * 60 * 24 * 7},
                      JWT_SECRET, algorithm=JWT_ALG)


def user_from_token(token: str) -> User | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return get_user_by_id(payload.get("sub") or "")
    except Exception:
        return None


def public_user(user: User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email,
            "picture": user.picture, "provider": user.provider}


def auth_config() -> dict:
    return {"google_client_id": GOOGLE_CLIENT_ID, "google_enabled": bool(GOOGLE_CLIENT_ID)}


# --- Password reset (existing Gmail accounts only) ---------------------------

def is_gmail(email: str) -> bool:
    return email.strip().lower().endswith(("@gmail.com", "@googlemail.com"))


def _send_reset_email(to_email: str, code: str) -> None:
    msg = MIMEText(
        f"Your password reset code is: {code}\n"
        f"It expires in {RESET_TTL_SECONDS // 60} minutes. If you did not "
        f"request this, you can ignore this email."
    )
    msg["Subject"] = "Reset your password"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)


def create_reset_code(email: str) -> str | None:
    """Issue a 6-digit code for an EXISTING Gmail account.

    Returns the plaintext code only in local dev mode (SMTP not configured);
    returns None when the code was emailed successfully.
    """
    email = email.strip().lower()
    if not is_gmail(email):
        raise ValueError("Password reset is only available for original Gmail accounts (@gmail.com).")
    if not get_user_by_email(email):
        raise ValueError("No account exists for this Gmail address. Please register first.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    with _conn() as c:
        c.execute("DELETE FROM password_resets WHERE email=? OR expires_at < ?",
                  (email, time.time()))
        c.execute("INSERT INTO password_resets VALUES (?,?,?,?,?)",
                  (secrets.token_hex(12), email, _hash(code),
                   time.time() + RESET_TTL_SECONDS, 0))
    if GMAIL_ADDRESS and GMAIL_APP_PASSWORD:
        _send_reset_email(email, code)
        return None
    return code


def reset_password(email: str, code: str, new_password: str) -> None:
    email = email.strip().lower()
    if len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM password_resets WHERE email=? AND used=0 AND expires_at > ? "
            "ORDER BY expires_at DESC LIMIT 1",
            (email, time.time()),
        ).fetchone()
        if not row or not _check(code.strip(), row["code_hash"]):
            raise ValueError("Invalid or expired reset code.")
        user = get_user_by_email(email)
        if not user:
            raise ValueError("Account no longer exists.")
        c.execute("UPDATE users SET password_hash=? WHERE id=?",
                  (_hash(new_password), user.id))
        c.execute("UPDATE password_resets SET used=1 WHERE id=?", (row["id"],))
