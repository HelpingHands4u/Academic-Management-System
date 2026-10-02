import httpx
import pytest

from app.main import app


@pytest.mark.anyio
async def test_health_endpoint_returns_expected_payload() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "Brainware University Academic Management Portal",
        }


@pytest.mark.anyio
async def test_docs_endpoint_is_available() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/docs")

        assert response.status_code == 200
        assert "Swagger UI" in response.text


@pytest.mark.anyio
async def test_redoc_endpoint_is_available() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/redoc")

        assert response.status_code == 200
        assert "ReDoc" in response.text
