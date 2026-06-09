"""
Phase 3 — OFFLINE unit tests (no live network, no real LLM/multimodal, no DB).

What is proven OFFLINE here:
  1. The section-template registry is well-formed and `get_sections` selects /
     validates / orders correctly.
  2. Context building (profile + grant) is deterministic and grounded — it only
     contains provided facts and omits missing ones.
  3. The per-section chat messages embed the anti-hallucination system prompt and
     the provided context; extracted-call text is bounded.
  4. Generation degrades safely: with no LLM each section becomes a deterministic
     scaffold (a TODO, no invented facts); with a stubbed LLM the returned text
     is stored verbatim and the whole package is assembled in canonical order.
  5. Export: markdown rendering is deterministic; an unknown format raises;
     .docx/.pdf either render to bytes (deps present) or raise a clear
     RuntimeError (deps absent) — never a silent failure.
  6. Multimodal message construction is correct (text + image_url data-URLs);
     bad mime raises; the PDF path is guarded behind the optional PyMuPDF dep.
  7. Application packages are USER-SCOPED (no unscoped getter; every accessor
     takes user_id) and model/schema/route stay consistent.
  8. Migration 007 adds ONLY the new table+index and has a reversible downgrade.

Run from the backend dir:
    python tests/test_phase3.py
or under pytest:
    python -m pytest tests/test_phase3.py -v
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

from services import document_templates as dt  # noqa: E402
from services.document_service import (  # noqa: E402
    DocumentService,
    build_profile_context,
    build_grant_context,
    SYSTEM_PROMPT,
)
from services import export_service as es  # noqa: E402
from services import multimodal_service as ms  # noqa: E402


# ── Stand-in profile/grant (attributes only — no DB needed) ──────────────────

class _Profile(SimpleNamespace):
    def profile_text(self) -> str:
        parts = [f"Company: {self.name}"]
        for label, attr in (
            ("Organization type", "organization_type"), ("Industry", "industry"),
            ("Stage", "stage"), ("Region", "region"), ("Country", "country"),
            ("Keywords", "keywords"), ("Description", "description"),
        ):
            val = getattr(self, attr, None)
            if val:
                parts.append(f"{label}: {val}")
        return "\n".join(parts)


def _profile(**kw):
    base = dict(
        id=1, name="Acme AI", industry="artificial intelligence",
        stage="mvp", region="Europe", country="Germany",
        funding_amount_sought=100000.0, currency="EUR", team_size=5,
        organization_type="startup", keywords="AI healthcare diagnostics",
        description="AI-powered medical diagnostics platform.",
    )
    base.update(kw)
    return _Profile(**base)


def _grant(**kw):
    base = dict(
        id=7, title="AI Innovation Grant", description="Funding for AI startups.",
        organization="EU Commission", country="Germany", category="Technology",
        deadline=date.today() + timedelta(days=60), industry="artificial intelligence",
        startup_stage="mvp", region="Europe", grant_amount="up to €200,000",
        budget_min=50000.0, budget_max=200000.0, currency="EUR",
        eligibility="EU-based startups.", source_url="https://example.org/grant/7",
        application_url=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── Stub LLM (mirrors the openai AsyncOpenAI surface used by the service) ─────

class _StubMessage:
    def __init__(self, content):
        self.message = SimpleNamespace(content=content)


class _StubCompletions:
    def __init__(self, content):
        self._content = content
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(choices=[_StubMessage(self._content)])


class _StubLLM:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=_StubCompletions(content))


def _make_service(llm=None):
    s = DocumentService.__new__(DocumentService)  # bypass __init__ (no settings)
    s.db = None
    s._llm = llm
    return s


# ── 1. Template registry ─────────────────────────────────────────────────────

def test_templates_registry():
    keys = [s.key for s in dt.DEFAULT_SECTIONS]
    assert len(keys) == len(set(keys)), "section keys must be unique"
    for s in dt.DEFAULT_SECTIONS:
        assert s.title and s.guidance and s.max_tokens > 0, s
    # The four plan-mandated sections are present.
    for required in ("executive_summary", "project_description",
                     "objectives_kpis", "budget"):
        assert required in dt.SECTIONS_BY_KEY, required

    # Default returns all, sorted by order.
    all_secs = dt.get_sections()
    assert [s.key for s in all_secs] == [
        s.key for s in sorted(dt.DEFAULT_SECTIONS, key=lambda x: x.order)
    ]
    # Subset selection preserves canonical order and de-duplicates.
    chosen = dt.get_sections(["budget", "executive_summary", "budget"])
    assert [s.key for s in chosen] == ["executive_summary", "budget"]
    # Unknown key is rejected.
    try:
        dt.get_sections(["nope"])
        assert False, "expected ValueError"
    except ValueError:
        pass
    print("OK template registry well-formed + get_sections selects/validates")


# ── 2. Context building (deterministic + grounded) ───────────────────────────

def test_context_building():
    p = _profile()
    pctx = build_profile_context(p)
    assert "Acme AI" in pctx and "artificial intelligence" in pctx

    g = _grant()
    gctx = build_grant_context(g)
    assert "AI Innovation Grant" in gctx
    assert "EU Commission" in gctx
    assert "https://example.org/grant/7" in gctx
    # Missing fields are omitted, not invented.
    g2 = _grant(organization=None, eligibility=None, description=None)
    gctx2 = build_grant_context(g2)
    assert "Funder/Organization:" not in gctx2
    assert "Eligibility:" not in gctx2
    print("OK context building deterministic + omits missing fields")


# ── 3. Section messages (anti-hallucination prompt) ──────────────────────────

def test_section_messages():
    sec = dt.SECTIONS_BY_KEY["executive_summary"]
    msgs = DocumentService._section_messages(
        sec, "PROFILE_CTX", "GRANT_CTX", extra_ctx="X" * 9000
    )
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == SYSTEM_PROMPT
    # System prompt forbids invention.
    assert "NEVER" in SYSTEM_PROMPT and "invent" in SYSTEM_PROMPT.lower()
    user = msgs[1]["content"]
    assert "PROFILE_CTX" in user and "GRANT_CTX" in user
    assert sec.title in user and sec.guidance in user
    # Extracted-call text is bounded to 4000 chars (truncated exactly).
    assert ("X" * 4000) in user and ("X" * 4001) not in user
    # No extra context → no extracted-call header.
    msgs2 = DocumentService._section_messages(sec, "P", "G")
    assert "EXTRACTED GRANT-CALL TEXT" not in msgs2[1]["content"]
    print("OK section messages embed anti-hallucination prompt + bounded context")


# ── 4. Generation (fallback + stubbed LLM) ───────────────────────────────────

def test_generation_fallback_no_llm():
    async def _run():
        svc = _make_service(llm=None)
        assert svc.llm_available is False
        content = await svc.generate_package_content(_profile(), _grant())
        # All default sections present, in canonical order.
        assert [s["key"] for s in content["sections"]] == [
            s.key for s in dt.get_sections()
        ]
        assert content["llm_used"] is False
        assert content["grant_id"] == 7 and content["profile_id"] == 1
        # Each section is a deterministic scaffold with a TODO and no invented prose.
        for s in content["sections"]:
            assert "[TODO" in s["content"]
        return content

    asyncio.run(_run())
    print("OK no-LLM generation yields deterministic TODO scaffolds")


def test_generation_with_stub_llm():
    async def _run():
        svc = _make_service(llm=_StubLLM("GENERATED BODY"))
        assert svc.llm_available is True
        content = await svc.generate_package_content(
            _profile(), _grant(), section_keys=["executive_summary", "budget"]
        )
        assert [s["key"] for s in content["sections"]] == ["executive_summary", "budget"]
        for s in content["sections"]:
            assert s["content"] == "GENERATED BODY"
        assert content["llm_used"] is True
        # Unknown section key surfaces as ValueError (→ 400 in the API).
        try:
            await svc.generate_package_content(_profile(), _grant(), section_keys=["bad"])
            assert False, "expected ValueError"
        except ValueError:
            pass
        return content

    asyncio.run(_run())
    print("OK stub-LLM generation stores model output verbatim, validates keys")


def test_generate_section_recovers_from_llm_error():
    async def _run():
        class _BoomCompletions:
            async def create(self, **kw):
                raise RuntimeError("gateway down")

        boom = SimpleNamespace(chat=SimpleNamespace(completions=_BoomCompletions()))
        svc = _make_service(llm=boom)
        sec = dt.SECTIONS_BY_KEY["budget"]
        body = await svc.generate_section(sec, "P", "G")
        assert "[TODO" in body  # fell back, did not raise
        return body

    asyncio.run(_run())
    print("OK section generation falls back to scaffold on LLM error")


# ── 5. Export ────────────────────────────────────────────────────────────────

def test_export_markdown_and_formats():
    pkg = {
        "title": "Application: Acme → AI Grant",
        "sections": [
            {"key": "executive_summary", "title": "Executive Summary",
             "content": "Line one.\nLine two."},
            {"key": "budget", "title": "Budget & Justification", "content": "Costs."},
        ],
    }
    md = es.to_markdown(pkg).decode("utf-8")
    assert md.startswith("# Application: Acme → AI Grant")
    assert "## Executive Summary" in md and "## Budget & Justification" in md
    assert "Line one.\nLine two." in md

    assert set(es.EXPORT_FORMATS) == {"md", "docx", "pdf"}
    # Unknown format rejected.
    try:
        es.render(pkg, "txt")
        assert False, "expected ValueError"
    except ValueError:
        pass

    # md always renders via the dispatcher.
    rendered = es.render(pkg, "md")
    assert rendered.extension == "md" and rendered.content

    # docx/pdf: render to bytes if the optional dep is installed, else a clear
    # RuntimeError (never a silent failure).
    for fmt in ("docx", "pdf"):
        try:
            r = es.render(pkg, fmt)
            assert r.content and r.extension == fmt
        except RuntimeError as e:
            assert "Install it with" in str(e) or "requires" in str(e)
    print("OK export: markdown deterministic, formats validated, docx/pdf guarded")


def test_safe_filename():
    assert es._safe_filename("Application: Acme → AI Grant").replace("_", "")
    assert "/" not in es._safe_filename("a/b\\c")
    assert es._safe_filename("") == "application"
    print("OK export filename slugged safely")


# ── 6. Multimodal message construction ───────────────────────────────────────

def test_multimodal_messages_and_data_url():
    url = ms.image_bytes_to_data_url(b"\x89PNG", "image/png")
    assert url.startswith("data:image/png;base64,")
    # Unsupported mime rejected.
    try:
        ms.image_bytes_to_data_url(b"x", "image/gif")
        assert False, "expected ValueError"
    except ValueError:
        pass

    msgs = ms.MultimodalService.build_messages([url, url], "READ THIS")
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    content = msgs[0]["content"]
    assert content[0] == {"type": "text", "text": "READ THIS"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == url
    assert sum(1 for c in content if c["type"] == "image_url") == 2
    print("OK multimodal builds text + image_url data-URL messages")


def test_pdf_path_guarded():
    # The PDF rasterizer must either work (PyMuPDF present) or raise a clear
    # RuntimeError — never an ImportError leaking to the caller. With PyMuPDF
    # present, a corrupt/non-PDF upload must raise ValueError (→ HTTP 400),
    # NOT RuntimeError (reserved for the missing dependency).
    try:
        import fitz  # noqa: F401
        have_fitz = True
    except ImportError:
        have_fitz = False
    if not have_fitz:
        try:
            ms.pdf_bytes_to_image_data_urls(b"%PDF-1.4")
            assert False, "expected RuntimeError without PyMuPDF"
        except RuntimeError as e:
            assert "PyMuPDF" in str(e)
    else:
        try:
            ms.pdf_bytes_to_image_data_urls(b"this is not a pdf")
            assert False, "expected ValueError for a corrupt PDF"
        except ValueError as e:
            assert "PDF" in str(e)
    print("OK PDF rasterization guarded (RuntimeError=missing dep, ValueError=corrupt)")


def test_extract_from_upload_returns_page_count():
    async def _run():
        svc = ms.MultimodalService.__new__(ms.MultimodalService)
        svc._client = None  # not configured → extract_from_images returns None
        url_input = b"\x89PNG fake"
        text, n = await svc.extract_from_upload(url_input, "image/png")
        assert text is None and n == 1, (text, n)
        # Unsupported type still raises ValueError.
        try:
            await svc.extract_from_upload(b"x", "application/zip")
            assert False, "expected ValueError"
        except ValueError:
            pass
        return n

    asyncio.run(_run())
    print("OK extract_from_upload reports actual page/image count")


# ── 7. User-scoping + model/schema/route consistency ─────────────────────────

def test_application_user_scoped():
    import inspect
    from models.application_document import ApplicationPackage
    from services.document_service import DocumentService as DS

    cols = ApplicationPackage.__table__.columns
    assert "user_id" in cols.keys()
    uid = cols["user_id"]
    assert uid.nullable is False, "user_id must be NOT NULL"
    fks = list(uid.foreign_keys)
    assert fks and fks[0].column.table.name == "users", fks

    # No unscoped accessor; every persistence accessor takes user_id.
    assert not hasattr(DS, "get_by_id"), "no unscoped getter allowed"
    for meth in ("get_owned", "list_for_user", "update_sections", "delete"):
        params = inspect.signature(getattr(DS, meth)).parameters
        assert "user_id" in params, (meth, list(params))
    print("OK application packages scoped to the authenticated user")


def test_model_schema_route_consistency():
    from models.application_document import ApplicationPackage
    from schemas.application import ApplicationResponse

    model_cols = set(ApplicationPackage.__table__.columns.keys())
    resp_fields = set(ApplicationResponse.model_fields.keys())
    # Every response field maps to a real model column.
    assert resp_fields <= model_cols, resp_fields - model_cols
    for col in ("user_id", "profile_id", "grant_id", "title", "status", "sections"):
        assert col in model_cols, col

    import api.routes.applications as ar
    paths = {r.path for r in ar.router.routes}
    assert "/applications" in paths
    assert any(p.endswith("/generate") for p in paths), paths
    assert any("/export" in p for p in paths), paths
    assert any(p.endswith("/extract") for p in paths), paths
    print("OK model/schema/route consistent")


# ── 8. Migration 007 hygiene (static, no DB) ─────────────────────────────────

def test_migration_007_additive_and_reversible():
    mig = (_BACKEND / "database" / "migrations" / "versions"
           / "007_phase3_applications.py")
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
                            and call.args
                            and isinstance(call.args[0], ast.Constant)):
                        out.append(call.args[0].value)
        return out

    assert "down_revision = '006_profile_user_scope'" in src
    assert "revision = '007_phase3_applications'" in src
    # upgrade creates ONLY the new table; downgrade drops ONLY it.
    assert _calls("upgrade", "create_table") == ["application_packages"]
    assert _calls("downgrade", "drop_table") == ["application_packages"]
    # No pre-existing tables/columns altered or dropped.
    assert _calls("upgrade", "alter_column") == []
    assert _calls("upgrade", "drop_column") == []
    assert _calls("downgrade", "drop_column") == []
    # Indexes symmetric and Phase-3-owned.
    created = set(_calls("upgrade", "create_index"))
    dropped = set(_calls("downgrade", "drop_index"))
    assert created == dropped, (created, dropped)
    for ix in created:
        assert ix.startswith("ix_application_packages_"), ix
    print("OK migration 007 additive + reversible")


def _main():
    test_templates_registry()
    test_context_building()
    test_section_messages()
    test_generation_fallback_no_llm()
    test_generation_with_stub_llm()
    test_generate_section_recovers_from_llm_error()
    test_export_markdown_and_formats()
    test_safe_filename()
    test_multimodal_messages_and_data_url()
    test_pdf_path_guarded()
    test_extract_from_upload_returns_page_count()
    test_application_user_scoped()
    test_model_schema_route_consistency()
    test_migration_007_additive_and_reversible()
    print("\nALL PHASE 3 OFFLINE TESTS PASSED")


if __name__ == "__main__":
    _main()
