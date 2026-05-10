"""Vercel Cron: recompute AI scores."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from fastapi import FastAPI, Header, HTTPException

from database.connection import AsyncSessionLocal
from services.ai_service import AIService

app = FastAPI()
CRON_SECRET = os.getenv("CRON_SECRET", "")


def _check_auth(authorization: str | None) -> None:
    if not CRON_SECRET:
        return
    if authorization != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/api/cron/score")
async def run_score(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    async with AsyncSessionLocal() as db:
        service = AIService(db)
        count = await service.update_all_scores()
        await db.commit()
    return {"ok": True, "updated": count}
