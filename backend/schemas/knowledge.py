from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


MAX_TITLE = 512
MAX_CONTENT = 100_000


class KnowledgeCreate(BaseModel):
    """Create a knowledge-base entry."""

    kind: str = Field(description="past_application | successful_case | template | submission")
    title: str = Field(max_length=MAX_TITLE)
    content: str = Field(default="", max_length=MAX_CONTENT)
    outcome: Optional[str] = Field(
        default=None, description="won | rejected | submitted | pending | withdrawn"
    )
    package_id: Optional[int] = None
    grant_id: Optional[int] = None
    funder: Optional[str] = Field(default=None, max_length=MAX_TITLE)
    meta: Optional[dict] = None


class KnowledgeUpdate(BaseModel):
    """Partial update of a knowledge-base entry (owner only)."""

    kind: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=MAX_TITLE)
    content: Optional[str] = Field(default=None, max_length=MAX_CONTENT)
    outcome: Optional[str] = None
    funder: Optional[str] = Field(default=None, max_length=MAX_TITLE)
    meta: Optional[dict] = None


class KnowledgeResponse(BaseModel):
    id: int
    user_id: int
    kind: str
    title: str
    content: str
    outcome: Optional[str] = None
    package_id: Optional[int] = None
    grant_id: Optional[int] = None
    funder: Optional[str] = None
    meta: dict = {}
    embedding_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeSearchResult(BaseModel):
    id: int
    kind: str
    title: str
    outcome: Optional[str] = None
    funder: Optional[str] = None
    grant_id: Optional[int] = None
    package_id: Optional[int] = None
    similarity_score: Optional[float] = None
