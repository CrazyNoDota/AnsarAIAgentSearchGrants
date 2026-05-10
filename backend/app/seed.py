"""
Seed script — creates default admin user on first run.
Called once via: python -m app.seed
"""
import asyncio
import logging
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select
from database.connection import AsyncSessionLocal
from models.user import User
from core.security import get_password_hash
from core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed():
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(User).where(User.username == settings.admin_username)
        )
        if existing:
            logger.info(f"Admin user '{settings.admin_username}' already exists — skipping seed")
            return

        user = User(
            username=settings.admin_username,
            hashed_password=get_password_hash(settings.admin_password),
            is_active=True,
        )
        db.add(user)
        await db.commit()
        logger.info(f"✅ Created admin user: {settings.admin_username}")


if __name__ == "__main__":
    asyncio.run(seed())
