"""
Phase 5 — Knowledge base: past applications, successful cases, reusable
templates, and submission history/results.

This service stores and retrieves a user's prior grant work so the AI consultant
can ground its advice in real precedent, and so the user can browse/search it.

SECURITY (Phase 2/3 lesson): the knowledge base is fully USER-SCOPED. Every
accessor takes and enforces ``user_id``; there is deliberately NO unscoped
getter. A user can never read another user's past applications/cases/templates.
Even semantic (vector) retrieval is filtered by ``user_id`` inside the SQL.

RETRIEVAL: semantic search reuses the same NVIDIA NIM embeddings + pgvector
pattern as ``grant_embeddings`` / ``RAGService`` (see embedding_service.py). When
embeddings are unavailable it degrades to a deterministic keyword fallback so the
consultant still gets grounded context offline.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, func, text, or_
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_entry import KnowledgeEntry
from services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# The knowledge kinds we accept (keeps stored data clean + queryable).
VALID_KINDS = ("past_application", "successful_case", "template", "submission")
VALID_OUTCOMES = ("won", "rejected", "submitted", "pending", "withdrawn")


class KnowledgeService:
    """User-scoped CRUD + semantic/keyword retrieval over the knowledge base."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_service = EmbeddingService(db)

    # ── Validation (pure) ───────────────────────────────────────────────────

    @staticmethod
    def validate_kind(kind: str) -> str:
        if kind not in VALID_KINDS:
            raise ValueError(
                f"Invalid kind '{kind}'. Choose one of: {', '.join(VALID_KINDS)}"
            )
        return kind

    @staticmethod
    def validate_outcome(outcome: Optional[str]) -> Optional[str]:
        if outcome is None:
            return None
        if outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"Invalid outcome '{outcome}'. Choose one of: "
                f"{', '.join(VALID_OUTCOMES)}"
            )
        return outcome

    # ── Create / update / delete (user-scoped) ──────────────────────────────

    async def create(
        self,
        *,
        user_id: int,
        kind: str,
        title: str,
        content: str = "",
        outcome: Optional[str] = None,
        package_id: Optional[int] = None,
        grant_id: Optional[int] = None,
        funder: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> KnowledgeEntry:
        self.validate_kind(kind)
        self.validate_outcome(outcome)
        entry = KnowledgeEntry(
            user_id=user_id,
            kind=kind,
            title=title,
            content=content or "",
            outcome=outcome,
            package_id=package_id,
            grant_id=grant_id,
            funder=funder,
            meta=meta or {},
            embedding_status="pending",
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def get_owned(
        self, entry_id: int, user_id: int
    ) -> Optional[KnowledgeEntry]:
        """Fetch an entry only if it belongs to ``user_id`` (else None)."""
        result = await self.db.execute(
            select(KnowledgeEntry).where(
                KnowledgeEntry.id == entry_id,
                KnowledgeEntry.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: int,
        *,
        kind: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[KnowledgeEntry], int]:
        conds = [KnowledgeEntry.user_id == user_id]
        if kind is not None:
            self.validate_kind(kind)
            conds.append(KnowledgeEntry.kind == kind)

        total = await self.db.scalar(
            select(func.count()).select_from(KnowledgeEntry).where(*conds)
        ) or 0
        result = await self.db.execute(
            select(KnowledgeEntry)
            .where(*conds)
            .order_by(KnowledgeEntry.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def update(
        self, entry_id: int, user_id: int, fields: dict
    ) -> Optional[KnowledgeEntry]:
        entry = await self.get_owned(entry_id, user_id)
        if not entry:
            return None
        if "kind" in fields and fields["kind"] is not None:
            self.validate_kind(fields["kind"])
        if "outcome" in fields:
            self.validate_outcome(fields["outcome"])
        search_text_changed = False
        for field, value in fields.items():
            if field == "content" and value is None:
                value = ""
            if value is None and field in ("kind", "title"):
                continue  # don't null required columns
            if field in ("title", "content", "funder", "kind", "outcome"):
                if value != getattr(entry, field):
                    search_text_changed = True
                setattr(entry, field, value)
            elif field == "meta" and value is not None:
                entry.meta = value
        if search_text_changed:
            # Stored embedding is now stale; mark for re-embedding.
            entry.embedding_status = "pending"
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def delete(self, entry_id: int, user_id: int) -> bool:
        entry = await self.get_owned(entry_id, user_id)
        if not entry:
            return False
        await self.db.delete(entry)
        await self.db.flush()
        return True

    # ── Embeddings (semantic indexing) ──────────────────────────────────────

    async def index_entry(self, entry: KnowledgeEntry, user_id: int) -> bool:
        """Generate + store the embedding for one owned entry.

        Replaces any prior embedding. Returns True if stored, False if indexing
        is unavailable or storage fails (the entry is still searchable by keyword).
        Never raises — embedding failure must not break knowledge-base writes.
        """
        if getattr(entry, "user_id", None) != user_id:
            logger.warning(
                "knowledge embedding skipped for non-owned entry %s and user %s",
                entry.id,
                user_id,
            )
            return False

        try:
            embedding = await self.embedding_service.generate_embedding(
                entry.search_text(), input_type="passage"
            )
        except Exception as e:  # pragma: no cover - network path
            logger.warning("knowledge embedding failed for entry %s: %s", entry.id, e)
            embedding = None
        if not embedding:
            entry.embedding_status = "failed"
            try:
                await self.db.flush()
            except Exception as e:
                logger.warning(
                    "knowledge embedding failure status flush failed for entry %s: %s",
                    entry.id,
                    e,
                )
            return False

        vec_str = f"[{','.join(str(round(x, 8)) for x in embedding)}]"
        try:
            async with self.db.begin_nested():
                await self.db.execute(
                    text(
                        """
                        DELETE FROM knowledge_embeddings
                        WHERE entry_id = :eid
                          AND EXISTS (
                              SELECT 1 FROM knowledge_entries
                              WHERE id = :eid AND user_id = :uid
                          )
                        """
                    ),
                    {"eid": entry.id, "uid": user_id},
                )
                await self.db.execute(
                    text(
                        """
                        INSERT INTO knowledge_embeddings (
                            entry_id, chunk_text, embedding
                        )
                        SELECT ke.id, :ctext, CAST(:emb AS vector)
                        FROM knowledge_entries ke
                        WHERE ke.id = :eid AND ke.user_id = :uid
                        """
                    ),
                    {
                        "eid": entry.id,
                        "uid": user_id,
                        "ctext": entry.search_text()[:8000],
                        "emb": vec_str,
                    },
                )
            entry.embedding_status = "done"
            await self.db.flush()
            return True
        except Exception as e:
            logger.warning(
                "knowledge embedding storage failed for entry %s: %s", entry.id, e
            )
            entry.embedding_status = "failed"
            try:
                await self.db.flush()
            except Exception as flush_error:
                logger.warning(
                    "knowledge embedding failure status flush failed for entry %s: %s",
                    entry.id,
                    flush_error,
                )
            return False

    # ── Retrieval (USER-SCOPED — never crosses users) ───────────────────────

    async def semantic_search(
        self, query: str, user_id: int, top_k: int = 5
    ) -> list[dict]:
        """Vector similarity over THIS user's knowledge entries only.

        The ``user_id`` filter is applied inside the SQL join so a vector hit can
        never surface another user's entry. Returns [] if embeddings unavailable.
        """
        try:
            query_embedding = await self.embedding_service.generate_embedding(
                query, input_type="query"
            )
        except Exception as e:  # pragma: no cover - network path
            logger.warning("knowledge query embedding failed: %s", e)
            return []
        if not query_embedding:
            return []

        vec_str = f"[{','.join(str(round(x, 8)) for x in query_embedding)}]"
        try:
            result = await self.db.execute(
                text(
                    """
                    SELECT ke.id, ke.kind, ke.title, ke.content, ke.outcome,
                           ke.funder, ke.grant_id, ke.package_id,
                           1 - (kemb.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM knowledge_embeddings kemb
                    JOIN knowledge_entries ke ON kemb.entry_id = ke.id
                    WHERE ke.user_id = :uid
                      AND kemb.embedding IS NOT NULL
                    ORDER BY kemb.embedding <=> CAST(:emb AS vector)
                    LIMIT :k
                    """
                ),
                {"emb": vec_str, "uid": user_id, "k": top_k},
            )
            rows = result.fetchall()
        except Exception as e:  # pragma: no cover - DB path
            logger.warning("knowledge semantic search failed: %s", e)
            return []

        return [
            {
                "id": r.id,
                "kind": r.kind,
                "title": r.title,
                "content": r.content,
                "outcome": r.outcome,
                "funder": r.funder,
                "grant_id": r.grant_id,
                "package_id": r.package_id,
                "similarity_score": float(r.similarity) if r.similarity is not None else 0.0,
            }
            for r in rows
        ]

    async def keyword_search(
        self, query: str, user_id: int, top_k: int = 5
    ) -> list[dict]:
        """Deterministic keyword fallback over THIS user's entries (no LLM/vector).

        Used when embeddings are unavailable so the consultant still has grounded
        context. ILIKE over title + content + funder; user-scoped.
        """
        q = (query or "").strip()
        conds = [KnowledgeEntry.user_id == user_id]
        if q:
            like = f"%{q}%"
            conds.append(
                or_(
                    KnowledgeEntry.title.ilike(like),
                    KnowledgeEntry.content.ilike(like),
                    KnowledgeEntry.funder.ilike(like),
                )
            )
        result = await self.db.execute(
            select(KnowledgeEntry)
            .where(*conds)
            .order_by(KnowledgeEntry.created_at.desc())
            .limit(top_k)
        )
        entries = result.scalars().all()
        return [
            {
                "id": e.id,
                "kind": e.kind,
                "title": e.title,
                "content": e.content,
                "outcome": e.outcome,
                "funder": e.funder,
                "grant_id": e.grant_id,
                "package_id": e.package_id,
                "similarity_score": None,
            }
            for e in entries
        ]

    async def retrieve_context(
        self, query: str, user_id: int, top_k: int = 5
    ) -> list[dict]:
        """Best-available grounded retrieval for the consultant.

        Tries semantic search first; falls back to keyword search when no
        embeddings/results. Always USER-SCOPED.
        """
        hits = await self.semantic_search(query, user_id, top_k=top_k)
        if hits:
            return hits
        return await self.keyword_search(query, user_id, top_k=top_k)
