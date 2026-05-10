from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class GrantData:
    """Standardized grant data returned by all scrapers."""
    title: str
    source_url: str
    organization: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    deadline: Optional[date] = None


class BaseScraper(ABC):
    """Abstract base class for all grant scrapers."""

    name: str = "base"

    @abstractmethod
    async def scrape(self) -> list[GrantData]:
        """Run the scraper and return a list of GrantData objects."""
        ...

    def normalize_url(self, url: str, base: str = "") -> str:
        """Ensure URL is absolute."""
        if url.startswith("http"):
            return url
        return base.rstrip("/") + "/" + url.lstrip("/")
