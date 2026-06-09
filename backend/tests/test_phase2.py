"""
Phase 2 — OFFLINE unit tests (no live network, no real LLM, no real DB).

Run from the backend dir:
    python -m pytest tests/test_phase2.py -v
or standalone:
    python tests/test_phase2.py

What is proven OFFLINE here:
  1. The deterministic per-dimension scorers behave correctly (industry/region/
     budget/deadline/stage) on representative inputs.
  2. The weighted-average fit formula gives a HIGH score to a good-fit
     profile/grant pair and a LOW score to a poor-fit pair — and inapplicable
     dimensions are dropped from the denominator (sparse profile not penalised).
  3. The semantic dimension is exercised with a STUBBED embedding + DB so no
     network/pgvector is needed, and it is dropped when embeddings are absent.
  4. Strengths/weaknesses extraction has the right SHAPE (non-empty lists,
     grounded in the computed dimensions) and the LLM is NOT required.
  5. rank_for_profile orders grants best-fit first.
  6. The model + schema + route are mutually consistent (field parity).
  7. Migration 005 adds ONLY new objects and has a reversible downgrade that
     drops only Phase-2-owned objects (static AST check, no DB).

NOTE: these use lightweight stand-in objects (SimpleNamespace) for Grant and
CompanyProfile because the deterministic scorers only read attributes. The real
ORM models are imported in the consistency test (7) to verify field parity.
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

from services.matching_service import MatchingService, SCORING_WEIGHTS  # noqa: E402


# ── Helpers: build a MatchingService whose external deps are stubbed ─────────

class _StubEmbeddingService:
    """Returns a fixed query embedding or None to simulate 'no API'."""
    def __init__(self, vec):
        self._vec = vec

    async def generate_embedding(self, text_input, input_type="passage"):
        return self._vec


class _StubResultRow:
    def __init__(self, similarity):
        self.similarity = similarity


class _StubResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _StubDB:
    """Minimal async DB stub: execute() returns a preset similarity row."""
    def __init__(self, similarity=None):
        self._similarity = similarity

    async def execute(self, *a, **k):
        if self._similarity is None:
            return _StubResult(None)
        return _StubResult(_StubResultRow(self._similarity))


def _make_matcher(embedding_vec=None, similarity=None):
    """Build a MatchingService with no real DB/LLM/embeddings."""
    m = MatchingService.__new__(MatchingService)  # bypass __init__ (no settings/LLM)
    m.db = _StubDB(similarity=similarity)
    m.embedding_service = _StubEmbeddingService(embedding_vec)
    m._llm = None  # force deterministic fallback explanation
    return m


class _Profile(SimpleNamespace):
    """Stand-in for CompanyProfile that mirrors its profile_text() so the real
    score_semantic() path (which calls profile.profile_text()) can be exercised
    offline without a DB-backed model instance."""

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
        if getattr(self, "funding_amount_sought", None) is not None:
            cur = getattr(self, "currency", None) or ""
            parts.append(f"Funding sought: {cur} {self.funding_amount_sought}".strip())
        return "\n".join(parts)


def _profile(**kw):
    base = dict(
        name="Acme AI", industry="artificial intelligence machine learning",
        stage="mvp", region="Europe", country="Germany",
        funding_amount_sought=100000.0, currency="EUR", team_size=5,
        organization_type="startup", keywords="AI healthcare diagnostics",
        description="AI-powered medical diagnostics platform.", past_funding=None,
    )
    base.update(kw)
    return _Profile(**base)


def _grant(**kw):
    base = dict(
        id=1, title="AI Innovation Grant", description="Funding for AI startups.",
        organization="EU Commission", country="Germany", category="Technology",
        deadline=date.today() + timedelta(days=60), industry="artificial intelligence",
        startup_stage="mvp", region="Europe", grant_amount="up to €200,000",
        budget_min=50000.0, budget_max=200000.0, currency="EUR",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── 1. Per-dimension scorers ─────────────────────────────────────────────────

def test_industry_scorer():
    # Perfect overlap with profile industry vocabulary.
    s, ok = MatchingService.score_industry(
        _profile(industry="artificial intelligence", keywords=""),
        _grant(industry="artificial intelligence", category="", title=""),
    )
    assert ok and s == 1.0, (s, ok)
    # No overlap at all.
    s, ok = MatchingService.score_industry(
        _profile(industry="agriculture farming", keywords=""),
        _grant(industry="fintech", category="finance", title="Banking Fund"),
    )
    assert ok and s == 0.0, (s, ok)
    # Profile gives no industry signal -> not applicable.
    s, ok = MatchingService.score_industry(
        _profile(industry=None, keywords=None), _grant()
    )
    assert ok is False, (s, ok)
    print("OK industry scorer")


def test_region_scorer():
    # Global grant matches anyone.
    s, ok = MatchingService.score_region(_profile(), _grant(region="Global", country=""))
    assert ok and s == 1.0
    # Same region.
    s, ok = MatchingService.score_region(
        _profile(region="Europe", country="Germany"),
        _grant(region="Europe", country="Germany"),
    )
    assert ok and s == 1.0
    # Mismatched region.
    s, ok = MatchingService.score_region(
        _profile(region="Asia", country="Japan"),
        _grant(region="North America", country="USA"),
    )
    assert ok and s == 0.0, (s, ok)
    # Profile has no geo -> not applicable.
    s, ok = MatchingService.score_region(_profile(region=None, country=None), _grant())
    assert ok is False
    print("OK region scorer")


def test_budget_scorer():
    # Inside window -> 1.0
    s, ok = MatchingService.score_budget(
        _profile(funding_amount_sought=100000.0),
        _grant(budget_min=50000.0, budget_max=200000.0),
    )
    assert ok and s == 1.0
    # Asking far above the grant's max -> decays well below 1.
    s, ok = MatchingService.score_budget(
        _profile(funding_amount_sought=1000000.0),
        _grant(budget_min=50000.0, budget_max=200000.0),
    )
    assert ok and 0.0 < s < 0.3, s
    # No funding sought -> not applicable.
    s, ok = MatchingService.score_budget(
        _profile(funding_amount_sought=None), _grant()
    )
    assert ok is False
    print("OK budget scorer")


def test_deadline_scorer():
    s, ok = MatchingService.score_deadline(
        _profile(), _grant(deadline=date.today() + timedelta(days=30))
    )
    assert ok and s == 1.0
    s, ok = MatchingService.score_deadline(
        _profile(), _grant(deadline=date.today() - timedelta(days=1))
    )
    assert ok and s == 0.0  # already closed
    print("OK deadline scorer")


def test_stage_scorer():
    s, ok = MatchingService.score_stage(_profile(stage="mvp"), _grant(startup_stage="mvp"))
    assert ok and s == 1.0
    s, ok = MatchingService.score_stage(
        _profile(stage="idea"), _grant(startup_stage="growth scaling")
    )
    assert ok and s == 0.0
    s, ok = MatchingService.score_stage(_profile(stage=None), _grant())
    assert ok is False
    print("OK stage scorer")


# ── 2 & 3. Aggregate fit formula + semantic dimension ────────────────────────

def test_good_fit_scores_high_poor_fit_scores_low():
    async def _run():
        matcher = _make_matcher(embedding_vec=[0.1] * 8, similarity=0.9)
        good = await matcher.compute_fit(_profile(), _grant())
        # Strong on every applicable dimension -> high score.
        assert good["fit_score"] >= 0.85, good["fit_score"]
        assert good["probability_pct"] >= 85

        poor = await matcher.compute_fit(
            _profile(
                industry="agriculture", keywords="farming livestock",
                region="Asia", country="Japan", stage="idea",
                funding_amount_sought=5000000.0,
            ),
            _grant(
                industry="fintech", category="finance", title="Banking Fund",
                region="North America", country="USA", startup_stage="growth",
                budget_min=10000.0, budget_max=50000.0,
                deadline=date.today() - timedelta(days=5),  # closed
            ),
        )
        assert poor["fit_score"] <= 0.25, poor["fit_score"]
        # Good must clearly beat poor.
        assert good["fit_score"] > poor["fit_score"] + 0.5
        return good, poor

    good, poor = asyncio.run(_run())
    print(f"OK good-fit={good['fit_score']} >> poor-fit={poor['fit_score']}")


def test_semantic_dropped_when_no_embeddings():
    async def _run():
        # No embedding vector -> semantic dimension not applicable.
        matcher = _make_matcher(embedding_vec=None)
        s, ok = await matcher.score_semantic(_profile(), _grant())
        assert ok is False and s == 0.0
        fit = await matcher.compute_fit(_profile(), _grant())
        # Semantic weight must be absent from the applied weights.
        assert "semantic" not in fit["breakdown"]["weights"], fit["breakdown"]["weights"]
        # Denominator = sum of the 5 applicable structured weights.
        applied = fit["breakdown"]["weights"]
        assert abs(sum(applied.values()) - (sum(SCORING_WEIGHTS.values()) - SCORING_WEIGHTS["semantic"])) < 1e-9
        return fit

    fit = asyncio.run(_run())
    print("OK semantic dimension dropped when embeddings absent")


def test_semantic_similarity_clamped_and_used():
    async def _run():
        matcher = _make_matcher(embedding_vec=[0.2] * 8, similarity=0.77)
        s, ok = await matcher.score_semantic(_profile(), _grant())
        assert ok and abs(s - 0.77) < 1e-9, (s, ok)
        # Negative cosine clamps to 0.
        matcher2 = _make_matcher(embedding_vec=[0.2] * 8, similarity=-0.3)
        s2, ok2 = await matcher2.score_semantic(_profile(), _grant())
        assert ok2 and s2 == 0.0
        return s

    asyncio.run(_run())
    print("OK semantic similarity used + clamped to [0,1]")


# ── 4. Strengths / weaknesses shape (no LLM) ─────────────────────────────────

def test_strengths_weaknesses_shape_no_llm():
    async def _run():
        matcher = _make_matcher(embedding_vec=[0.1] * 8, similarity=0.9)
        fit = await matcher.analyze_pair(_profile(), _grant(), with_llm=True)
        # _llm is None -> explanation must be the deterministic fallback.
        assert isinstance(fit["strengths"], list) and fit["strengths"]
        assert isinstance(fit["weaknesses"], list) and fit["weaknesses"]
        assert isinstance(fit["explanation"], str) and fit["explanation"]
        # A good-fit pair should surface at least one concrete strength.
        assert any("Strong" in s for s in fit["strengths"]), fit["strengths"]
        # The explanation is grounded: it echoes the computed probability.
        assert str(fit["probability_pct"]) in fit["explanation"]

        # A poor pair should surface concrete weaknesses.
        poor = await matcher.analyze_pair(
            _profile(industry="agriculture", keywords="farming", region="Asia",
                     country="Japan", stage="idea", funding_amount_sought=9e6),
            _grant(industry="fintech", category="finance", title="Bank Fund",
                   region="USA", country="USA", startup_stage="growth",
                   budget_min=1000.0, budget_max=5000.0),
            with_llm=True,
        )
        assert any("Weak" in w for w in poor["weaknesses"]), poor["weaknesses"]
        return fit

    asyncio.run(_run())
    print("OK strengths/weaknesses shape correct without LLM")


# ── 5. Ranking ───────────────────────────────────────────────────────────────

def test_rank_orders_best_first():
    async def _run():
        matcher = _make_matcher(embedding_vec=None)  # structured-only ranking
        profile = _profile()
        strong = _grant(id=1)
        weak = _grant(
            id=2, industry="fishing", category="marine", title="Fisheries Fund",
            region="Antarctica", country="", startup_stage="established",
            budget_min=1.0, budget_max=10.0,
            deadline=date.today() - timedelta(days=10),
        )
        ranked = await matcher.rank_for_profile(profile, [weak, strong], limit=2, with_llm=False)
        assert [r["grant_id"] for r in ranked] == [1, 2], ranked
        assert ranked[0]["fit_score"] > ranked[1]["fit_score"]
        return ranked

    asyncio.run(_run())
    print("OK ranking orders best-fit first")


# ── 6. Model / schema / route consistency ────────────────────────────────────

def test_model_schema_route_consistency():
    from models.profile import CompanyProfile
    from schemas.profile import ProfileBase, ProfileResponse

    model_cols = set(CompanyProfile.__table__.columns.keys())
    schema_fields = set(ProfileBase.model_fields.keys())
    # Every editable schema field must exist as a model column.
    assert schema_fields <= model_cols, schema_fields - model_cols
    # Core matching fields present on the model.
    for col in ("industry", "stage", "region", "funding_amount_sought",
                "team_size", "organization_type", "keywords", "description"):
        assert col in model_cols, col
    # Response adds id + timestamps.
    resp_fields = set(ProfileResponse.model_fields.keys())
    assert {"id", "created_at", "updated_at"} <= resp_fields

    # Route module imports cleanly and exposes the recommendation endpoint.
    import api.routes.profiles as pr
    paths = {r.path for r in pr.router.routes}
    assert "/profiles" in paths
    assert any("/recommendations" in p for p in paths), paths
    assert any("/fit/" in p for p in paths), paths
    print("OK model/schema/route consistent")


# ── 7. Migration 005 hygiene (static, no DB) ─────────────────────────────────

def test_migration_005_additive_and_reversible():
    mig = (_BACKEND / "database" / "migrations" / "versions"
           / "005_phase2_profiles.py")
    src = mig.read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _calls(func_name, attr):
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                for call in ast.walk(node):
                    if (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == attr
                            and call.args
                            and isinstance(call.args[0], ast.Constant)):
                        names.append(call.args[0].value)
        return names

    # Linear chain off Phase 1.
    assert "down_revision = '004_phase1_filters'" in src
    assert "revision = '005_phase2_profiles'" in src

    # upgrade creates ONLY the new table; downgrade drops ONLY that table.
    assert _calls("upgrade", "create_table") == ["company_profiles"]
    assert _calls("downgrade", "drop_table") == ["company_profiles"]
    # No pre-existing tables/columns altered or dropped anywhere.
    assert _calls("upgrade", "alter_column") == []
    assert _calls("downgrade", "alter_column") == []
    assert _calls("upgrade", "drop_column") == []
    assert _calls("downgrade", "drop_column") == []
    # Indexes are symmetric (every created index is dropped on downgrade) and
    # all are Phase-2-owned (company_profiles only).
    created = set(_calls("upgrade", "create_index"))
    dropped = set(_calls("downgrade", "drop_index"))
    assert created == dropped, (created, dropped)
    for ix in created:
        assert ix.startswith("ix_company_profiles_"), ix
    print("OK migration 005 additive + reversible")


# ── 8. Regression tests for the codex round-1 findings ───────────────────────

class _RaisingEmbeddingService:
    """Simulates an embedding API that raises (timeout / rate-limit / bad key)."""
    async def generate_embedding(self, text_input, input_type="passage"):
        raise RuntimeError("embedding API down")


class _StubMessage:
    def __init__(self, content):
        self.message = SimpleNamespace(content=content)


class _StubCompletions:
    def __init__(self, content):
        self._content = content

    async def create(self, **kw):
        return SimpleNamespace(choices=[_StubMessage(self._content)])


class _StubLLM:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=_StubCompletions(content))


def test_region_no_false_positives():
    # United States vs United Kingdom must NOT match (the old substring bug).
    s, ok = MatchingService.score_region(
        _profile(region="", country="United States"),
        _grant(region="", country="United Kingdom"),
    )
    assert ok and s == 0.0, (s, ok)
    # South America vs North America must NOT match.
    s, ok = MatchingService.score_region(
        _profile(region="South America", country=""),
        _grant(region="North America", country=""),
    )
    assert ok and s == 0.0, (s, ok)
    # Aliases DO match: profile "USA" vs grant "United States".
    s, ok = MatchingService.score_region(
        _profile(region="", country="USA"),
        _grant(region="", country="United States"),
    )
    assert ok and s == 1.0, (s, ok)
    print("OK region scorer rejects US/UK + S.America/N.America false positives")


def test_budget_currency_mismatch_not_perfect():
    # Same number, different currency -> must NOT be a perfect 1.0 fit.
    s, ok = MatchingService.score_budget(
        _profile(funding_amount_sought=100000.0, currency="KZT"),
        _grant(budget_min=50000.0, budget_max=200000.0, currency="USD"),
    )
    assert ok and s <= 0.5, (s, ok)
    # Same currency, inside window -> still perfect.
    s, ok = MatchingService.score_budget(
        _profile(funding_amount_sought=100000.0, currency="USD"),
        _grant(budget_min=50000.0, budget_max=200000.0, currency="USD"),
    )
    assert ok and s == 1.0, (s, ok)
    print("OK budget scorer respects currency mismatch")


def test_semantic_drops_on_embedding_exception():
    async def _run():
        matcher = _make_matcher(embedding_vec=[0.1] * 8, similarity=0.9)
        matcher.embedding_service = _RaisingEmbeddingService()
        # Must NOT raise — the dimension is dropped instead.
        s, ok = await matcher.score_semantic(_profile(), _grant())
        assert ok is False and s == 0.0, (s, ok)
        # And a full fit still computes (semantic weight absent from denominator).
        fit = await matcher.compute_fit(_profile(), _grant())
        assert "semantic" not in fit["breakdown"]["weights"], fit["breakdown"]["weights"]
        return fit

    asyncio.run(_run())
    print("OK semantic dimension dropped when embedding API raises")


def test_explanation_grounding_guard():
    async def _run():
        matcher = _make_matcher(embedding_vec=None)
        fit = await matcher.compute_fit(_profile(), _grant())
        # LLM tries to contradict the computed score with a different percentage.
        bad_pct = (fit["probability_pct"] + 11) % 100
        matcher._llm = _StubLLM(f"This is a great fit at about {bad_pct}% chance.")
        explanation = await matcher.explain_fit(_profile(), _grant(), fit)
        # The contradicting LLM text must be rejected for the grounded fallback.
        assert str(bad_pct) + "%" not in explanation
        assert str(fit["probability_pct"]) in explanation, explanation

        # A consistent LLM explanation (no number, or the right one) is kept.
        matcher._llm = _StubLLM("Strong alignment on industry and region.")
        kept = await matcher.explain_fit(_profile(), _grant(), fit)
        assert kept == "Strong alignment on industry and region."
        return explanation

    asyncio.run(_run())
    print("OK explanation grounding guard rejects contradicting LLM score")


# ── 9. Profile ownership / user-scoping (codex round-2 [High]) ───────────────

def test_profile_user_scoped():
    import inspect
    from models.profile import CompanyProfile
    from services.profile_service import ProfileService

    cols = CompanyProfile.__table__.columns
    assert "user_id" in cols.keys(), list(cols.keys())
    uid = cols["user_id"]
    assert uid.nullable is False, "user_id must be NOT NULL"
    fks = list(uid.foreign_keys)
    assert fks and fks[0].column.table.name == "users", fks

    # No unscoped accessor remains; every CRUD method requires a user_id.
    assert not hasattr(ProfileService, "get_by_id"), "unscoped get_by_id must be gone"
    for meth in ("create", "get_owned", "list_for_user", "update", "delete"):
        params = inspect.signature(getattr(ProfileService, meth)).parameters
        assert "user_id" in params, (meth, list(params))
    print("OK profiles are scoped to the authenticated user")


def test_migration_006_additive_and_reversible():
    mig = (_BACKEND / "database" / "migrations" / "versions"
           / "006_profile_user_scope.py")
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

    assert "down_revision = '005_phase2_profiles'" in src
    assert "revision = '006_profile_user_scope'" in src
    # Only ADDS to the existing Phase-2 table; never creates/drops a table or
    # touches another table.
    assert _calls("upgrade", "add_column") == ["company_profiles"]
    assert _calls("upgrade", "create_index") == ["ix_company_profiles_user_id"]
    assert _calls("upgrade", "create_foreign_key") == ["fk_company_profiles_user_id"]
    assert _calls("upgrade", "create_table") == []
    # Downgrade reverses exactly those, dropping nothing else.
    assert _calls("downgrade", "drop_column") == ["company_profiles"]
    assert _calls("downgrade", "drop_index") == ["ix_company_profiles_user_id"]
    assert _calls("downgrade", "drop_constraint") == ["fk_company_profiles_user_id"]
    assert _calls("downgrade", "drop_table") == []
    print("OK migration 006 additive + reversible (adds user_id scoping)")


def _main():
    test_industry_scorer()
    test_region_scorer()
    test_budget_scorer()
    test_deadline_scorer()
    test_stage_scorer()
    test_good_fit_scores_high_poor_fit_scores_low()
    test_semantic_dropped_when_no_embeddings()
    test_semantic_similarity_clamped_and_used()
    test_strengths_weaknesses_shape_no_llm()
    test_rank_orders_best_first()
    test_model_schema_route_consistency()
    test_migration_005_additive_and_reversible()
    test_region_no_false_positives()
    test_budget_currency_mismatch_not_perfect()
    test_semantic_drops_on_embedding_exception()
    test_explanation_grounding_guard()
    test_profile_user_scoped()
    test_migration_006_additive_and_reversible()
    print("\nALL PHASE 2 OFFLINE TESTS PASSED")


if __name__ == "__main__":
    _main()
