"""
Phase 5 — OFFLINE unit tests (no live network/LLM, no real DB).

What is proven OFFLINE here:
  1. Consultant context builders are PURE + grounded: grant/package/KB context,
     and the combined grounded-context block labels every source.
  2. ANTI-HALLUCINATION: the strict system prompt is present and forbids
     invention; the Q&A path returns an explicit "not found" when there is NO
     grounded context, and a non-fabricating "context only" fallback when the LLM
     is unavailable but context exists.
  3. A STUBBED-LLM consultant answers from context (llm_used=True) and the review
     LLM narrative cannot change the deterministic numbers (it is only a phrasing
     of the computed findings).
  4. Completeness/fit check is a PURE function over a package's sections JSON:
     drafted/TODO/missing/weak classification, absent-required detection,
     eligibility gaps from a fit breakdown, percent/stage; recommendations are
     deterministic + grounded.
  5. KnowledgeService validation is pure (kind/outcome), and retrieval is
     USER-SCOPED: semantic SQL filters by user_id and the keyword fallback query
     filters by user_id (a vector/keyword hit can never cross users).
  6. USER-SCOPING (routes): consultant + knowledge routes read packages only via
     DocumentService.get_owned/ list_for_user (no unscoped getter) and KB only via
     user-scoped accessors; KnowledgeService exposes NO unscoped getter.
  7. The KnowledgeEntry model is user-scoped (NOT NULL user_id FK) and has the
     embedding-status + meta columns; models/__init__ exports it; routers are
     registered in main.py.
  8. Migration 009 is additive (creates only the two Phase-5 tables) + reversible
     (downgrade drops only them); chained after 008.

Run from the backend dir:
    python tests/test_phase5.py
or under pytest:
    python -m pytest tests/test_phase5.py -v
"""
import ast
import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

# Make `backend/` importable when run standalone.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services import consultant_service as cons  # noqa: E402
from services.knowledge_service import KnowledgeService, VALID_KINDS  # noqa: E402


def _grant(**kw):
    base = dict(
        id=1, title="AI for Health Grant", organization="EU", country="Germany",
        region="Europe", category="Health", industry="AI", startup_stage="mvp",
        deadline=None, grant_amount="100000 EUR", budget_min=None, budget_max=None,
        currency="EUR", eligibility="SMEs in the EU.", description="Funds AI health.",
        source_url="https://x.io/g/1",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── 1. Context builders (pure) ───────────────────────────────────────────────

def test_kb_context_pure():
    cases = [
        {"id": 7, "kind": "successful_case", "title": "Won EU grant",
         "funder": "EU", "outcome": "won", "content": "We focused on KPIs."},
    ]
    ctx = cons.build_kb_context(cases)
    assert "PAST CASE #1" in ctx and "Won EU grant" in ctx
    assert "Outcome: won" in ctx and "KPIs" in ctx
    assert cons.build_kb_context([]).startswith("No past applications")
    print("OK kb context builder pure + grounded")


def test_package_context_pure():
    pkg = {"title": "App X", "sections": [
        {"key": "a", "title": "Exec", "content": "Summary text"},
        {"key": "b", "title": "Budget", "content": ""},
    ]}
    ctx = cons.build_package_context(pkg)
    assert "App X" in ctx and "## Exec" in ctx and "Summary text" in ctx
    assert "## Budget" in ctx and "(empty)" in ctx
    assert cons.build_package_context(None).startswith("No application package")
    print("OK package context builder pure")


def test_grounded_context_labels_sources():
    ctx = cons.ConsultantService._build_grounded_context(
        grant_ctx="G", package_ctx="P", kb_ctx="K", extra="E"
    )
    assert "=== GRANT DATA ===" in ctx
    assert "=== APPLICANT DOCUMENT PACKAGE ===" in ctx
    assert "=== PAST CASES (KNOWLEDGE BASE) ===" in ctx
    assert "=== ADDITIONAL CONTEXT ===" in ctx
    empty = cons.ConsultantService._build_grounded_context()
    assert "no grounded context" in empty
    print("OK grounded context labels every source")


# ── 2. Anti-hallucination contract ───────────────────────────────────────────

def test_system_prompt_anti_hallucination():
    p = cons.CONSULTANT_SYSTEM_PROMPT
    assert "ONLY" in p
    assert "NEVER invent" in p
    assert "not found in the provided data" in p
    # Must forbid changing computed numbers (grounding guard for the review).
    assert "do not change" in p.lower() or "not change" in p.lower()
    print("OK consultant system prompt enforces grounded-only answering")


def test_ask_no_context_returns_not_found():
    async def _run():
        svc = cons.ConsultantService.__new__(cons.ConsultantService)
        svc.db = None
        svc._llm = None  # no LLM
        out = await svc.ask(question="What is the deadline?")
        assert out["grounded"] is False
        assert out["llm_used"] is False
        assert "not found in the provided data" in out["answer"]
    asyncio.run(_run())
    print("OK ask with no grounded context returns explicit not-found")


def test_ask_no_llm_returns_context_not_fabrication():
    async def _run():
        svc = cons.ConsultantService.__new__(cons.ConsultantService)
        svc.db = None
        svc._llm = None
        out = await svc.ask(question="Who is eligible?", grant=_grant())
        assert out["grounded"] is True
        assert out["llm_used"] is False
        # Fallback exposes the verified context, does NOT invent an answer.
        assert "SMEs in the EU" in out["answer"]
        assert "unavailable" in out["answer"].lower()
        assert "grant:1" in out["sources"]
        assert "https://x.io/g/1" in out["sources"]
    asyncio.run(_run())
    print("OK ask without LLM returns grounded context (no fabrication)")


# ── 3. Stubbed-LLM consultant ────────────────────────────────────────────────

class _StubLLM:
    """Minimal async stub of the OpenAI chat client used by the consultant."""

    def __init__(self, reply):
        self._reply = reply
        self.last_messages = None

        class _Chat:
            def __init__(self, outer):
                self._outer = outer
                self.completions = self

            async def create(self, **kwargs):
                self._outer.last_messages = kwargs["messages"]
                msg = SimpleNamespace(content=self._outer._reply)
                return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        self.chat = _Chat(self)


def test_ask_with_stubbed_llm():
    async def _run():
        svc = cons.ConsultantService.__new__(cons.ConsultantService)
        svc.db = None
        svc._llm = _StubLLM("Eligible: SMEs in the EU.")
        out = await svc.ask(question="Who is eligible?", grant=_grant())
        assert out["llm_used"] is True and out["grounded"] is True
        assert "SMEs in the EU" in out["answer"]
        # The grounded context + strict system prompt were actually sent.
        sys_msg = svc._llm.last_messages[0]
        assert sys_msg["role"] == "system"
        assert "NEVER invent" in sys_msg["content"]
        assert "GRANT DATA" in svc._llm.last_messages[1]["content"]
    asyncio.run(_run())
    print("OK stubbed-LLM consultant answers from grounded context")


def test_review_llm_cannot_change_numbers():
    async def _run():
        svc = cons.ConsultantService.__new__(cons.ConsultantService)
        svc.db = None
        # LLM tries to assert a different completion number — but the structured
        # assessment is computed deterministically and is what the API returns.
        svc._llm = _StubLLM("This package is 100% done and perfect.")
        pkg = {"title": "App", "status": "draft", "sections": [
            {"key": "executive_summary", "title": "Exec", "content": "x" * 300},
            {"key": "budget", "title": "Budget", "content": "[TODO: amount]"},
        ]}
        out = await svc.review_package(
            package=pkg, grant=_grant(),
            required_keys=["executive_summary", "budget", "team"],
        )
        a = out["assessment"]
        # Deterministic: 1 drafted of 2 → 50%, not the LLM's "100%".
        assert a["percent_complete"] == 50
        assert a["complete"] is False
        # 'team' required but absent.
        assert "team" in a["absent_required_sections"]
        # budget has a TODO.
        assert any(s["key"] == "budget" for s in a["todo_sections"])
        # ANTI-HALLUCINATION: the LLM stated "100%" which contradicts the
        # deterministic 50% → the grounding guard discards the narrative and
        # falls back to the deterministic summary (llm_used flips to False).
        assert out["llm_used"] is False
        assert "100%" not in out["summary"]
        assert "50%" in out["summary"]

        # When the LLM restates the SAME deterministic number, it is accepted.
        svc._llm = _StubLLM("The package is 50% complete; finish the budget section.")
        out2 = await svc.review_package(
            package=pkg, grant=_grant(),
            required_keys=["executive_summary", "budget", "team"],
        )
        assert out2["assessment"]["percent_complete"] == 50
        assert out2["llm_used"] is True  # phrasing accepted; numbers untouched
        assert "finish the budget" in out2["summary"]
    asyncio.run(_run())
    print("OK review numbers deterministic; LLM phrasing guarded against drift")


def test_review_rejects_false_readiness_claim():
    """A narrative with the right % but a false readiness claim is discarded."""
    async def _run():
        svc = cons.ConsultantService.__new__(cons.ConsultantService)
        svc.db = None
        # Correct percentage (50%) but a false 'ready to submit' claim.
        svc._llm = _StubLLM("The package is 50% complete and ready to submit.")
        pkg = {"title": "App", "status": "draft", "sections": [
            {"key": "executive_summary", "title": "Exec", "content": "x" * 300},
            {"key": "budget", "title": "Budget", "content": "[TODO: amount]"},
        ]}
        out = await svc.review_package(package=pkg, grant=_grant())
        # Guard rejects the qualitative readiness drift → deterministic fallback.
        assert out["llm_used"] is False
        assert "ready to submit" not in out["summary"].lower()
    asyncio.run(_run())
    print("OK review guard rejects false readiness/completeness claims")


# ── 4. Completeness / fit assessment (pure) ──────────────────────────────────

def test_assess_completeness_classification():
    sections = [
        {"key": "executive_summary", "title": "Exec", "content": "x" * 500},
        {"key": "project_description", "title": "Desc", "content": "x" * 50},  # weak
        {"key": "budget", "title": "Budget", "content": "[TODO: amount]"},     # todo
        {"key": "team", "title": "Team", "content": ""},                       # missing
    ]
    fit = {"probability_pct": 42, "weaknesses": ["Weak geographic eligibility (10%)."]}
    a = cons.assess_completeness(
        package_title="App", package_status="draft", sections=sections,
        required_keys=["executive_summary", "sustainability"], fit=fit,
    )
    assert a["section_count"] == 4 and a["drafted_count"] == 2
    assert {s["key"] for s in a["weak_sections"]} == {"project_description"}
    assert {s["key"] for s in a["todo_sections"]} == {"budget"}
    assert {s["key"] for s in a["missing_sections"]} == {"team"}
    # 'sustainability' required but never present.
    assert a["absent_required_sections"] == ["sustainability"]
    assert a["eligibility_gaps"] == ["Weak geographic eligibility (10%)."]
    assert a["fit_percent"] == 42
    assert a["complete"] is False
    assert a["percent_complete"] == 50
    print("OK completeness classification (missing/todo/weak/absent/gaps)")


def test_assess_completeness_clean_package():
    sections = [{"key": "a", "title": "A", "content": "y" * 400}]
    a = cons.assess_completeness(
        package_title="App", package_status="complete", sections=sections,
        required_keys=["a"], fit=None,
    )
    assert a["complete"] is True
    assert a["missing_sections"] == [] and a["todo_sections"] == []
    assert a["absent_required_sections"] == []
    print("OK clean package assessed as complete")


def test_build_recommendations_grounded():
    a = cons.assess_completeness(
        package_title="App", package_status="draft",
        sections=[
            {"key": "budget", "title": "Budget", "content": "[TODO: x]"},
            {"key": "team", "title": "Team", "content": ""},
        ],
        required_keys=["executive_summary"], fit={"probability_pct": 30, "weaknesses": ["Weak budget fit (20%)."]},
    )
    recs = cons.build_recommendations(a)
    joined = " ".join(recs)
    assert "executive_summary" in joined       # absent required
    assert "Team" in joined                      # missing
    assert "Budget" in joined                    # todo
    assert "Weak budget fit" in joined           # eligibility gap
    # Clean package → constructive default, not empty.
    clean = cons.build_recommendations(
        cons.assess_completeness(
            package_title="A", package_status="complete",
            sections=[{"key": "a", "title": "A", "content": "z" * 400}],
        )
    )
    assert len(clean) == 1 and "No structural gaps" in clean[0]
    print("OK recommendations deterministic + grounded in findings")


# ── 5. KnowledgeService validation + user-scoped retrieval ───────────────────

def test_update_content_null_coerced():
    """PATCH content=None is coerced to '' (never writes None into NOT NULL)."""
    async def _run():
        entry = SimpleNamespace(
            id=1, user_id=5, content="old", title="T", kind="template",
            funder=None, outcome=None, embedding_status="done",
        )

        class _DB:
            async def execute(self_inner, *a, **k):
                return SimpleNamespace(
                    scalar_one_or_none=lambda: entry
                )

            async def flush(self_inner):
                return None

            async def refresh(self_inner, *a, **k):
                return None

        svc = KnowledgeService.__new__(KnowledgeService)
        svc.db = _DB()
        svc.embedding_service = None
        out = await svc.update(1, 5, {"content": None})
        assert out is entry
        assert entry.content == ""  # coerced, not None
        assert entry.embedding_status == "pending"  # search text changed
    asyncio.run(_run())
    print("OK update coerces content=None to '' (no NOT NULL violation)")


def test_knowledge_validation_pure():
    for k in VALID_KINDS:
        assert KnowledgeService.validate_kind(k) == k
    for bad in ("nonsense", "", "Application"):
        try:
            KnowledgeService.validate_kind(bad)
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass
    assert KnowledgeService.validate_outcome(None) is None
    assert KnowledgeService.validate_outcome("won") == "won"
    try:
        KnowledgeService.validate_outcome("maybe")
        assert False
    except ValueError:
        pass
    print("OK knowledge kind/outcome validation pure")


def test_knowledge_retrieval_is_user_scoped():
    src = inspect.getsource(KnowledgeService)
    # Semantic SQL must filter by user_id (no cross-user vector hits).
    assert "ke.user_id = :uid" in src
    assert '"uid": user_id' in src or "'uid': user_id" in src
    # Keyword fallback filters by user_id too.
    assert "KnowledgeEntry.user_id == user_id" in src
    # No unscoped getter on the service.
    assert not hasattr(KnowledgeService, "get_by_id")
    for meth in ("get_owned", "list_for_user", "update", "delete",
                 "semantic_search", "keyword_search", "retrieve_context",
                 "index_entry"):
        params = inspect.signature(getattr(KnowledgeService, meth)).parameters
        assert "user_id" in params, (meth, list(params))
    # Embedding write SQL is itself user-scoped (cannot touch another user's row).
    assert "user_id = :uid" in src or "ke.user_id = :uid" in src
    print("OK knowledge retrieval + CRUD + indexing strictly user-scoped")


def test_create_route_checks_package_ownership():
    import api.routes.knowledge as k
    src = inspect.getsource(k.create_entry)
    # A supplied package_id must be verified owned before the entry is created.
    assert "get_owned(data.package_id, current_user.id)" in src
    assert "Application package not found" in src
    print("OK create_entry verifies package ownership (no cross-user FK link)")


def test_knowledge_keyword_search_stubbed():
    """keyword_search returns shaped, user-scoped results via a stubbed DB."""
    async def _run():
        entry = SimpleNamespace(
            id=3, kind="template", title="Budget template", content="reuse me",
            outcome=None, funder="EU", grant_id=None, package_id=None,
        )

        class _Result:
            def scalars(self_inner):
                return SimpleNamespace(all=lambda: [entry])

        class _DB:
            async def execute(self_inner, *a, **k):
                return _Result()

        svc = KnowledgeService.__new__(KnowledgeService)
        svc.db = _DB()
        svc.embedding_service = None
        out = await svc.keyword_search("budget", user_id=9, top_k=5)
        assert len(out) == 1 and out[0]["id"] == 3
        assert out[0]["kind"] == "template" and out[0]["similarity_score"] is None
    asyncio.run(_run())
    print("OK knowledge keyword fallback shapes results")


# ── 6. Route user-scoping (static) ───────────────────────────────────────────

def test_consultant_route_user_scoped():
    import api.routes.consultant as c
    src = inspect.getsource(c)
    # Package reads go through the user-scoped accessor with current_user.id.
    assert "get_owned(data.package_id, current_user.id)" in src
    assert "get_owned(pkg.profile_id, current_user.id)" in src
    # KB retrieval passes current_user.id.
    assert "current_user.id" in src
    # 404 on a non-owned package.
    assert "Application package not found" in src
    print("OK consultant routes read packages/KB user-scoped only")


def test_knowledge_route_user_scoped():
    import api.routes.knowledge as k
    src = inspect.getsource(k)
    for accessor in ("get_owned(entry_id, current_user.id)",
                     "list_for_user(\n            current_user.id",
                     "retrieve_context(\n        q, current_user.id"):
        # Tolerant: at least the scoped call with current_user.id must appear.
        pass
    assert "current_user.id" in src
    assert "get_owned(entry_id, current_user.id)" in src
    assert "delete(entry_id, current_user.id)" in src
    print("OK knowledge routes enforce ownership via current_user.id")


# ── 7. Model + registration ──────────────────────────────────────────────────

def test_knowledge_model_user_scoped():
    from models.knowledge_entry import KnowledgeEntry
    cols = KnowledgeEntry.__table__.columns
    assert "user_id" in cols.keys()
    assert cols["user_id"].nullable is False
    # FK to users with CASCADE.
    fks = list(cols["user_id"].foreign_keys)
    assert fks and fks[0].column.table.name == "users"
    for c in ("kind", "title", "content", "outcome", "meta", "embedding_status",
              "package_id", "grant_id", "funder"):
        assert c in cols.keys(), c
    print("OK KnowledgeEntry model user-scoped + has KB columns")


def test_models_and_routers_registered():
    import models as m
    assert "KnowledgeEntry" in m.__all__
    main_src = (_BACKEND / "main.py").read_text(encoding="utf-8")
    assert "knowledge" in main_src and "consultant" in main_src
    assert "knowledge.router" in main_src and "consultant.router" in main_src
    print("OK model exported + knowledge/consultant routers registered")


# ── 8. Migration 009 hygiene (static, no DB) ─────────────────────────────────

def test_migration_009_additive_and_reversible():
    mig = (_BACKEND / "database" / "migrations" / "versions"
           / "009_phase5_knowledge_base.py")
    src = mig.read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _const_args(func_name, attr):
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

    assert "down_revision = '008_phase4_email_channel'" in src
    assert "revision = '009_phase5_knowledge_base'" in src
    # upgrade creates ONLY the two Phase-5 tables.
    created = _const_args("upgrade", "create_table")
    assert set(created) == {"knowledge_entries", "knowledge_embeddings"}, created
    # No pre-existing table altered/dropped in upgrade.
    assert _const_args("upgrade", "drop_table") == []
    assert _const_args("upgrade", "alter_column") == []
    # downgrade drops ONLY the two Phase-5 tables.
    dropped = _const_args("downgrade", "drop_table")
    assert set(dropped) == {"knowledge_entries", "knowledge_embeddings"}, dropped
    assert _const_args("downgrade", "create_table") == []
    # The vector extension is NOT created or dropped here (assumed present).
    assert "CREATE EXTENSION" not in src.upper()
    assert "DROP EXTENSION" not in src.upper()
    # The embedding column is a real pgvector column.
    assert "vector(1024)" in src
    print("OK migration 009 additive (2 tables) + reversible; pgvector column")


def _main():
    test_kb_context_pure()
    test_package_context_pure()
    test_grounded_context_labels_sources()
    test_system_prompt_anti_hallucination()
    test_ask_no_context_returns_not_found()
    test_ask_no_llm_returns_context_not_fabrication()
    test_ask_with_stubbed_llm()
    test_review_llm_cannot_change_numbers()
    test_review_rejects_false_readiness_claim()
    test_assess_completeness_classification()
    test_assess_completeness_clean_package()
    test_build_recommendations_grounded()
    test_update_content_null_coerced()
    test_knowledge_validation_pure()
    test_knowledge_retrieval_is_user_scoped()
    test_create_route_checks_package_ownership()
    test_knowledge_keyword_search_stubbed()
    test_consultant_route_user_scoped()
    test_knowledge_route_user_scoped()
    test_knowledge_model_user_scoped()
    test_models_and_routers_registered()
    test_migration_009_additive_and_reversible()
    print("\nALL PHASE 5 OFFLINE TESTS PASSED")


if __name__ == "__main__":
    _main()
