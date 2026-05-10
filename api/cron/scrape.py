"""Vercel Cron: run scrapers daily."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from fastapi import FastAPI, Header, HTTPException

from scraping.runner import run_all_scrapers_async

app = FastAPI()
CRON_SECRET = os.getenv("CRON_SECRET", "")


def _check_auth(authorization: str | None) -> None:
    if not CRON_SECRET:
        return
    if authorization != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/api/cron/scrape")
async def run_scrape(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    summary = await run_all_scrapers_async()
    return {"ok": True, "summary": summary}
