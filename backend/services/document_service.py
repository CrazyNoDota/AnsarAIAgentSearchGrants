"""
Phase 3 — Grant-application document package generation.

Generates a structured application package (Executive Summary, Project
Description, Objectives & KPIs, Budget, ...) for a given (company profile,
grant) pair, drafting each section with NVIDIA NIM (Qwen3) via the OpenAI-
compatible *Chat Completions* API — the same direct path the rest of the repo
uses (see services/ai_service.py, scraping/nim_client.py). Webwright's Responses
API is intentionally NOT used (Phase 0 finding).

ANTI-HALLUCINATION DESIGN (consistent with RAG / matching services):
- Every section is generated ONLY from the supplied company profile + grant
  details (+ optional extracted grant-call text). The system prompt forbids
  inventing facts; unknowns must be emitted as explicit "[TODO: ...]"
  placeholders, never fabricated.
- The context fed to the model is built deterministically (pure functions below)
  so it is unit-testable without any network call.
- If the LLM is unavailable, each section degrades to a deterministic scaffold
  containing the known facts + placeholders — the package is still produced, it
  just isn't prose.

Persistence is fully USER-SCOPED from the start (Phase 2 security lesson):
packages belong to the user who generated them; there is no unscoped getter.
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import AsyncOpenAI

from core.config import get_settings
from models.application_document import ApplicationPackage
from models.grant import Grant
from models.profile import CompanyProfile
from services.document_templates import SectionTemplate, get_sections

logger = logging.getLogger(__name__)
settings = get_settings()

# Hard cap on a single section's LLM call. Kept well under typical gateway
# limits; sections are generated sequentially so total time scales with count.
SECTION_TIMEOUT_SECONDS = 60

SYSTEM_PROMPT = (
    "You are an expert grant-application writer for Ansar Consulting. You draft "
    "professional, fundable application sections in clear English.\n\n"
    "STRICT RULES — NEVER VIOLATE:\n"
    "1. Use ONLY the facts given in the COMPANY PROFILE and GRANT DETAILS (and "
    "any EXTRACTED GRANT-CALL TEXT). Do not invent organizations, partners, "
    "people, achievements, metrics, dates or financial figures.\n"
    "2. When a fact required by the section is missing, insert a clearly marked "
    "placeholder such as \"[TODO: provide ...]\" instead of making one up.\n"
    "3. Do not contradict the provided facts (e.g. funding amounts, eligibility, "
    "deadlines).\n"
    "4. Write only the requested section's body — no preamble like 'Here is', no "
    "markdown code fences, and do not repeat the section heading."
)


def build_profile_context(profile: CompanyProfile) -> str:
    """Deterministic natural-language description of the applicant.

    Reuses the same text the matching engine embeds, so generation and fit
    scoring stay grounded in identical profile facts.
    """
    return profile.profile_text()


def build_grant_context(grant: Grant) -> str:
    """Deterministic description of the target grant for grounding."""
    parts: list[str] = [f"Title: {grant.title}"]
    if grant.organization:
        parts.append(f"Funder/Organization: {grant.organization}")
    if grant.country:
        parts.append(f"Country: {grant.country}")
    if grant.region:
        parts.append(f"Region: {grant.region}")
    if grant.category:
        parts.append(f"Category: {grant.category}")
    if grant.industry:
        parts.append(f"Industry: {grant.industry}")
    if grant.startup_stage:
        parts.append(f"Eligible stage: {grant.startup_stage}")
    if grant.deadline:
        parts.append(f"Deadline: {grant.deadline}")
    if grant.grant_amount:
        parts.append(f"Funding amount: {grant.grant_amount}")
    # Normalized numeric budget window (Phase 1 fields), when present.
    if grant.budget_min is not None or grant.budget_max is not None:
        cur = grant.currency or ""
        lo = grant.budget_min if grant.budget_min is not None else "?"
        hi = grant.budget_max if grant.budget_max is not None else "?"
        parts.append(f"Funding range: {cur} {lo} - {hi}".strip())
    if grant.eligibility:
        parts.append(f"Eligibility: {grant.eligibility[:1200]}")
    if grant.description:
        parts.append(f"Description: {grant.description[:2000]}")
    if grant.source_url:
        parts.append(f"Source: {grant.source_url}")
    return "\n".join(parts)


class DocumentService:
    """Generates and persists grant-application document packages."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._llm: Optional["AsyncOpenAI"] = None
        if settings.nvidia_api_key:
            # Lazy import keeps the service importable in minimal/offline envs.
            from openai import AsyncOpenAI

            self._llm = AsyncOpenAI(
                base_url=settings.nvidia_base_url,
                api_key=settings.nvidia_api_key,
            )

    @property
    def llm_available(self) -> bool:
        return self._llm is not None

    # ── Prompt construction (pure / testable) ──────────────────────────────

    @staticmethod
    def _section_messages(
        section: SectionTemplate,
        profile_ctx: str,
        grant_ctx: str,
        extra_ctx: Optional[str] = None,
    ) -> list[dict]:
        """Build the chat messages for one section. Pure — no network."""
        user_parts = [
            f"COMPANY PROFILE:\n{profile_ctx}",
            f"\nGRANT DETAILS:\n{grant_ctx}",
        ]
        if extra_ctx:
            # Bound the extracted-call text so the prompt stays within limits.
            user_parts.append(f"\nEXTRACTED GRANT-CALL TEXT:\n{extra_ctx[:4000]}")
        user_parts.append(
            f"\nWrite the \"{section.title}\" section now.\n"
            f"Instructions: {section.guidance}"
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    @staticmethod
    def _fallback_section(section: SectionTemplate) -> str:
        """Deterministic scaffold used when the LLM is unavailable or errors.

        Produces no invented facts — only the section's intent plus a TODO so a
        human can complete it. Keeps the package well-formed without the model.
        """
        return (
            f"[Draft unavailable — AI generation was not available for this "
            f"section.]\n\nPurpose: {section.guidance}\n\n"
            f"[TODO: complete the {section.title} section.]"
        )

    # ── Generation ─────────────────────────────────────────────────────────

    async def generate_section(
        self,
        section: SectionTemplate,
        profile_ctx: str,
        grant_ctx: str,
        extra_ctx: Optional[str] = None,
    ) -> str:
        """Generate one section's body. Falls back to a scaffold on any failure."""
        if not self._llm:
            return self._fallback_section(section)
        try:
            resp = await self._llm.chat.completions.create(
                model=settings.nvidia_model,
                messages=self._section_messages(
                    section, profile_ctx, grant_ctx, extra_ctx
                ),
                temperature=0.4,
                max_tokens=section.max_tokens,
                timeout=SECTION_TIMEOUT_SECONDS,
            )
            content = (resp.choices[0].message.content or "").strip()
            return content or self._fallback_section(section)
        except Exception as e:  # network/timeout/rate-limit must not crash the run
            logger.warning("section '%s' generation failed: %s", section.key, e)
            return self._fallback_section(section)

    async def generate_package_content(
        self,
        profile: CompanyProfile,
        grant: Grant,
        section_keys: Optional[list[str]] = None,
        extra_ctx: Optional[str] = None,
    ) -> dict:
        """Generate the full package content (no persistence).

        Returns a dict with a title and an ordered list of section dicts:
            {"title", "grant_id", "profile_id", "sections": [{key,title,content}],
             "llm_used": bool}
        Raises ValueError for unknown section keys (surfaced as 400 by the API).
        """
        sections = get_sections(section_keys)
        profile_ctx = build_profile_context(profile)
        grant_ctx = build_grant_context(grant)

        out_sections: list[dict] = []
        for section in sections:
            body = await self.generate_section(
                section, profile_ctx, grant_ctx, extra_ctx
            )
            out_sections.append(
                {"key": section.key, "title": section.title, "content": body}
            )

        return {
            "title": f"Application: {profile.name} → {grant.title}",
            "grant_id": grant.id,
            "profile_id": profile.id,
            "sections": out_sections,
            "llm_used": self.llm_available,
        }

    # ── Persistence (user-scoped) ──────────────────────────────────────────

    async def create_package(
        self,
        *,
        user_id: int,
        profile: CompanyProfile,
        grant: Grant,
        content: dict,
    ) -> ApplicationPackage:
        pkg = ApplicationPackage(
            user_id=user_id,
            profile_id=profile.id,
            grant_id=grant.id,
            grant_title=grant.title,
            title=content["title"],
            status="complete" if content.get("llm_used") else "draft",
            sections=content["sections"],
        )
        self.db.add(pkg)
        await self.db.flush()
        await self.db.refresh(pkg)
        return pkg

    async def get_owned(
        self, package_id: int, user_id: int
    ) -> Optional[ApplicationPackage]:
        """Fetch a package only if it belongs to ``user_id`` (else None)."""
        result = await self.db.execute(
            select(ApplicationPackage).where(
                ApplicationPackage.id == package_id,
                ApplicationPackage.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: int,
        page: int = 1,
        size: int = 20,
        offset: Optional[int] = None,
    ) -> tuple[list[ApplicationPackage], int]:
        total = await self.db.scalar(
            select(func.count())
            .select_from(ApplicationPackage)
            .where(ApplicationPackage.user_id == user_id)
        ) or 0
        result = await self.db.execute(
            select(ApplicationPackage)
            .where(ApplicationPackage.user_id == user_id)
            .order_by(ApplicationPackage.created_at.desc())
            .offset(offset if offset is not None else (page - 1) * size)
            .limit(size)
        )
        return list(result.scalars().all()), total

    async def update_sections(
        self, package_id: int, user_id: int, sections: list[dict]
    ) -> Optional[ApplicationPackage]:
        """Replace the stored sections (manual edits) for an owned package."""
        pkg = await self.get_owned(package_id, user_id)
        if not pkg:
            return None
        pkg.sections = sections
        await self.db.flush()
        await self.db.refresh(pkg)
        return pkg

    async def delete(self, package_id: int, user_id: int) -> bool:
        pkg = await self.get_owned(package_id, user_id)
        if not pkg:
            return False
        await self.db.delete(pkg)
        await self.db.flush()
        return True
