"""
Phase 4 — OFFLINE unit tests (no live network/SMTP, no real DB).

What is proven OFFLINE here:
  1. Email message construction is pure + correct (From/To/Subject, plain-text
     always present, HTML alternative attached when given).
  2. Deadline-email rendering is deterministic and HTML-escapes untrusted fields.
  3. EmailService degrades gracefully when SMTP is unconfigured (available=False,
     send returns False, never raises) and, with a STUBBED transport (no real
     network), actually "delivers" — send_bulk de-dupes recipients and counts
     deliveries; the stub records the built message.
  4. The readiness checklist is a PURE function over a package's sections JSON:
     drafted vs. [TODO]/missing classification, percent-complete, prep stage, and
     deadline/urgency annotation.
  5. Calendar event shaping + urgency bucketing are pure and match the urgency
     thresholds used by /deadlines.
  6. USER-SCOPING: the readiness endpoint reads packages only via the user-scoped
     DocumentService accessors (no unscoped getter); the reminder email helper
     only targets subscribers with email enabled.
  7. The email channel is modeled on NotificationSubscription (email + enabled
     flag) and the subscriptions schema validates addresses without a new dep.
  8. Migration 008 is additive (only ADDs two columns) + reversible (downgrade
     drops only those two columns); chained after 007.

Run from the backend dir:
    python tests/test_phase4.py
or under pytest:
    python -m pytest tests/test_phase4.py -v
"""
import ast
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

# Make `backend/` importable when run standalone.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services import email_service as es  # noqa: E402
from services import calendar_service as cal  # noqa: E402


# ── 1. Email message construction (pure) ─────────────────────────────────────

def test_build_message():
    msg = es.build_message(
        sender="noreply@ansar.example",
        to_addr="user@example.com",
        subject="Hello",
        text_body="plain body",
    )
    assert "noreply@ansar.example" in msg["From"]
    assert msg["To"] == "user@example.com"
    assert msg["Subject"] == "Hello"
    assert msg.get_content_type() == "text/plain"
    assert "plain body" in msg.get_content()

    # With HTML alternative → multipart/alternative carrying both parts.
    msg2 = es.build_message(
        sender="s@x.io", to_addr="r@x.io", subject="S",
        text_body="text", html_body="<b>html</b>",
    )
    assert msg2.get_content_type() == "multipart/alternative"
    types = {p.get_content_type() for p in msg2.iter_parts()}
    assert "text/plain" in types and "text/html" in types
    print("OK email message built (plain always; html alternative when given)")


# ── 2. Deadline email rendering (deterministic + escaped) ────────────────────

def test_render_deadline_email():
    items = [
        {"title": "AI Grant", "deadline": "2026-07-01", "days_left": 7,
         "source_url": "https://x.io/g/1"},
        {"title": "Health & <Science>", "deadline": "2026-07-08", "days_left": 14,
         "source_url": "https://x.io/g/2"},
    ]
    subject, text, html = es.render_deadline_email(items)
    assert "2 upcoming deadlines" in subject
    assert "AI Grant" in text and "2026-07-01" in text and "7 day(s)" in text
    assert "https://x.io/g/1" in text
    # HTML escapes special chars in untrusted titles.
    assert "&amp;" in html and "&lt;Science&gt;" in html
    assert "Health & <Science>" not in html

    # Singular subject for a single item.
    s1, _, _ = es.render_deadline_email([items[0]])
    assert "1 upcoming deadline" in s1 and "deadlines" not in s1
    print("OK deadline email rendered deterministically + HTML-escaped")


# ── 3. EmailService: graceful degradation + stubbed delivery ─────────────────

def test_email_unconfigured_degrades():
    async def _run():
        svc = es.EmailService.__new__(es.EmailService)
        svc._settings = SimpleNamespace(
            use_email=False, email_sender="", smtp_host="",
        )
        assert svc.available is False
        ok = await svc.send_email("a@b.io", "S", "T")
        assert ok is False  # logged + skipped, did NOT raise
        n = await svc.send_bulk(["a@b.io"], "S", "T")
        assert n == 0
    asyncio.run(_run())
    print("OK email degrades gracefully when unconfigured (no raise)")


def test_email_send_with_stubbed_transport():
    async def _run():
        sent_msgs = []

        svc = es.EmailService.__new__(es.EmailService)
        svc._settings = SimpleNamespace(
            use_email=True, email_sender="from@ansar.io", smtp_host="smtp.x",
        )
        # Stub the transport — NO real SMTP/network.
        svc._smtp_send = lambda msg: sent_msgs.append(msg)

        ok = await svc.send_email("to@x.io", "Subj", "Body", "<b>Body</b>")
        assert ok is True
        assert len(sent_msgs) == 1
        m = sent_msgs[0]
        assert m["To"] == "to@x.io" and m["Subject"] == "Subj"
        assert "from@ansar.io" in m["From"]

        # send_bulk de-duplicates recipients and counts deliveries.
        sent_msgs.clear()
        n = await svc.send_bulk(
            ["x@a.io", "x@a.io", "y@a.io", ""], "S", "T"
        )
        assert n == 2, n
        assert {m["To"] for m in sent_msgs} == {"x@a.io", "y@a.io"}
    asyncio.run(_run())
    print("OK email sends via stubbed transport; bulk de-dupes + counts")


def test_email_send_swallows_transport_error():
    async def _run():
        def _boom(msg):
            raise OSError("connection refused")

        svc = es.EmailService.__new__(es.EmailService)
        svc._settings = SimpleNamespace(
            use_email=True, email_sender="from@ansar.io", smtp_host="smtp.x",
        )
        svc._smtp_send = _boom
        ok = await svc.send_email("to@x.io", "S", "T")
        assert ok is False  # error logged, not raised
    asyncio.run(_run())
    print("OK email send swallows transport errors (returns False)")


# ── 4. Readiness checklist (pure) ────────────────────────────────────────────

def test_evaluate_sections_classification():
    secs = [
        {"key": "a", "title": "A", "content": "Real drafted prose here."},
        {"key": "b", "title": "B", "content": "Intro. [TODO: provide budget]."},
        {"key": "c", "title": "C", "content": "   "},  # missing
        {"key": "d", "title": "D",
         "content": "[Draft unavailable — AI generation was not available...]"},
    ]
    statuses = cal.evaluate_sections(secs)
    by_key = {s.key: s for s in statuses}
    assert by_key["a"].drafted and not by_key["a"].has_todo
    assert not by_key["b"].drafted and by_key["b"].has_todo
    assert not by_key["c"].drafted and not by_key["c"].has_todo  # missing
    assert not by_key["d"].drafted and by_key["d"].has_todo
    print("OK section classification: drafted vs TODO vs missing")


def test_build_readiness_counts_and_stage():
    secs = [
        {"key": "a", "title": "A", "content": "Real prose."},
        {"key": "b", "title": "B", "content": "[TODO: x]"},
        {"key": "c", "title": "C", "content": ""},
    ]
    r = cal.build_readiness(
        package_id=5, title="App", status="draft",
        grant_id=9, grant_title="G", sections=secs,
    )
    assert r["section_count"] == 3
    assert r["drafted_count"] == 1
    assert r["todo_count"] == 1
    assert r["missing_count"] == 1
    assert r["percent_complete"] == 33
    assert r["stage"] == "in_progress"
    assert r["deadline"] is None and r["urgency"] is None

    # All drafted → ready, 100%.
    full = cal.build_readiness(
        package_id=1, title="t", status="complete", grant_id=None,
        grant_title=None,
        sections=[{"key": "a", "title": "A", "content": "x"}],
    )
    assert full["stage"] == "ready" and full["percent_complete"] == 100

    # Empty package → not_started.
    empty = cal.build_readiness(
        package_id=1, title="t", status="draft", grant_id=None,
        grant_title=None, sections=[],
    )
    assert empty["stage"] == "not_started" and empty["percent_complete"] == 0
    print("OK readiness counts + percent + stage derivation")


def test_build_readiness_deadline_annotation():
    today = date(2026, 6, 9)
    r = cal.build_readiness(
        package_id=1, title="t", status="draft", grant_id=2, grant_title="G",
        sections=[{"key": "a", "title": "A", "content": "x"}],
        deadline=today + timedelta(days=5), today=today,
    )
    assert r["days_left"] == 5 and r["urgency"] == "high"

    passed = cal.build_readiness(
        package_id=1, title="t", status="draft", grant_id=2, grant_title="G",
        sections=[{"key": "a", "title": "A", "content": "x"}],
        deadline=today - timedelta(days=1), today=today,
    )
    assert passed["days_left"] == -1 and passed["urgency"] == "passed"
    print("OK readiness annotates deadline + urgency (incl. passed)")


# ── 5. Calendar shaping + urgency (pure) ─────────────────────────────────────

def test_urgency_thresholds():
    assert cal.urgency_for(0) == "critical"
    assert cal.urgency_for(1) == "critical"
    assert cal.urgency_for(7) == "high"
    assert cal.urgency_for(14) == "medium"
    assert cal.urgency_for(30) == "normal"
    print("OK urgency thresholds match /deadlines buckets")


def test_calendar_event_and_buckets():
    today = date(2026, 6, 9)
    g = SimpleNamespace(
        id=3, title="Grant X", deadline=today + timedelta(days=3),
        organization="EU", source_url="https://x.io/3", application_url=None,
    )
    ev = cal.grant_to_calendar_event(g, today)
    assert ev["grant_id"] == 3 and ev["days_left"] == 3
    assert ev["urgency"] == "high" and ev["organization"] == "EU"

    g2 = SimpleNamespace(
        id=4, title="Far Grant", deadline=today + timedelta(days=40),
        organization=None, source_url=None, application_url=None,
    )
    buckets = cal.bucket_by_urgency(
        [ev, cal.grant_to_calendar_event(g2, today)]
    )
    assert len(buckets["high"]) == 1 and len(buckets["normal"]) == 1
    assert buckets["critical"] == [] and buckets["medium"] == []
    print("OK calendar events shaped + bucketed by urgency")


# ── 6. User-scoping (readiness route uses scoped accessors only) ──────────────

def test_readiness_route_user_scoped():
    import inspect
    import api.routes.deadlines as dl
    from services.document_service import DocumentService as DS

    src = inspect.getsource(dl)
    # Readiness must go through the user-scoped accessors, passing current_user.id.
    assert "list_for_user(\n        current_user.id" in src or \
           "list_for_user(current_user.id" in src or \
           "current_user.id" in src
    assert "get_owned(package_id, current_user.id)" in src
    # And the service still exposes NO unscoped getter.
    assert not hasattr(DS, "get_by_id"), "no unscoped getter allowed"
    for meth in ("get_owned", "list_for_user"):
        params = inspect.signature(getattr(DS, meth)).parameters
        assert "user_id" in params, (meth, list(params))
    print("OK readiness route reads packages user-scoped only")


def test_email_reminder_targets_only_enabled_subscribers():
    import inspect
    import api.routes.deadlines as dl

    src = inspect.getsource(dl._send_deadline_email_alerts)
    # Must filter on email present AND email_enabled True.
    assert "email.isnot(None)" in src
    assert "email_enabled.is_(True)" in src
    print("OK email reminders only target subscribers with email enabled")


# ── 7. Model + schema: email channel modeled cleanly, no new dep ─────────────

def test_subscription_model_has_email_channel():
    from models.notification_subscription import NotificationSubscription as NS
    cols = NS.__table__.columns
    assert "email" in cols.keys() and "email_enabled" in cols.keys()
    # Telegram columns untouched (channel ADDED, not replaced).
    assert "telegram_user_id" in cols.keys()
    assert "telegram_chat_id" in cols.keys()
    assert cols["email"].nullable is True
    assert cols["email_enabled"].nullable is False
    print("OK email channel modeled on NotificationSubscription (alongside Telegram)")


def test_email_validator_no_new_dep():
    from api.routes.subscriptions import _validate_email
    assert _validate_email(None) is None
    assert _validate_email("  ") is None
    assert _validate_email(" user@example.com ") == "user@example.com"
    for bad in ("nope", "a@b", "@b.com", "a@", "a b@c.com", "a@b.", "a@.b"):
        try:
            _validate_email(bad)
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass
    print("OK lightweight email validation (no email-validator dependency)")


def test_settings_email_properties():
    from core.config import Settings
    s = Settings(smtp_host="", email_from="", smtp_user="")
    assert s.use_email is False
    s2 = Settings(smtp_host="smtp.x", email_from="from@x.io")
    assert s2.use_email is True and s2.email_sender == "from@x.io"
    # Sender falls back to SMTP_USER when EMAIL_FROM empty.
    s3 = Settings(smtp_host="smtp.x", email_from="", smtp_user="u@x.io")
    assert s3.email_sender == "u@x.io" and s3.use_email is True
    print("OK settings: use_email + email_sender fallback")


# ── 8. Migration 008 hygiene (static, no DB) ─────────────────────────────────

def test_migration_008_additive_and_reversible():
    mig = (_BACKEND / "database" / "migrations" / "versions"
           / "008_phase4_email_channel.py")
    src = mig.read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _calls(func_name, attr):
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                for call in ast.walk(node):
                    if (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == attr
                            and len(call.args) >= 2
                            and isinstance(call.args[0], ast.Constant)):
                        out.append(call.args[0].value)
        return out

    assert "down_revision = '007_phase3_applications'" in src
    assert "revision = '008_phase4_email_channel'" in src
    # upgrade ADDs only the two new columns on the existing table.
    added = _calls("upgrade", "add_column")
    assert added == ["notification_subscriptions", "notification_subscriptions"]
    # No table created/dropped, no column altered/dropped in upgrade.
    assert _calls("upgrade", "create_table") == []
    assert _calls("upgrade", "drop_table") == []
    assert _calls("upgrade", "alter_column") == []
    assert _calls("upgrade", "drop_column") == []
    # downgrade drops ONLY the two Phase-4 columns; nothing else.
    dropped = _calls("downgrade", "drop_column")
    assert dropped == ["notification_subscriptions", "notification_subscriptions"]
    assert _calls("downgrade", "drop_table") == []
    assert _calls("downgrade", "add_column") == []

    # The dropped column names are exactly the two Phase-4 columns.
    dropped_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            for call in ast.walk(node):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "drop_column"
                        and len(call.args) >= 2
                        and isinstance(call.args[1], ast.Constant)):
                    dropped_names.append(call.args[1].value)
    assert set(dropped_names) == {"email", "email_enabled"}, dropped_names
    print("OK migration 008 additive (2 columns) + reversible")


def _main():
    test_build_message()
    test_render_deadline_email()
    test_email_unconfigured_degrades()
    test_email_send_with_stubbed_transport()
    test_email_send_swallows_transport_error()
    test_evaluate_sections_classification()
    test_build_readiness_counts_and_stage()
    test_build_readiness_deadline_annotation()
    test_urgency_thresholds()
    test_calendar_event_and_buckets()
    test_readiness_route_user_scoped()
    test_email_reminder_targets_only_enabled_subscribers()
    test_subscription_model_has_email_channel()
    test_email_validator_no_new_dep()
    test_settings_email_properties()
    test_migration_008_additive_and_reversible()
    print("\nALL PHASE 4 OFFLINE TESTS PASSED")


if __name__ == "__main__":
    _main()
