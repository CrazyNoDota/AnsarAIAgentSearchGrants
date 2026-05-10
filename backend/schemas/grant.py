from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, HttpUrl


class GrantBase(BaseModel):
    title: str
    description: Optional[str] = None
    organization: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    deadline: Optional[date] = None
    source_url: str


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


class GrantResponse(GrantBase):
    id: int
    status: str
    ai_score: float
    telegram_msg_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GrantListResponse(BaseModel):
    items: list[GrantResponse]
    total: int
    page: int
    size: int
