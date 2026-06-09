"""Map a detected form field to a profile key.

Strategy:
  1. Rule-based — fast, deterministic, handles the 90% of common fields.
  2. LLM fallback (Qwen3 via NVIDIA OpenAI-compatible endpoint) only when rules miss.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from openai import AsyncOpenAI

from config import get_settings
from filler.detector import FieldInfo
from storage.db import PROFILE_FIELDS

log = logging.getLogger(__name__)


# Each profile key → set of substrings/regex hints. Ordered: more specific first.
_RULES: dict[str, tuple[str, ...]] = {
    "email": ("email", "e-mail", "mail", "почт"),
    "phone": ("phone", "tel", "mobile", "whatsapp", "телефон", "номер"),
    "first_name": ("first name", "given name", "firstname", "имя"),
    "last_name": ("last name", "surname", "family name", "lastname", "фамил"),
    "full_name": ("full name", "your name", "fullname", "полное имя", "name"),
    "company": (
        "company",
        "organization",
        "organisation",
        "employer",
        "компания",
        "организац",
    ),
    "job_title": (
        "job title",
        "position",
        "role",
        "title",
        "должность",
        "job",
    ),
    "country": ("country", "страна"),
    "city": ("city", "town", "город"),
    "website": ("website", "site", "url", "homepage", "сайт"),
    "linkedin": ("linkedin",),
    "bio_short": ("bio", "about you", "about yourself", "о себе", "introduce"),
}

# Profile-key normalization for autocomplete attribute → profile key.
_AUTOCOMPLETE_MAP: dict[str, str] = {
    "email": "email",
    "name": "full_name",
    "given-name": "first_name",
    "family-name": "last_name",
    "tel": "phone",
    "tel-national": "phone",
    "organization": "company",
    "organization-title": "job_title",
    "country": "country",
    "country-name": "country",
    "address-level2": "city",
    "url": "website",
    "bday": None,  # explicitly not a profile field — skip
}


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _haystack(field: FieldInfo) -> str:
    return _normalize(
        " ".join(
            filter(None, [field.label, field.placeholder, field.name, field.id])
        )
    )


def rule_based_match(field: FieldInfo) -> str | None:
    """Return profile key if any rule matches, else None."""
    # HTML autocomplete is the most reliable signal when present.
    if field.autocomplete:
        ac = field.autocomplete.strip().lower()
        if ac in _AUTOCOMPLETE_MAP:
            return _AUTOCOMPLETE_MAP[ac]

    # Type-based shortcut for email/phone/url inputs.
    if field.type == "email":
        return "email"
    if field.type == "tel":
        return "phone"
    if field.type == "url":
        return "website"

    haystack = _haystack(field)
    if not haystack:
        return None

    for key, hints in _RULES.items():
        for hint in hints:
            if hint in haystack:
                return key
    return None


_LLM_PROMPT = """\
You map a single web-form field onto one of these user-profile keys, or to "none" if no key fits.

Profile keys (only these are valid):
{keys}

Respond with strict JSON: {{"profile_key": "<one_of_the_keys_or_none>"}}.

Field metadata:
- label: {label}
- placeholder: {placeholder}
- name attribute: {name}
- id attribute: {id}
- input type: {type}
- autocomplete: {autocomplete}
- options (if select/radio): {options}

Rules:
- Only return a key from the list above.
- If the field is asking for something not in the list (e.g. dietary, t-shirt size, custom question), return "none".
- If the field looks like a captcha/agreement/checkbox, return "none".
"""


async def llm_match(field: FieldInfo, keys: Iterable[str] = PROFILE_FIELDS) -> str | None:
    settings = get_settings()
    if not settings.nvidia_api_key and not settings.openai_api_key:
        return None

    base_url = settings.nvidia_base_url if settings.nvidia_api_key else None
    api_key = settings.nvidia_api_key or settings.openai_api_key
    model = settings.nvidia_model if settings.nvidia_api_key else "gpt-4o-mini"

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    prompt = _LLM_PROMPT.format(
        keys="\n".join(f"- {k}" for k in keys),
        label=field.label or "(none)",
        placeholder=field.placeholder or "(none)",
        name=field.name or "(none)",
        id=field.id or "(none)",
        type=field.type,
        autocomplete=field.autocomplete or "(none)",
        options=field.options or field.radio_group or "(none)",
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=60,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Tolerate extra text — find the first {...} block.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(0))
        key = data.get("profile_key")
        if isinstance(key, str) and key in keys:
            return key
        return None
    except Exception as exc:
        log.warning("LLM mapper failed for field %r: %s", field.display, exc)
        return None


async def map_field(field: FieldInfo) -> str | None:
    """Public entry point: try rules, then LLM."""
    rule = rule_based_match(field)
    if rule:
        return rule
    return await llm_match(field)
