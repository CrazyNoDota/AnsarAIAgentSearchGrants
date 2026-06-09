"""
Offline tests for the natural-language intent router (handlers/nlu.py).

Pure-Python (no aiogram / network), so it runs standalone:
    python bot/tests/test_nlu.py
"""
import importlib.util
import pathlib

_NLU = pathlib.Path(__file__).resolve().parents[1] / "handlers" / "nlu.py"
_spec = importlib.util.spec_from_file_location("nlu", _NLU)
nlu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nlu)
detect_intent = nlu.detect_intent

# (message, expected_intent) — expected None means "fall through to RAG search".
CASES = [
    ("на какие гранты скоро истекает срок", "deadlines"),
    ("какие гранты скоро истекают", "deadlines"),
    ("горящие дедлайны", "deadlines"),
    ("show deadlines", "deadlines"),
    ("покажи новые гранты", "pending"),
    ("что нового?", "pending"),
    ("гранты на рассмотрении", "pending"),
    ("одобренные гранты", "approved"),
    ("покажи отклонённые", "rejected"),
    ("статистика", "stats"),
    ("сколько всего грантов", "stats"),
    ("что ты узнал обо мне", "insights"),
    ("чему ты научился", "insights"),
    ("мои источники", "sources"),
    ("список источников", "sources"),
    ("запусти сбор грантов", "scrape"),
    ("обнови гранты", "scrape"),
    ("помощь", "help"),
    ("какие есть команды", "help"),
    ("как это работает", "guide"),
    ("что ты умеешь", "guide"),
    ("добавь источник https://astanahub.com/grants", "addsource"),
    ("add source https://example.org/funding", "addsource"),
    # Search-style queries MUST fall through to RAG (None):
    ("найди гранты связанные с туризмом в казахстане", None),
    ("гранты для ИИ-стартапов", None),
    ("есть ли финансирование для НКО", None),
    ("гранты по туризму", None),
    ("", None),
    ("привет", None),
]


def test_intents():
    failures = []
    for text, expected in CASES:
        result = detect_intent(text)
        got = result[0] if result else None
        if got != expected:
            failures.append((text, expected, result))
    assert not failures, "intent mismatches: " + repr(failures)


def test_addsource_extracts_url():
    # Trailing punctuation must be stripped from the captured URL.
    result = detect_intent("добавь источник https://astanahub.com/grants .")
    assert result == ("addsource", "https://astanahub.com/grants"), result
    # "add source" without a URL is NOT an addsource intent.
    assert detect_intent("добавь источник") != ("addsource", None)


if __name__ == "__main__":
    test_intents()
    test_addsource_extracts_url()
    print(f"OK — {len(CASES)} intent cases + addsource extraction passed")
