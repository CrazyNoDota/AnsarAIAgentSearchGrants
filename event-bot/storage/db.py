from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

PROFILE_FIELDS: tuple[str, ...] = (
    "full_name",
    "first_name",
    "last_name",
    "email",
    "phone",
    "company",
    "job_title",
    "country",
    "city",
    "website",
    "linkedin",
    "bio_short",
)

PROFILE_LABELS: dict[str, str] = {
    "full_name": "Полное имя (как в паспорте/визитке)",
    "first_name": "Имя",
    "last_name": "Фамилия",
    "email": "Email",
    "phone": "Телефон (с кодом страны, напр. +7 701 234 56 78)",
    "company": "Название компании / организации",
    "job_title": "Должность",
    "country": "Страна",
    "city": "Город",
    "website": "Сайт компании (необязательно — отправь '-' чтобы пропустить)",
    "linkedin": "LinkedIn URL (необязательно — '-' чтобы пропустить)",
    "bio_short": "Короткое био 1-2 предложения (необязательно — '-' чтобы пропустить)",
}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    telegram_id      INTEGER PRIMARY KEY,
    full_name        TEXT,
    first_name       TEXT,
    last_name        TEXT,
    email            TEXT,
    phone            TEXT,
    company          TEXT,
    job_title        TEXT,
    country          TEXT,
    city             TEXT,
    website          TEXT,
    linkedin         TEXT,
    bio_short        TEXT,
    created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at       TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS custom_answers (
    telegram_id      INTEGER NOT NULL,
    field_signature  TEXT NOT NULL,
    field_label      TEXT,
    answer           TEXT NOT NULL,
    updated_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (telegram_id, field_signature)
);

CREATE TABLE IF NOT EXISTS registrations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id      INTEGER NOT NULL,
    url              TEXT NOT NULL,
    status           TEXT NOT NULL,
    detail           TEXT,
    payload          TEXT,
    created_at       TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


_DB_PATH: Path | None = None


def configure(db_path: str) -> None:
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def _conn() -> AsyncIterator[aiosqlite.Connection]:
    if _DB_PATH is None:
        raise RuntimeError("storage.db.configure() was not called")
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    async with _conn() as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def get_profile(telegram_id: int) -> dict[str, Any] | None:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM profiles WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def upsert_profile(telegram_id: int, data: dict[str, Any]) -> None:
    fields = [k for k in data.keys() if k in PROFILE_FIELDS]
    if not fields:
        return
    placeholders = ", ".join("?" for _ in fields)
    columns = ", ".join(fields)
    values = [data[k] for k in fields]

    update_assignments = ", ".join(f"{f} = excluded.{f}" for f in fields)

    sql = (
        f"INSERT INTO profiles (telegram_id, {columns}) "
        f"VALUES (?, {placeholders}) "
        f"ON CONFLICT(telegram_id) DO UPDATE SET {update_assignments}, "
        f"updated_at = CURRENT_TIMESTAMP"
    )
    async with _conn() as db:
        await db.execute(sql, [telegram_id, *values])
        await db.commit()


async def get_custom_answer(telegram_id: int, field_signature: str) -> str | None:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT answer FROM custom_answers WHERE telegram_id = ? AND field_signature = ?",
            (telegram_id, field_signature),
        )
        row = await cur.fetchone()
        return row["answer"] if row else None


async def save_custom_answer(
    telegram_id: int, field_signature: str, field_label: str, answer: str
) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO custom_answers (telegram_id, field_signature, field_label, answer) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(telegram_id, field_signature) DO UPDATE SET "
            "answer = excluded.answer, field_label = excluded.field_label, "
            "updated_at = CURRENT_TIMESTAMP",
            (telegram_id, field_signature, field_label, answer),
        )
        await db.commit()


async def log_registration(
    telegram_id: int,
    url: str,
    status: str,
    detail: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    async with _conn() as db:
        cur = await db.execute(
            "INSERT INTO registrations (telegram_id, url, status, detail, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (telegram_id, url, status, detail, json.dumps(payload) if payload else None),
        )
        await db.commit()
        return cur.lastrowid or 0
