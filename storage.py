import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent / "trainer.db"


@dataclass
class UserStats:
    vk_id: int
    correct: int
    wrong: int


class Storage:
    REVIEW_INTERVALS = [1, 3, 7, 14]

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _column_exists(self, conn: sqlite3.Connection, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row["name"] == column for row in rows)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    vk_id INTEGER PRIMARY KEY,
                    correct INTEGER NOT NULL DEFAULT 0,
                    wrong INTEGER NOT NULL DEFAULT 0,
                    diagnostic_done INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            if not self._column_exists(conn, "users", "diagnostic_done"):
                conn.execute("ALTER TABLE users ADD COLUMN diagnostic_done INTEGER NOT NULL DEFAULT 0")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_stats (
                    vk_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    correct INTEGER NOT NULL DEFAULT 0,
                    wrong INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (vk_id, topic)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS active_questions (
                    vk_id INTEGER PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_schedule (
                    vk_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 0,
                    interval_days INTEGER NOT NULL DEFAULT 1,
                    due_at TEXT NOT NULL,
                    PRIMARY KEY (vk_id, topic)
                )
                """
            )

    def ensure_user(self, vk_id: int) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO users(vk_id) VALUES (?)", (vk_id,))

    def get_user_stats(self, vk_id: int) -> UserStats:
        self.ensure_user(vk_id)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE vk_id = ?", (vk_id,)).fetchone()
        return UserStats(vk_id=vk_id, correct=row["correct"], wrong=row["wrong"])

    def is_diagnostic_done(self, vk_id: int) -> bool:
        self.ensure_user(vk_id)
        with self._connect() as conn:
            row = conn.execute("SELECT diagnostic_done FROM users WHERE vk_id = ?", (vk_id,)).fetchone()
        return bool(row["diagnostic_done"])

    def set_diagnostic_done(self, vk_id: int, done: bool = True) -> None:
        self.ensure_user(vk_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET diagnostic_done = ? WHERE vk_id = ?",
                (1 if done else 0, vk_id),
            )

    def get_topic_stats(self, vk_id: int) -> Dict[str, Dict[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT topic, correct, wrong FROM topic_stats WHERE vk_id = ?", (vk_id,)
            ).fetchall()
        return {
            row["topic"]: {"correct": row["correct"], "wrong": row["wrong"]}
            for row in rows
        }

    def get_due_review_topics(self, vk_id: int, limit: int = 5) -> List[str]:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT topic FROM review_schedule
                WHERE vk_id = ? AND due_at <= ?
                ORDER BY due_at ASC
                LIMIT ?
                """,
                (vk_id, now, limit),
            ).fetchall()
        return [row["topic"] for row in rows]

    def _update_review_schedule(self, conn: sqlite3.Connection, vk_id: int, topic: str, is_correct: bool) -> None:
        current = conn.execute(
            "SELECT level FROM review_schedule WHERE vk_id = ? AND topic = ?",
            (vk_id, topic),
        ).fetchone()

        if not is_correct:
            level = 0
        elif current is None:
            return
        else:
            level = min(current["level"] + 1, len(self.REVIEW_INTERVALS) - 1)

        interval = self.REVIEW_INTERVALS[level]
        due_at = (datetime.utcnow() + timedelta(days=interval)).isoformat()
        conn.execute(
            """
            INSERT INTO review_schedule(vk_id, topic, level, interval_days, due_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(vk_id, topic)
            DO UPDATE SET level = excluded.level, interval_days = excluded.interval_days, due_at = excluded.due_at
            """,
            (vk_id, topic, level, interval, due_at),
        )

    def update_result(self, vk_id: int, topic: str, is_correct: bool) -> None:
        self.ensure_user(vk_id)
        with self._connect() as conn:
            if is_correct:
                conn.execute(
                    "UPDATE users SET correct = correct + 1 WHERE vk_id = ?", (vk_id,)
                )
                conn.execute(
                    """
                    INSERT INTO topic_stats(vk_id, topic, correct, wrong)
                    VALUES (?, ?, 1, 0)
                    ON CONFLICT(vk_id, topic)
                    DO UPDATE SET correct = correct + 1
                    """,
                    (vk_id, topic),
                )
            else:
                conn.execute("UPDATE users SET wrong = wrong + 1 WHERE vk_id = ?", (vk_id,))
                conn.execute(
                    """
                    INSERT INTO topic_stats(vk_id, topic, correct, wrong)
                    VALUES (?, ?, 0, 1)
                    ON CONFLICT(vk_id, topic)
                    DO UPDATE SET wrong = wrong + 1
                    """,
                    (vk_id, topic),
                )

            self._update_review_schedule(conn, vk_id, topic, is_correct)

    def set_active_question(self, vk_id: int, payload: dict) -> None:
        blob = json.dumps(payload, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO active_questions(vk_id, payload)
                VALUES (?, ?)
                ON CONFLICT(vk_id) DO UPDATE SET payload = excluded.payload
                """,
                (vk_id, blob),
            )

    def get_active_question(self, vk_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM active_questions WHERE vk_id = ?", (vk_id,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])

    def clear_active_question(self, vk_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM active_questions WHERE vk_id = ?", (vk_id,))
