"""
Phase 3 — Application document section templates.

A grant application "package" is assembled from a fixed, ordered set of sections
(Executive Summary, Project Description, Objectives & KPIs, Budget, ...). Each
section is described declaratively here so the generator, the API and the tests
all agree on the structure and so sections can be selected/extended without
touching generation logic.

The `guidance` text is the per-section instruction handed to the LLM. It must
NEVER ask the model to invent facts — the document generator's system prompt
forbids invention and the guidance only describes *what to write* and *which
provided facts to draw on* (see services/document_service.py).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectionTemplate:
    """One section of a generated grant-application package.

    key:        stable identifier (used in the stored JSON + API).
    title:      human heading rendered in the exported document.
    order:      sort order within the package.
    guidance:   instruction to the LLM for this section (no invention).
    max_tokens: generation budget for this section.
    """

    key: str
    title: str
    order: int
    guidance: str
    max_tokens: int = 700


# Core sections from the Phase 3 plan: Executive Summary, project description,
# KPI/goals/results, budget. Two further commonly-required sections (team and
# sustainability) round out a fundable package; callers may select a subset.
DEFAULT_SECTIONS: tuple[SectionTemplate, ...] = (
    SectionTemplate(
        key="executive_summary",
        title="Executive Summary",
        order=10,
        guidance=(
            "Write a concise executive summary (around 150-220 words) that states "
            "what the project is, the problem it solves, who the applicant is, the "
            "funding requested, and why this project fits this specific grant. Draw "
            "the applicant facts ONLY from the company profile and the funding "
            "amount/eligibility ONLY from the grant details."
        ),
        max_tokens=500,
    ),
    SectionTemplate(
        key="project_description",
        title="Project Description",
        order=20,
        guidance=(
            "Describe the project in detail: background and problem statement, the "
            "proposed solution/approach, target beneficiaries, and how the work "
            "aligns with this grant's stated themes, eligibility and priorities. "
            "Use the company profile for the applicant's domain, stage and team, "
            "and the grant details for the funder's priorities. Do not fabricate "
            "partners, results or metrics that are not provided."
        ),
        max_tokens=900,
    ),
    SectionTemplate(
        key="objectives_kpis",
        title="Objectives, Goals & KPIs",
        order=30,
        guidance=(
            "List 3-5 SMART objectives and, for each, concrete measurable KPIs and "
            "expected results/outcomes. Present them as a clear bulleted or numbered "
            "list. KPIs must be realistic for the applicant's stage as given in the "
            "profile; where a baseline or target value is unknown, insert a clearly "
            "marked placeholder rather than inventing a number."
        ),
        max_tokens=700,
    ),
    SectionTemplate(
        key="budget",
        title="Budget & Justification",
        order=40,
        guidance=(
            "Provide a high-level budget breakdown and justification for the "
            "requested funding. Anchor the total on the funding amount the applicant "
            "is seeking (from the profile) and keep it within the grant's funding "
            "range when one is given. Break the total into sensible categories "
            "(e.g. personnel, equipment, operations, dissemination) with short "
            "justifications. Use placeholders like \"[TODO: confirm amount]\" for "
            "figures that are not provided; never invent precise costs."
        ),
        max_tokens=800,
    ),
    SectionTemplate(
        key="team",
        title="Team & Organizational Capacity",
        order=50,
        guidance=(
            "Summarise the applicant's capacity to deliver: organization type, "
            "team size, stage and any relevant experience, all taken from the "
            "company profile. If specific roles or named team members are not "
            "provided, describe the capability in general terms with placeholders "
            "instead of inventing individuals."
        ),
        max_tokens=500,
    ),
    SectionTemplate(
        key="sustainability",
        title="Sustainability & Impact",
        order=60,
        guidance=(
            "Explain the longer-term impact and how outcomes will be sustained "
            "after the grant ends (e.g. revenue model, follow-on funding, "
            "partnerships, scale-up). Ground this in the applicant's profile and "
            "the grant's goals; mark any unknowns as placeholders."
        ),
        max_tokens=500,
    ),
)

# Index by key for O(1) selection/validation.
SECTIONS_BY_KEY: dict[str, SectionTemplate] = {s.key: s for s in DEFAULT_SECTIONS}


def get_sections(keys: list[str] | None = None) -> list[SectionTemplate]:
    """Return the requested section templates in canonical order.

    `keys=None` → all default sections. Unknown keys raise ValueError so the API
    can return a clean 400 instead of silently dropping a requested section.
    """
    if keys is None:
        return sorted(DEFAULT_SECTIONS, key=lambda s: s.order)
    unknown = [k for k in keys if k not in SECTIONS_BY_KEY]
    if unknown:
        raise ValueError(f"Unknown section key(s): {', '.join(unknown)}")
    # De-duplicate while preserving canonical (order) sorting.
    chosen = {SECTIONS_BY_KEY[k] for k in keys}
    return sorted(chosen, key=lambda s: s.order)
