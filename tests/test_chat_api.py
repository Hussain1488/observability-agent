import json

import pytest
from httpx import ASGITransport, AsyncClient

EVENTS = [
    {"type": "route", "agent": "traces"},
    {"type": "tool_call", "tool": "get_trace", "args": {"service": "checkout"}},
    {"type": "tool_result", "tool": "get_trace", "content": "db.query 1450ms"},
    {"type": "token", "text": "The db.query "},
    {"type": "token", "text": "span is slow."},
]


@pytest.fixture
def client(monkeypatch):
    from app.api import chat

    async def fake_stream_chat(message, thread_id="test"):
        for event in EVENTS:
            yield event

    monkeypatch.setattr(chat, "stream_chat", fake_stream_chat)

    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_chat_streams_all_events(client):
    async with client:
        async with client.stream("POST", "/chat", json={"message": "why slow?"}) as r:
            assert r.status_code == 200
            body = "".join([chunk async for chunk in r.aiter_text()])

    received = [json.loads(line) for line in body.splitlines() if line.strip()]
    assert received == EVENTS


async def test_chat_rejects_too_short_message(client):
    async with client:
        response = await client.post("/chat", json={"message": "x"})

    assert response.status_code == 422


async def test_chat_requires_message_field(client):
    async with client:
        response = await client.post("/chat", json={})

    assert response.status_code == 422
