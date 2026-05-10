from datetime import datetime
from pydantic import BaseModel


class ReviewCreate(BaseModel):
    decision: str  # "approved" or "rejected"
    reviewer_name: str = "staff"


class ReviewResponse(BaseModel):
    id: int
    grant_id: int
    reviewer_name: str
    decision: str
    created_at: datetime

    model_config = {"from_attributes": True}
