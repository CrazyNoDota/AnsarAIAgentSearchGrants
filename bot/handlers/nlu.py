"""
Natural-language intent detection for plain-text messages (Russian + English).

Lets users type ordinary phrases instead of slash commands — e.g.
"какие гранты скоро истекают", "покажи новые гранты", "статистика",
"show my sources", "добавь источник https://...". Used by the free-form chat
fallback (handlers/chat.py): if a clear *action* intent is detected the message
is dispatched to the matching command handler; otherwise it falls through to the
RAG grant search (the default).

Search-style questions ("найди гранты по туризму в Казахстане") are intentionally
NOT intercepted — they go to RAG, which returns a grounded AI answer + grant
cards. So the rules below aim for action intents only and stay conservative to
avoid hijacking genuine search queries.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# Ordered list of (intent, [regex patterns]). Patterns are matched
# case-insensitively against the lowercased message; the FIRST intent with any
# matching pattern wins, so more specific intents come earlier.
INTENT_RULES: list[tuple[str, list[str]]] = [
    ("guide", [
        r"как (это |всё |все |тут |здесь |мне )?(всё |все )?работает",
        r"что (ты |этот бот |бот )?умеет",
        r"что ты умеешь",
        r"с чего нач",
        r"как (мне )?(тут |этим )?польз",
        r"\bguide\b",
        r"how (do|does|to) .*(work|use)",
        r"getting started",
    ]),
    ("help", [
        r"помощ",
        r"справк",
        r"список команд",
        r"какие (есть )?команд",
        r"\bhelp\b",
        r"\bcommands?\b",
    ]),
    ("deadlines", [
        r"дедлайн",
        r"истека",
        r"сроки?\b.*(подач|истек|заканч|закры)",
        r"скоро\b.*(истек|заканч|закро|закры)",
        r"горящ",
        r"\bdeadlines?\b",
        r"\bexpir",
        r"due soon",
        r"closing soon",
    ]),
    ("pending", [
        r"нов(ые|ых|ое|еньк)\w*\W{0,4}грант",
        r"грант\w*\W{0,4}нов(ые|ых)",
        r"что нового",
        r"на рассмотр",
        r"на проверк",
        r"непросмотр",
        r"свеж\w*\W{0,4}грант",
        r"\bpending\b",
        r"new grants?",
    ]),
    ("approved", [
        r"одобрен\w*\W{0,6}грант",
        r"грант\w*\W{0,6}одобрен",
        r"принят\w*\W{0,4}грант",
        r"approved grants?",
    ]),
    ("rejected", [
        r"отклон[её]нн?",
        r"отказан\w*\W{0,6}грант",
        r"rejected grants?",
    ]),
    ("stats", [
        r"статистик",
        r"сколько (всего )?грантов",
        r"\bstats?\b",
        r"\bstatistics\b",
        r"сводк\w*\W{0,4}баз",
    ]),
    ("insights", [
        r"что (ты )?(узнал|понял|выучил)",
        r"чему (ты )?научил",
        r"мои предпочтени",
        r"\binsights?\b",
        r"\bpreferences\b",
    ]),
    ("sources", [
        r"(список|мои|какие|показ\w*|покаж\w*|все)\W{0,3}источник",
        r"источник\w*\W{0,4}(список|есть|добавл)",
        r"^источники\b",
        r"list sources",
        r"show .*sources",
        r"my sources",
    ]),
    ("scrape", [
        r"запусти\w*\W{0,12}(сбор|скан|парс)",
        r"обнови\w*\W{0,12}(грант|баз)",
        r"собери\w*\W{0,12}грант",
        r"просканир",
        r"run (a )?scrape",
        r"scrape now",
        r"refresh grants",
    ]),
]

_COMPILED = [
    (intent, [re.compile(p, re.IGNORECASE) for p in pats])
    for intent, pats in INTENT_RULES
]

# "add a source" needs a URL in the message; detected before the generic rules.
_ADD_VERB = re.compile(r"(добав|регистр|подключ|\badd\b|register)", re.IGNORECASE)
_ADD_NOUN = re.compile(r"(источник|ресурс|\bsource\b|\burl\b|сайт)", re.IGNORECASE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def detect_intent(text: str) -> Optional[Tuple[str, Optional[str]]]:
    """Classify a plain-text message into an action intent.

    Returns ``(intent, arg)`` where ``arg`` is currently only used by the
    ``addsource`` intent (the extracted URL); ``None`` for all others.
    Returns ``None`` (the whole result) when no action intent matches — the
    caller should then treat the text as a RAG search query.
    """
    raw = text or ""
    t = raw.strip().lower()
    if not t:
        return None

    # "добавь источник <url>" / "add source <url>" — requires an explicit URL.
    if _ADD_VERB.search(t) and _ADD_NOUN.search(t):
        m = _URL.search(raw)
        if m:
            return ("addsource", m.group(0).rstrip(".,;)]}»\"'"))

    for intent, patterns in _COMPILED:
        if any(p.search(t) for p in patterns):
            return (intent, None)
    return None
