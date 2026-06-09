"""
AI Grant Discovery & Recommendation System — FastAPI Backend
VPS Production Mode (no Vercel, no APScheduler — n8n handles scheduling)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import auth, grants, reviews, stats, recommendations, scraper
from api.routes import search, deadlines, embeddings, subscriptions, profiles
from api.routes import applications, knowledge, consultant
from core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AI Grant Agent backend starting (VPS mode, n8n orchestration)...")
    logger.info(f"NVIDIA API: {'✓' if settings.use_nvidia_ai else '✗'}")
    logger.info(f"Tavily: {'✓' if settings.use_tavily else '✗'}")
    logger.info(f"Firecrawl: {'✓' if settings.use_firecrawl else '✗'}")
    logger.info(f"Email/SMTP: {'✓' if settings.use_email else '✗'}")
    yield
    logger.info("Backend shutting down")


app = FastAPI(
    title="AI Grant Agent",
    description=(
        "Automated grant discovery and recommendation system. "
        "Uses RAG architecture with pgvector for anti-hallucination responses. "
        "VPS deployment with n8n workflow automation."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow Vercel frontend + local dev
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core CRUD routes
app.include_router(auth.router)
app.include_router(grants.router)
app.include_router(reviews.router)
app.include_router(stats.router)
app.include_router(profiles.router)
app.include_router(applications.router)
app.include_router(knowledge.router)

# AI / RAG routes
app.include_router(recommendations.router)
app.include_router(search.router)
app.include_router(embeddings.router)
app.include_router(consultant.router)

# Operations routes
app.include_router(scraper.router)
app.include_router(deadlines.router)
app.include_router(subscriptions.router)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "AI Grant Agent",
        "version": "2.0.0",
        "features": {
            "rag": True,
            "nvidia_ai": settings.use_nvidia_ai,
            "multimodal": settings.use_step,
            "tavily": settings.use_tavily,
            "firecrawl": settings.use_firecrawl,
            "email": settings.use_email,
        },
    }
