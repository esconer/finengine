"""Regression: vendor-failure RuntimeError in equity_research routes -> 503."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import equity_research as er_mod


@pytest.mark.api
@pytest.mark.asyncio
async def test_full_profile_runtime_error_maps_to_503():
    from main import app

    mock_svc = Mock()
    mock_svc.get_full_profile = AsyncMock(side_effect=RuntimeError("vendor down"))
    transport = ASGITransport(app=app)
    with patch.object(er_mod, "get_equity_research_service", return_value=mock_svc):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/company/RELIANCE/full-profile")
    assert resp.status_code == 503
    # `_raise_provider_http_error` deliberately does NOT pass the upstream
    # message through: its docstring is "Translate typed provider failures
    # without exposing upstream details", and an untyped RuntimeError falls to
    # the `unknown` branch, "Upstream data service unavailable". This test used
    # to assert the raw vendor string came back, which contradicted that intent
    # and sat red in the baseline for the whole session.
    #
    # So assert the property the code is actually written to provide: a 503, a
    # sanitised detail, and NO trace of the upstream text. The last assertion is
    # the one worth having -- it is what stops someone "fixing" the mapping by
    # echoing the exception back to the client.
    detail = resp.json()["detail"]
    assert detail == "Upstream data service unavailable"
    assert "vendor down" not in detail
    assert "RuntimeError" not in detail
