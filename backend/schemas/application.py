from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# Practical bounds so manual edits / generated content can't bloat the JSON
# column or make export rendering pathologically expensive.
MAX_SECTIONS = 50
MAX_SECTION_CHARS = 50_000


class ApplicationSection(BaseModel):
    key: str = Field(max_length=64)
    title: str = Field(max_length=256)
    content: str = Field(max_length=MAX_SECTION_CHARS)


class GenerateRequest(BaseModel):
    """Request to generate an application package for a (profile, grant) pair."""

    profile_id: int
    grant_id: int
    # Optional subset of section keys (see document_templates.SECTIONS_BY_KEY).
    # None → all default sections.
    sections: Optional[list[str]] = Field(default=None, max_length=MAX_SECTIONS)
    # Optional pre-extracted grant-call text (e.g. from /applications/extract)
    # to ground generation in the real call wording.
    extra_context: Optional[str] = Field(default=None, max_length=20000)


class ApplicationResponse(BaseModel):
    id: int
    user_id: int
    profile_id: Optional[int] = None
    grant_id: Optional[int] = None
    grant_title: Optional[str] = None
    title: str
    status: str
    sections: list[ApplicationSection]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApplicationUpdate(BaseModel):
    """Manual edits to a package's sections."""

    sections: list[ApplicationSection] = Field(max_length=MAX_SECTIONS)


class ExtractResponse(BaseModel):
    """Result of multimodal reading of an uploaded grant-call file."""

    text: Optional[str] = None
    pages_or_images: int = 0
    available: bool = True
