from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class GrantBase(BaseModel):
    title: str
    description: Optional[str] = None
    organization: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    deadline: Optional[date] = None
    source_url: str
    grant_amount: Optional[str] = None
    eligibility: Optional[str] = None
    industry: Optional[str] = None
    startup_stage: Optional[str] = None
    application_url: Optional[str] = None
    # Phase 1 structured filter fields
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    currency: Optional[str] = None
    region: Optional[str] = None


class GrantCreate(GrantBase):
    pass


class GrantUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    organization: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    deadline: Optional[date] = None
    status: Optional[str] = None
    grant_amount: Optional[str] = None
    eligibility: Optional[str] = None
    industry: Optional[str] = None
    startup_stage: Optional[str] = None
    application_url: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    currency: Optional[str] = None
    region: Optional[str] = None


class GrantResponse(GrantBase):
    id: int
    status: str
    ai_score: float
    confidence_score: float = 0.85
    embedding_status: str = "pending"
    telegram_msg_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GrantListResponse(BaseModel):
    items: list[GrantResponse]
    total: int
    page: int
    size: int
