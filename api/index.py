"""
Vercel Python serverless entry for the FastAPI backend.
URL routing: vercel.json rewrites every non-/api/ path here, so FastAPI keeps
its original routes (/auth/login, /grants, etc.).
"""
import sys
from pathlib import Path

# Make `backend/` importable as a package root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import auth, grants, reviews, stats, recommendations, scraper
from core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="AI Grant Agent",
    description="Automated grant sourcing and management system",
    version="1.0.0",
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(grants.router)
app.include_router(reviews.router)
app.include_router(stats.router)
app.include_router(recommendations.router)
app.include_router(scraper.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "AI Grant Agent Backend"}
