"""Tests for Turnstile solver."""

import pytest
from cf_bypass.solvers.base import SolverResult, BaseSolver
from cf_bypass.solvers.turnstile import TurnstileSolver


class TestSolverResult:
    """Tests for SolverResult dataclass."""

    def test_defaults(self):
        result = SolverResult()
        assert result.success is False
        assert result.token is None
        assert result.duration == 0.0
        assert result.error is None

    def test_success_with_token(self):
        result = SolverResult(
            token="test-token-123",
            success=True,
            duration=5.5,
        )
        assert result.success is True
        assert result.token == "test-token-123"
        assert result.duration == 5.5

    def test_failure_with_error(self):
        result = SolverResult(
            success=False,
            duration=30.0,
            error="Timeout",
        )
        assert result.success is False
        assert result.error == "Timeout"


class TestBaseSolverAbstract:
    """Verify BaseSolver is properly abstract."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseSolver()  # type: ignore[abstract]


class TestTurnstileSolver:
    """Tests for TurnstileSolver static methods and initialization."""

    def test_default_init(self):
        solver = TurnstileSolver()
        assert solver.name == "turnstile"
        assert solver.api_key == ""
        assert solver.service == "capsolver"

    def test_init_with_api_key(self):
        solver = TurnstileSolver(
            api_key="CAP-TESTKEY",
            service="capsolver",
        )
        assert solver.api_key == "CAP-TESTKEY"
        assert solver.service == "capsolver"

    def test_extract_sitekey_from_data_sitekey(self):
        html = '<div class="cf-turnstile" data-sitekey="0x4AAAAAAABC123"></div>'
        sitekey = TurnstileSolver.extract_sitekey(html)
        assert sitekey == "0x4AAAAAAABC123"

    def test_extract_sitekey_from_inline_js(self):
        html = "<script>turnstile.render('#widget', { sitekey: '0x4AAAAAAAXYZ' })</script>"
        sitekey = TurnstileSolver.extract_sitekey(html)
        assert sitekey == "0x4AAAAAAAXYZ"

    def test_extract_sitekey_from_challenge_div(self):
        html = '<div class="cf-turnstile"></div>'
        sitekey = TurnstileSolver.extract_sitekey(html)
        assert sitekey == "__detected__"

    def test_extract_sitekey_none(self):
        html = "<h1>Normal Page</h1>"
        sitekey = TurnstileSolver.extract_sitekey(html)
        assert sitekey is None

    def test_extract_sitekey_empty_html(self):
        assert TurnstileSolver.extract_sitekey("") is None
        assert TurnstileSolver.extract_sitekey(None) is None  # type: ignore[arg-type]

    def test_is_turnstile_present(self):
        html = '<div class="cf-turnstile" data-sitekey="0x4AAAAAAATEST"></div>'
        assert TurnstileSolver.is_turnstile_present(html) is True

    def test_is_turnstile_present_false(self):
        assert TurnstileSolver.is_turnstile_present("<h1>Hello</h1>") is False
