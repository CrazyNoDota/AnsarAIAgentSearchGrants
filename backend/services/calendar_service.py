"""
Phase 4 — Calendar of active grants + application-prep readiness checklist.

Two capabilities, both built on existing Phase 1/3 data:

1. CALENDAR: a forward-looking view of active (approved) grants that have a
   deadline, bucketed by urgency. Reuses the same selection/urgency logic the
   /deadlines route already uses; this service exposes it as reusable, testable
   pure helpers (no DB) plus a user-scoped DB accessor.

2. READINESS CHECKLIST: for an application package (Phase 3 ``ApplicationPackage``)
   it reports, per section, whether the section is drafted, still a TODO/empty,
   and derives an overall prep stage + percent-complete. This is PURE over the
   package's stored ``sections`` JSON, so it is fully unit-testable and is the
   same regardless of who built the package — but every DB read of a package is
   USER-SCOPED via ``DocumentService.get_owned`` / ``list_for_user`` (Phase 2/3
   lesson: no unscoped accessor).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

# Markers that indicate a section is NOT yet really drafted.
_TODO_MARKERS = ("[todo", "[draft unavailable")


def urgency_for(days_left: int) -> str:
    """Bucket a day-count into an urgency label (matches /deadlines)."""
    if days_left <= 1:
        return "critical"
    if days_left <= 7:
        return "high"
    if days_left <= 14:
        return "medium"
    return "normal"


def days_left_for(deadline: date, today: Optional[date] = None) -> int:
    today = today or date.today()
    return (deadline - today).days


# ── Readiness checklist (pure over the stored sections JSON) ─────────────────

@dataclass(frozen=True)
class SectionStatus:
    key: str
    title: str
    drafted: bool  # has real (non-placeholder, non-empty) content
    has_todo: bool  # content still contains a [TODO ...] / draft-unavailable marker
    char_count: int

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "drafted": self.drafted,
            "has_todo": self.has_todo,
            "char_count": self.char_count,
        }


def _section_is_drafted(content: str) -> tuple[bool, bool]:
    """Return (drafted, has_todo) for one section's content string.

    `drafted` = there is substantive content AND no TODO/placeholder marker.
    `has_todo` = a TODO/draft-unavailable marker is present.
    Empty/whitespace-only content is neither drafted nor a TODO (it is "missing").
    """
    text = (content or "").strip()
    if not text:
        return False, False
    low = text.lower()
    has_todo = any(m in low for m in _TODO_MARKERS)
    drafted = not has_todo
    return drafted, has_todo


def evaluate_sections(sections: list[dict]) -> list[SectionStatus]:
    """Per-section readiness over a package's stored ``sections`` JSON. Pure."""
    out: list[SectionStatus] = []
    for s in sections or []:
        content = s.get("content", "") if isinstance(s, dict) else ""
        drafted, has_todo = _section_is_drafted(content)
        out.append(
            SectionStatus(
                key=str(s.get("key", "")) if isinstance(s, dict) else "",
                title=str(s.get("title", "")) if isinstance(s, dict) else "",
                drafted=drafted,
                has_todo=has_todo,
                char_count=len((content or "").strip()),
            )
        )
    return out


def prep_stage(total: int, drafted: int) -> str:
    """Coarse prep stage from drafted/total counts."""
    if total == 0:
        return "not_started"
    if drafted == 0:
        return "not_started"
    if drafted < total:
        return "in_progress"
    return "ready"


def build_readiness(
    *,
    package_id: int,
    title: str,
    status: str,
    grant_id: Optional[int],
    grant_title: Optional[str],
    sections: list[dict],
    deadline: Optional[date] = None,
    today: Optional[date] = None,
) -> dict:
    """Build the full readiness checklist for one package. Pure / testable.

    ``deadline`` (the grant's deadline, if known) lets the checklist surface time
    pressure alongside completion. Does NOT read the DB — the caller resolves the
    package + grant deadline (user-scoped) and passes them in.
    """
    sec_statuses = evaluate_sections(sections)
    total = len(sec_statuses)
    drafted = sum(1 for s in sec_statuses if s.drafted)
    todo = sum(1 for s in sec_statuses if s.has_todo)
    missing = sum(1 for s in sec_statuses if not s.drafted and not s.has_todo)
    pct = round(100 * drafted / total) if total else 0

    result: dict = {
        "package_id": package_id,
        "title": title,
        "status": status,
        "grant_id": grant_id,
        "grant_title": grant_title,
        "stage": prep_stage(total, drafted),
        "percent_complete": pct,
        "section_count": total,
        "drafted_count": drafted,
        "todo_count": todo,
        "missing_count": missing,
        "sections": [s.as_dict() for s in sec_statuses],
    }
    if deadline is not None:
        dl = days_left_for(deadline, today)
        result["deadline"] = str(deadline)
        result["days_left"] = dl
        result["urgency"] = urgency_for(dl) if dl >= 0 else "passed"
    else:
        result["deadline"] = None
        result["days_left"] = None
        result["urgency"] = None
    return result


# ── Calendar event shaping (pure) ────────────────────────────────────────────

def grant_to_calendar_event(grant, today: Optional[date] = None) -> dict:
    """Shape a Grant row into a calendar event dict. Pure (no DB)."""
    today = today or date.today()
    dl = days_left_for(grant.deadline, today)
    return {
        "grant_id": grant.id,
        "title": grant.title,
        "deadline": str(grant.deadline),
        "days_left": dl,
        "urgency": urgency_for(dl),
        "organization": getattr(grant, "organization", None),
        "source_url": getattr(grant, "source_url", None),
        "application_url": getattr(grant, "application_url", None),
    }


def bucket_by_urgency(events: list[dict]) -> dict:
    """Group calendar events into urgency buckets (pure)."""
    buckets: dict[str, list[dict]] = {
        "critical": [], "high": [], "medium": [], "normal": []
    }
    for e in events:
        buckets.setdefault(e.get("urgency", "normal"), []).append(e)
    return buckets
