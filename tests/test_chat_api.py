import pytest
from httpx import ASGITransport, AsyncClient

TOKENS = ["The db.query ", "span is slow."]


@pytest.fixture
def client(monkeypatch):
    from app.api import chat

    async def fake_stream_tokens(message, thread_id="test"):
        for token in TOKENS:
            yield token

    monkeypatch.setattr(chat, "stream_tokens", fake_stream_tokens)

    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_ask_streams_plain_text(client):
    async with client:
        async with client.stream("POST", "/ask", json={"message": "why slow?"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/plain")
            body = "".join([chunk async for chunk in r.aiter_text()])

    assert body == "".join(TOKENS)


async def test_ask_rejects_too_short_message(client):
    async with client:
        response = await client.post("/ask", json={"message": "x"})

    assert response.status_code == 422


async def test_ask_requires_message_field(client):
    async with client:
        response = await client.post("/ask", json={})

    assert response.status_code == 422
