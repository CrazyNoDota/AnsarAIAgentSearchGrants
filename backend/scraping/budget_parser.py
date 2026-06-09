"""
Budget / amount parsing helpers (Phase 1).

Turns free-text funding strings ("Up to $50,000", "€100K-€500K", "GBP 2 million")
into normalized (budget_min, budget_max, currency) so grants can be filtered by
budget. Pure-python, no network — safe to unit-test offline.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

_CURRENCY_SYMBOLS = {
    "$": "USD", "US$": "USD", "usd": "USD",
    "€": "EUR", "eur": "EUR",
    "£": "GBP", "gbp": "GBP",
    "¥": "JPY", "jpy": "JPY",
    "chf": "CHF",
}

_MULTIPLIERS = {
    "k": 1_000, "thousand": 1_000,
    "m": 1_000_000, "mn": 1_000_000, "million": 1_000_000,
    "b": 1_000_000_000, "bn": 1_000_000_000, "billion": 1_000_000_000,
}

# A number optionally followed by a k/m/b style suffix.
_AMOUNT_RE = re.compile(
    r"([\d][\d,\.]*)\s*(k|m|mn|b|bn|thousand|million|billion)?",
    re.IGNORECASE,
)


def _detect_currency(text: str) -> Optional[str]:
    low = text.lower()
    for sym, code in _CURRENCY_SYMBOLS.items():
        if sym in text or sym in low:
            return code
    return None


def _to_number(num: str, suffix: Optional[str]) -> Optional[float]:
    try:
        val = float(num.replace(",", ""))
    except ValueError:
        return None
    if suffix:
        val *= _MULTIPLIERS.get(suffix.lower(), 1)
    return val


def parse_budget(text: Optional[str]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Return (budget_min, budget_max, currency) from a free-text amount string.

    Examples:
        "Up to $50,000"   -> (None, 50000.0, "USD")
        "€100K-€500K"     -> (100000.0, 500000.0, "EUR")
        "GBP 2 million"   -> (2000000.0, 2000000.0, "GBP")
        "" / None         -> (None, None, None)
    """
    if not text:
        return None, None, None
    text = str(text)
    currency = _detect_currency(text)

    amounts = []
    for m in _AMOUNT_RE.finditer(text):
        num = _to_number(m.group(1), m.group(2))
        # Ignore bare years (e.g. "2026") with no currency/suffix context.
        if num is None:
            continue
        if num >= 1900 and num <= 2100 and not m.group(2) and currency is None:
            continue
        amounts.append(num)

    if not amounts:
        return None, None, currency

    low = text.lower()
    if len(amounts) == 1:
        val = amounts[0]
        if any(w in low for w in ("up to", "maximum", "max", "no more than")):
            return None, val, currency
        if any(w in low for w in ("from", "minimum", "min", "at least", "starting")):
            return val, None, currency
        return val, val, currency

    return min(amounts), max(amounts), currency
