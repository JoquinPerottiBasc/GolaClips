"""Database layer for GolaClips.

Uses SQLite locally and PostgreSQL in production (when DATABASE_URL is set).
"""

import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")
_POSTGRES = DATABASE_URL.startswith("postgres")

DB_PATH = Path(__file__).parent / "golaclips.db"

# SQL placeholder differs between drivers
PH = "%s" if _POSTGRES else "?"
# Current timestamp expression
NOW = "NOW()" if _POSTGRES else "datetime('now')"

# Credits per plan (in minutes). Credits do NOT accumulate between months.
PLAN_CREDITS = {"free": 30, "pro": 200}

if _POSTGRES:
    import psycopg2
    import psycopg2.extras


@contextmanager
def _conn():
    """Context manager that yields a cursor and auto-commits/rollbacks."""
    if _POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


def _row(cursor):
    r = cursor.fetchone()
    return dict(r) if r else None


def _next_reset_date() -> datetime:
    """Return the first day of next month at 00:00 UTC."""
    now = datetime.utcnow()
    if now.month == 12:
        return datetime(now.year + 1, 1, 1)
    return datetime(now.year, now.month + 1, 1)


def init_db():
    """Create tables if they don't exist, then apply schema migrations."""
    if _POSTGRES:
        id_type = "SERIAL PRIMARY KEY"
        text_type = "TEXT"
    else:
        id_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
        text_type = "TEXT"

    with _conn() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                id {id_type},
                firebase_uid {text_type} UNIQUE NOT NULL,
                email {text_type} NOT NULL,
                name {text_type},
                avatar_url {text_type},
                plan {text_type} DEFAULT 'free',
                credits_remaining INTEGER DEFAULT 30,
                credits_reset_date TIMESTAMP,
                stripe_customer_id {text_type},
                stripe_subscription_id {text_type},
                credits_seconds INTEGER NOT NULL DEFAULT 0,
                monthly_reset_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS transactions (
                id {id_type},
                user_id INTEGER REFERENCES users(id),
                type {text_type} NOT NULL,
                amount_usd REAL,
                credits_seconds INTEGER NOT NULL,
                description {text_type},
                stripe_session_id {text_type},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS jobs (
                id {text_type} PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                original_filename {text_type},
                status {text_type} DEFAULT 'queued',
                error {text_type},
                credits_used INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS clips (
                id {id_type},
                job_id {text_type} REFERENCES jobs(id),
                filename {text_type} NOT NULL,
                r2_key {text_type} NOT NULL,
                start_sec REAL,
                end_sec REAL,
                score INTEGER,
                description {text_type}
            )
        """)

    _apply_migrations()


def _apply_migrations():
    """Add new columns to existing tables. Safe to run multiple times."""
    migrations = [
        "ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'",
        "ALTER TABLE users ADD COLUMN credits_remaining INTEGER DEFAULT 30",
        "ALTER TABLE users ADD COLUMN credits_reset_date TIMESTAMP",
        "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT",
        "ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT",
        "ALTER TABLE jobs ADD COLUMN credits_used INTEGER",
    ]
    with _conn() as cur:
        for sql in migrations:
            try:
                cur.execute(sql)
            except Exception:
                # Column already exists — skip silently
                pass


def _next_reset_date_str() -> str:
    return _next_reset_date().isoformat()


def reset_monthly_credits(user_id: int, plan: str = "free"):
    """Reset credits_remaining to plan maximum and set next reset date.
    Credits do NOT accumulate — always reset to the exact plan total.
    """
    total = PLAN_CREDITS.get(plan, 30)
    next_reset = _next_reset_date()
    with _conn() as cur:
        cur.execute(f"""
            UPDATE users
            SET credits_remaining = {PH}, credits_reset_date = {PH}
            WHERE id = {PH}
        """, (total, next_reset.isoformat(), user_id))


def check_and_reset_if_needed(user_id: int) -> dict:
    """If the monthly reset date has passed, reset credits to plan total.
    Returns the up-to-date user row (plan, credits_remaining, credits_reset_date).
    """
    with _conn() as cur:
        cur.execute(
            f"SELECT plan, credits_remaining, credits_reset_date FROM users WHERE id = {PH}",
            (user_id,)
        )
        row = _row(cur)

    if not row:
        return {}

    plan = row.get("plan") or "free"
    reset_date = row.get("credits_reset_date")

    needs_reset = False
    if not reset_date:
        needs_reset = True
    else:
        if isinstance(reset_date, str):
            try:
                reset_date = datetime.fromisoformat(reset_date)
            except ValueError:
                needs_reset = True
        if not needs_reset and datetime.utcnow() >= reset_date:
            needs_reset = True

    if needs_reset:
        reset_monthly_credits(user_id, plan)
        with _conn() as cur:
            cur.execute(
                f"SELECT plan, credits_remaining, credits_reset_date FROM users WHERE id = {PH}",
                (user_id,)
            )
            row = _row(cur) or {}

    return row


def get_user_plan_credits(user_id: int) -> dict:
    """Return plan info and current credits. Triggers reset if needed."""
    info = check_and_reset_if_needed(user_id)
    plan = info.get("plan") or "free"
    return {
        "plan": plan,
        "credits_remaining": info.get("credits_remaining", PLAN_CREDITS.get(plan, 30)),
        "credits_total": PLAN_CREDITS.get(plan, 30),
        "credits_reset_date": info.get("credits_reset_date"),
    }


def deduct_credits(user_id: int, minutes: int):
    """Deduct credits (minutes) from user's credits_remaining."""
    with _conn() as cur:
        cur.execute(f"""
            UPDATE users SET credits_remaining = credits_remaining - {PH} WHERE id = {PH}
        """, (minutes, user_id))


def refund_credits(user_id: int, minutes: int):
    """Refund credits after a processing error, capped at plan maximum.
    Credits still won't exceed the plan total — no accumulation.
    """
    with _conn() as cur:
        cur.execute(f"SELECT plan FROM users WHERE id = {PH}", (user_id,))
        row = _row(cur)
        plan = (row.get("plan") or "free") if row else "free"
        total = PLAN_CREDITS.get(plan, 30)
        cur.execute(f"""
            UPDATE users
            SET credits_remaining = MIN(credits_remaining + {PH}, {total})
            WHERE id = {PH}
        """, (minutes, user_id))


def upsert_user(firebase_uid: str, email: str, name: str, avatar_url: str) -> dict:
    """Create or update user, return user record. Initializes credits for new users."""
    with _conn() as cur:
        cur.execute(f"""
            INSERT INTO users (firebase_uid, email, name, avatar_url)
            VALUES ({PH}, {PH}, {PH}, {PH})
            ON CONFLICT(firebase_uid) DO UPDATE SET
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                avatar_url = EXCLUDED.avatar_url
        """, (firebase_uid, email, name, avatar_url))
        cur.execute(f"SELECT * FROM users WHERE firebase_uid = {PH}", (firebase_uid,))
        user = _row(cur)

    # Initialize reset date for users that don't have one yet
    if user and not user.get("credits_reset_date"):
        reset_monthly_credits(user["id"], user.get("plan") or "free")
        with _conn() as cur:
            cur.execute(f"SELECT * FROM users WHERE id = {PH}", (user["id"],))
            user = _row(cur)

    return user


def create_job(job_id: str, user_id: int, original_filename: str,
               credits_used: int = None, expires_days: int = 7):
    """Insert a new job record."""
    expires_at = datetime.utcnow() + timedelta(days=expires_days)
    with _conn() as cur:
        cur.execute(f"""
            INSERT INTO jobs (id, user_id, original_filename, status, credits_used, expires_at)
            VALUES ({PH}, {PH}, {PH}, 'queued', {PH}, {PH})
        """, (job_id, user_id, original_filename, credits_used, expires_at.isoformat()))


def update_job_status(job_id: str, status: str, error: str = None):
    with _conn() as cur:
        cur.execute(
            f"UPDATE jobs SET status = {PH}, error = {PH} WHERE id = {PH}",
            (status, error, job_id)
        )


def insert_clip(job_id: str, filename: str, r2_key: str,
                start_sec: float, end_sec: float, score: int, description: str):
    with _conn() as cur:
        cur.execute(f"""
            INSERT INTO clips (job_id, filename, r2_key, start_sec, end_sec, score, description)
            VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
        """, (job_id, filename, r2_key, start_sec, end_sec, score, description))


def get_user_history(user_id: int) -> list:
    """Return all done jobs for a user with their clips, newest first."""
    with _conn() as cur:
        cur.execute(f"""
            SELECT * FROM jobs
            WHERE user_id = {PH} AND status = 'done'
            ORDER BY created_at DESC
        """, (user_id,))
        jobs = _rows(cur)

        for job in jobs:
            cur.execute(
                f"SELECT * FROM clips WHERE job_id = {PH} ORDER BY id ASC",
                (job["id"],)
            )
            job["clips"] = _rows(cur)

        return jobs


def get_job_with_clips(job_id: str):
    """Return a job and its clips from DB, or None if not found."""
    with _conn() as cur:
        cur.execute(f"SELECT * FROM jobs WHERE id = {PH}", (job_id,))
        job = _row(cur)
        if not job:
            return None
        cur.execute(
            f"SELECT * FROM clips WHERE job_id = {PH} ORDER BY id ASC",
            (job_id,)
        )
        job["clips"] = _rows(cur)
        return job


def delete_expired_jobs() -> list:
    """Delete expired jobs and their clips from DB, return their R2 keys."""
    with _conn() as cur:
        cur.execute(f"SELECT id FROM jobs WHERE expires_at < {NOW}")
        expired = _rows(cur)

        if not expired:
            return []

        job_ids = [r["id"] for r in expired]
        r2_keys = []

        for job_id in job_ids:
            cur.execute(f"SELECT r2_key FROM clips WHERE job_id = {PH}", (job_id,))
            r2_keys.extend(r["r2_key"] for r in _rows(cur))
            cur.execute(f"DELETE FROM clips WHERE job_id = {PH}", (job_id,))

        for job_id in job_ids:
            cur.execute(f"DELETE FROM jobs WHERE id = {PH}", (job_id,))

        return r2_keys
