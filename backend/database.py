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


def init_db():
    """Create tables if they don't exist."""
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


def upsert_user(firebase_uid: str, email: str, name: str, avatar_url: str) -> dict:
    """Create or update user, return user record."""
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
        return _row(cur)


def create_job(job_id: str, user_id: int, original_filename: str):
    """Insert a new job record with 7-day expiry."""
    expires_at = datetime.utcnow() + timedelta(days=7)
    with _conn() as cur:
        cur.execute(f"""
            INSERT INTO jobs (id, user_id, original_filename, status, expires_at)
            VALUES ({PH}, {PH}, {PH}, 'queued', {PH})
        """, (job_id, user_id, original_filename, expires_at.isoformat()))


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

        # Delete jobs one by one to avoid driver-specific IN clause issues
        for job_id in job_ids:
            cur.execute(f"DELETE FROM jobs WHERE id = {PH}", (job_id,))

        return r2_keys
