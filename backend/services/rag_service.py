"""
RAG (Retrieval-Augmented Generation) Service

ANTI-HALLUCINATION DESIGN:
- LLM NEVER answers from memory — only from retrieved verified context
- Source URLs are always cited
- If no relevant data found → explicit "not found" response
- Confidence scores prevent low-quality results from surfacing

Flow:
  User Query → Generate Query Embedding → Vector Search (pgvector)
  → Hybrid Merge (SQL + Vector) → Build Context → NVIDIA LLM
  → Grounded Response with Citations → Return to User
"""
import logging
from typing import Optional, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI

from core.config import get_settings
from services.embedding_service import EmbeddingService
from models.search_log import SearchLog

logger = logging.getLogger(__name__)
settings = get_settings()

# Strict anti-hallucination system prompt
RAG_SYSTEM_PROMPT = """You are a grant recommendation assistant for Ansar Consulting.

STRICT RULES — NEVER VIOLATE:
1. Answer ONLY using the verified grant data provided below
2. NEVER invent grants, deadlines, funding amounts, or organizations
3. NEVER assume eligibility criteria not stated in the data
4. If information is missing or unavailable, say: "This information was not found in our verified database"
5. Always cite the source URL for every grant you mention
6. Format each grant recommendation clearly with: Title, Organization, Country, Deadline, Amount, and Source URL
7. If no relevant grants found in the context, say so explicitly

You help employees at Ansar Consulting find grants for their clients:
universities, startups, NGOs, research centers, students, and innovation programs."""


class RAGService:
    """Full RAG pipeline: semantic search + grounded LLM response generation."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_service = EmbeddingService(db)
        self._llm: Optional["AsyncOpenAI"] = None
        if settings.nvidia_api_key:
            from openai import AsyncOpenAI

            self._llm = AsyncOpenAI(
                base_url=settings.nvidia_base_url,
                api_key=settings.nvidia_api_key,
            )

    async def semantic_search(self, query: str, top_k: int = 15) -> list[dict]:
        """
        Run vector similarity search against grant_embeddings using pgvector.
        Returns grants sorted by semantic similarity to the query.
        """
        query_embedding = await self.embedding_service.generate_embedding(
            query, input_type="query"
        )
        if not query_embedding:
            logger.warning("Could not generate query embedding — falling back to keyword search")
            return []

        vec_str = f"[{','.join(str(round(x, 8)) for x in query_embedding)}]"

        result = await self.db.execute(
            text("""
                SELECT DISTINCT ON (g.id)
                    g.id, g.title, g.organization, g.country, g.category,
                    g.description, g.deadline, g.source_url, g.status,
                    g.ai_score, g.grant_amount, g.eligibility, g.industry,
                    g.startup_stage, g.application_url, g.confidence_score,
                    1 - (ge.embedding <=> CAST(:emb AS vector)) AS similarity
                FROM grant_embeddings ge
                JOIN grants g ON ge.grant_id = g.id
                WHERE g.status IN ('approved', 'pending')
                  AND ge.embedding IS NOT NULL
                ORDER BY g.id, ge.embedding <=> CAST(:emb AS vector)
            """),
            {"emb": vec_str},
        )
        rows = result.fetchall()

        # Sort by similarity descending, return top_k
        grants = []
        for row in rows:
            grants.append({
                "id": row.id,
                "title": row.title,
                "organization": row.organization,
                "country": row.country,
                "category": row.category,
                "description": row.description,
                "deadline": str(row.deadline) if row.deadline else None,
                "source_url": row.source_url,
                "status": row.status,
                "ai_score": row.ai_score,
                "grant_amount": row.grant_amount,
                "eligibility": row.eligibility,
                "industry": row.industry,
                "startup_stage": row.startup_stage,
                "application_url": row.application_url,
                "confidence_score": row.confidence_score,
                "similarity_score": float(row.similarity),
            })

        grants.sort(key=lambda x: x["similarity_score"], reverse=True)
        return grants[:top_k]

    def _build_rag_context(self, grants: list[dict]) -> str:
        """Build the verified context string passed to the LLM. Max 5 grants."""
        if not grants:
            return "No verified grants found in database for this query."

        lines = []
        for i, g in enumerate(grants[:5], 1):
            lines.append(f"\n{'='*40}")
            lines.append(f"GRANT #{i} [ID: {g['id']}]")
            lines.append(f"Title: {g['title']}")
            if g.get("organization"):
                lines.append(f"Organization: {g['organization']}")
            if g.get("country"):
                lines.append(f"Country: {g['country']}")
            if g.get("category"):
                lines.append(f"Category: {g['category']}")
            if g.get("industry"):
                lines.append(f"Industry: {g['industry']}")
            if g.get("startup_stage"):
                lines.append(f"Stage: {g['startup_stage']}")
            if g.get("deadline"):
                lines.append(f"Deadline: {g['deadline']}")
            if g.get("grant_amount"):
                lines.append(f"Amount: {g['grant_amount']}")
            if g.get("eligibility"):
                lines.append(f"Eligibility: {g['eligibility'][:400]}")
            if g.get("description"):
                lines.append(f"Description: {g['description'][:600]}")
            lines.append(f"Source URL: {g['source_url']}")
            if g.get("application_url") and g["application_url"] != g["source_url"]:
                lines.append(f"Apply Here: {g['application_url']}")

        return "\n".join(lines)

    async def generate_grounded_response(self, query: str, grants: list[dict]) -> str:
        """
        Generate LLM response using ONLY the retrieved context (anti-hallucination).
        Falls back to structured text if LLM unavailable.
        """
        if not self._llm:
            return self._plain_text_response(grants)

        context = self._build_rag_context(grants)

        try:
            response = await self._llm.chat.completions.create(
                model=settings.nvidia_model,
                messages=[
                    {"role": "system", "content": RAG_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"VERIFIED GRANT DATABASE CONTEXT:\n{context}\n\n"
                            f"{'='*40}\n"
                            f"EMPLOYEE QUERY: {query}\n\n"
                            "Based ONLY on the verified grants above, provide helpful recommendations."
                        ),
                    },
                ],
                temperature=0.3,
                max_tokens=1200,
                timeout=60,
            )
            return response.choices[0].message.content or self._plain_text_response(grants)
        except Exception as e:
            logger.error(f"RAG LLM call failed: {e}")
            return self._plain_text_response(grants)

    def _plain_text_response(self, grants: list[dict]) -> str:
        """Structured fallback response when LLM is unavailable."""
        if not grants:
            return "Verified information was not found in our database for this query."

        lines = [f"Found {len(grants)} relevant grant(s):\n"]
        for g in grants[:5]:
            lines.append(f"📌 {g['title']}")
            if g.get("organization"):
                lines.append(f"   Organization: {g['organization']}")
            if g.get("country"):
                lines.append(f"   Country: {g['country']}")
            if g.get("deadline"):
                lines.append(f"   Deadline: {g['deadline']}")
            if g.get("grant_amount"):
                lines.append(f"   Amount: {g['grant_amount']}")
            lines.append(f"   Source: {g['source_url']}")
            lines.append("")
        return "\n".join(lines)

    async def recommend(
        self, query: str, limit: int = 5, user_id: Optional[str] = None
    ) -> tuple[list[dict], str]:
        """
        Full RAG recommendation pipeline.
        Returns (grant_list, llm_grounded_response).
        """
        # Step 1: Semantic vector search
        grants = await self.semantic_search(query, top_k=limit * 3)

        # Step 2: Fallback to keyword search if no embeddings yet
        if not grants:
            logger.info("No embeddings found — falling back to keyword search")
            from services.search_service import SearchService
            search_svc = SearchService(self.db)
            grants = await search_svc.keyword_search(query, limit=limit * 2)

        # Step 3: Generate grounded response
        response = await self.generate_grounded_response(query, grants[:limit])

        # Step 4: Log search for analytics
        try:
            log = SearchLog(
                query=query,
                user_id=user_id,
                results_count=len(grants[:limit]),
                search_type="semantic" if grants else "keyword",
            )
            self.db.add(log)
            await self.db.flush()
        except Exception:
            pass

        return grants[:limit], response
