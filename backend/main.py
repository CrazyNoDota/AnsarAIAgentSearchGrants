import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import auth, grants, reviews, stats, recommendations, scraper
from core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# APScheduler runs only in local/docker dev. Vercel uses /api/cron/* endpoints
# instead. Set RUN_SCHEDULER=1 in docker-compose to enable.
_run_scheduler = os.getenv("RUN_SCHEDULER", "0") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Grant Agent backend...")
    scheduler = None
    if _run_scheduler:
        from scheduler.jobs import create_scheduler
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("Scheduler started (local mode)")
    else:
        logger.info("Scheduler disabled (serverless mode — use Vercel Cron)")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


app = FastAPI(
    title="AI Grant Agent",
    description="Automated grant sourcing and management system",
    version="1.0.0",
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(grants.router)
app.include_router(reviews.router)
app.include_router(stats.router)
app.include_router(recommendations.router)
app.include_router(scraper.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "AI Grant Agent Backend"}
