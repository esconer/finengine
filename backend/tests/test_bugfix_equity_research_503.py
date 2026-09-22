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
    assert resp.json()["detail"] == "vendor down"
