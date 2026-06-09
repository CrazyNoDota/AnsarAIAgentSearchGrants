"""
Embedding Management Endpoints
Called by n8n workflow to process pending embeddings.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from services.embedding_service import EmbeddingService
from api.deps import get_current_user
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/embeddings", tags=["embeddings"])


@router.post("/generate-pending")
async def generate_pending_embeddings(
    batch_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Process grants with embedding_status='pending'.
    Called by n8n workflow after scraping completes.
    """
    service = EmbeddingService(db)
    result = await service.generate_pending_embeddings(batch_size=batch_size)
    return result


@router.post("/{grant_id}/reembed")
async def reembed_grant(
    grant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Force re-generation of embeddings for a specific grant."""
    service = EmbeddingService(db)
    success = await service.reembed_grant(grant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Grant not found or embedding failed")
    return {"grant_id": grant_id, "status": "reembedded"}
