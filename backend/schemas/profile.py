from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ProfileBase(BaseModel):
    name: str
    industry: Optional[str] = None
    stage: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    funding_amount_sought: Optional[float] = None
    currency: Optional[str] = None
    team_size: Optional[int] = None
    organization_type: Optional[str] = None
    keywords: Optional[str] = None
    description: Optional[str] = None
    past_funding: Optional[float] = None


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    stage: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    funding_amount_sought: Optional[float] = None
    currency: Optional[str] = None
    team_size: Optional[int] = None
    organization_type: Optional[str] = None
    keywords: Optional[str] = None
    description: Optional[str] = None
    past_funding: Optional[float] = None


class ProfileResponse(ProfileBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Fit / match result schemas ────────────────────────────────────────────

class FitFeatureBreakdown(BaseModel):
    """Per-dimension scores that feed the deterministic overall fit score.

    Each value is in [0, 1]. `weight` is the weight applied to that dimension
    in the weighted-average formula (see matching_service.SCORING_WEIGHTS).
    """
    industry: float
    region: float
    budget: float
    deadline: float
    stage: float
    semantic: float
    weights: dict


class FitResult(BaseModel):
    grant_id: int
    grant_title: str
    # Deterministic overall fit score / pass-probability in [0, 1].
    fit_score: float
    probability_pct: int
    strengths: list[str]
    weaknesses: list[str]
    explanation: str
    breakdown: FitFeatureBreakdown


class FitRecommendation(FitResult):
    """A grant in a ranked recommendation list for a profile."""
    source_url: Optional[str] = None
    organization: Optional[str] = None
    deadline: Optional[str] = None
    grant_amount: Optional[str] = None
