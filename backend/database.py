"""SQLite database setup and CRUD for GolaClips."""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "golaclips.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                firebase_uid TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                name TEXT,
                avatar_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                original_filename TEXT,
                status TEXT DEFAULT 'queued',
                error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME
            );

            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT REFERENCES jobs(id),
                filename TEXT NOT NULL,
                r2_key TEXT NOT NULL,
                start_sec REAL,
                end_sec REAL,
                score INTEGER,
                description TEXT
            );
        """)


def upsert_user(firebase_uid: str, email: str, name: str, avatar_url: str) -> dict:
    """Create or update user, return user record."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO users (firebase_uid, email, name, avatar_url)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(firebase_uid) DO UPDATE SET
                email = excluded.email,
                name = excluded.name,
                avatar_url = excluded.avatar_url
        """, (firebase_uid, email, name, avatar_url))
        row = conn.execute(
            "SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)
        ).fetchone()
        return dict(row)


def create_job(job_id: str, user_id: int, original_filename: str):
    """Insert a new job record with 7-day expiry."""
    expires_at = datetime.utcnow() + timedelta(days=7)
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO jobs (id, user_id, original_filename, status, expires_at)
            VALUES (?, ?, ?, 'queued', ?)
        """, (job_id, user_id, original_filename, expires_at.isoformat()))


def update_job_status(job_id: str, status: str, error: str = None):
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, error = ? WHERE id = ?",
            (status, error, job_id)
        )


def insert_clip(job_id: str, filename: str, r2_key: str,
                start_sec: float, end_sec: float, score: int, description: str):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO clips (job_id, filename, r2_key, start_sec, end_sec, score, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (job_id, filename, r2_key, start_sec, end_sec, score, description))


def get_user_history(user_id: int) -> list:
    """Return all done jobs for a user with their clips, newest first."""
    with get_connection() as conn:
        jobs = conn.execute("""
            SELECT * FROM jobs
            WHERE user_id = ? AND status = 'done'
            ORDER BY created_at DESC
        """, (user_id,)).fetchall()
        result = []
        for job in jobs:
            job_dict = dict(job)
            clips = conn.execute(
                "SELECT * FROM clips WHERE job_id = ? ORDER BY id ASC",
                (job["id"],)
            ).fetchall()
            job_dict["clips"] = [dict(c) for c in clips]
            result.append(job_dict)
        return result


def get_job_with_clips(job_id: str):
    """Return a job and its clips from SQLite, or None if not found."""
    with get_connection() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return None
        job_dict = dict(job)
        clips = conn.execute(
            "SELECT * FROM clips WHERE job_id = ? ORDER BY id ASC",
            (job_id,)
        ).fetchall()
        job_dict["clips"] = [dict(c) for c in clips]
        return job_dict


def delete_expired_jobs() -> list:
    """Delete expired jobs and their clips from DB, return their R2 keys."""
    with get_connection() as conn:
        expired_jobs = conn.execute("""
            SELECT id FROM jobs WHERE expires_at < datetime('now')
        """).fetchall()

        if not expired_jobs:
            return []

        job_ids = [row["id"] for row in expired_jobs]
        r2_keys = []

        for job_id in job_ids:
            clips = conn.execute(
                "SELECT r2_key FROM clips WHERE job_id = ?", (job_id,)
            ).fetchall()
            r2_keys.extend(row["r2_key"] for row in clips)
            conn.execute("DELETE FROM clips WHERE job_id = ?", (job_id,))

        placeholders = ",".join("?" * len(job_ids))
        conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids)
        return r2_keys
