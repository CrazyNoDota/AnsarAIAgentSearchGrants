from typing import Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """Ask the consultant a grounded question about a grant.

    At least one of ``grant_id`` / ``package_id`` should be supplied so the
    answer can be grounded; the knowledge base is searched automatically using
    the question text (user-scoped).
    """

    question: str = Field(min_length=1, max_length=2000)
    grant_id: Optional[int] = None
    # Optional owned package to also ground the answer in the applicant's draft.
    package_id: Optional[int] = None
    # Whether to also retrieve grounded precedent from the user's knowledge base.
    use_knowledge_base: bool = True


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    llm_used: bool
    sources: list[str] = []


class ReviewRequest(BaseModel):
    """Request a completeness/fit review + recommendations for an owned package."""

    package_id: int
    # When true, also use the source profile↔grant fit (Phase-2 matching) to
    # surface eligibility/fit gaps.
    include_fit: bool = True
    use_knowledge_base: bool = True


class SectionFinding(BaseModel):
    key: str
    title: str
    char_count: Optional[int] = None


class Assessment(BaseModel):
    package_title: str
    package_status: str
    section_count: int
    drafted_count: int
    percent_complete: int
    stage: str
    complete: bool
    missing_sections: list[dict] = []
    todo_sections: list[dict] = []
    weak_sections: list[dict] = []
    absent_required_sections: list[str] = []
    eligibility_gaps: list[str] = []
    fit_percent: Optional[int] = None


class ReviewResponse(BaseModel):
    assessment: Assessment
    recommendations: list[str]
    summary: str
    llm_used: bool
