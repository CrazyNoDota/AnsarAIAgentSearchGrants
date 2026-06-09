"""
NVIDIA NIM Embedding Service
Generates 1024-dimensional embeddings using nvidia/nv-embedqa-e5-v5
Stores them in PostgreSQL via pgvector for semantic/RAG search
"""
import logging
from typing import Optional, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import get_settings
from models.grant import Grant

logger = logging.getLogger(__name__)
settings = get_settings()

EMBEDDING_DIM = 1024
MAX_INPUT_CHARS = 8000  # Safe limit for embedding input


class EmbeddingService:
    """Handles embedding generation via NVIDIA NIM and storage in pgvector."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._client: Optional["AsyncOpenAI"] = None
        api_key = settings.embedding_api_key
        if api_key:
            # Lazy import keeps this service importable without `openai`
            # installed (offline/minimal environments).
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                base_url=settings.nvidia_base_url,
                api_key=api_key,
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def generate_embedding(
        self, text_input: str, input_type: str = "passage"
    ) -> Optional[list[float]]:
        """
        Generate embedding vector via NVIDIA NIM API.

        Args:
            text_input: Text to embed (truncated to MAX_INPUT_CHARS)
            input_type: 'passage' for documents, 'query' for search queries
        """
        if not self._client or not text_input.strip():
            return None

        try:
            response = await self._client.embeddings.create(
                model=settings.nvidia_embedding_model,
                input=[text_input[:MAX_INPUT_CHARS]],
                encoding_format="float",
                extra_body={
                    "input_type": input_type,
                    "truncate": "END",
                },
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding generation failed ({input_type}): {e}")
            raise

    def _build_chunks(self, grant: Grant) -> list[tuple[str, str]]:
        """
        Build text chunks from grant data for multi-chunk indexing.
        Returns list of (chunk_type, chunk_text) pairs.
        """
        chunks = []

        # Primary chunk: combined summary for search
        summary_parts = []
        if grant.title:
            summary_parts.append(f"Title: {grant.title}")
        if grant.organization:
            summary_parts.append(f"Organization: {grant.organization}")
        if grant.country:
            summary_parts.append(f"Country: {grant.country}")
        if grant.category:
            summary_parts.append(f"Category: {grant.category}")
        if grant.industry:
            summary_parts.append(f"Industry: {grant.industry}")
        if grant.startup_stage:
            summary_parts.append(f"Stage: {grant.startup_stage}")
        if grant.grant_amount:
            summary_parts.append(f"Amount: {grant.grant_amount}")
        if grant.description:
            summary_parts.append(f"Description: {grant.description[:3000]}")
        if summary_parts:
            chunks.append(("summary", "\n".join(summary_parts)))

        # Eligibility chunk (separate so it can be retrieved specifically)
        if grant.eligibility:
            chunks.append(("eligibility", f"Eligibility criteria for {grant.title}:\n{grant.eligibility[:2000]}"))

        return chunks

    async def generate_grant_embeddings(self, grant: Grant) -> int:
        """
        Generate and store all embeddings for a single grant.
        Deletes old embeddings first to avoid duplicates.
        Returns the number of chunks stored.
        """
        # Remove stale embeddings
        await self.db.execute(
            text("DELETE FROM grant_embeddings WHERE grant_id = :gid"),
            {"gid": grant.id},
        )

        chunks = self._build_chunks(grant)
        stored = 0

        for chunk_type, chunk_text in chunks:
            embedding = await self.generate_embedding(chunk_text, input_type="passage")
            if not embedding:
                continue

            # Build vector literal string: "[0.1, 0.2, ...]"
            vec_str = f"[{','.join(str(round(x, 8)) for x in embedding)}]"

            await self.db.execute(
                text("""
                    INSERT INTO grant_embeddings (grant_id, chunk_type, chunk_text, embedding)
                    VALUES (:gid, :ctype, :ctext, CAST(:emb AS vector))
                """),
                {
                    "gid": grant.id,
                    "ctype": chunk_type,
                    "ctext": chunk_text,
                    "emb": vec_str,
                },
            )
            stored += 1

        # Update embedding status on the grant
        grant.embedding_status = "done" if stored > 0 else "failed"
        await self.db.flush()

        return stored

    async def generate_pending_embeddings(self, batch_size: int = 20) -> dict:
        """
        Process grants that haven't been embedded yet.
        Each grant is committed independently so one failure doesn't poison others.
        """
        result = await self.db.execute(
            select(Grant.id).where(Grant.embedding_status == "pending").limit(batch_size)
        )
        grant_ids = list(result.scalars().all())

        if not grant_ids:
            return {"processed": 0, "failed": 0, "total": 0}

        processed = failed = 0
        for grant_id in grant_ids:
            try:
                grant = await self.db.get(Grant, grant_id)
                if not grant:
                    continue
                count = await self.generate_grant_embeddings(grant)
                await self.db.commit()
                if count > 0:
                    processed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Embedding failed for grant {grant_id}: {e}")
                await self.db.rollback()
                try:
                    grant = await self.db.get(Grant, grant_id)
                    if grant:
                        grant.embedding_status = "failed"
                        await self.db.commit()
                except Exception:
                    await self.db.rollback()
                failed += 1

        logger.info(f"Embedding pipeline: {processed} done, {failed} failed of {len(grant_ids)} total")
        return {"processed": processed, "failed": failed, "total": len(grant_ids)}

    async def reembed_grant(self, grant_id: int) -> bool:
        """Force re-embedding of a single grant (e.g., after approval)."""
        try:
            grant = await self.db.get(Grant, grant_id)
            if not grant:
                return False
            grant.embedding_status = "pending"
            count = await self.generate_grant_embeddings(grant)
            await self.db.commit()
            return count > 0
        except Exception as e:
            logger.error(f"reembed_grant {grant_id} failed: {e}")
            await self.db.rollback()
            return False
