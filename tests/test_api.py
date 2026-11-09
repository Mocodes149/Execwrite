import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from execwrite.main import MAX_WORDS, app, get_client
from execwrite.rewriter import ADJUSTMENTS, model_options


class FakeStream:
    def __init__(self, chunks, stop_reason, error):
        self._chunks = chunks
        self._stop_reason = stop_reason
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    @property
    async def text_stream(self):
        for chunk in self._chunks:
            yield chunk
        if self._error:
            raise self._error

    async def get_final_message(self):
        return SimpleNamespace(stop_reason=self._stop_reason)


class FakeClient:
    def __init__(self, chunks=("Bonjour", " monde"), stop_reason="end_turn", error=None):
        self.messages = self
        self.calls = []
        self._args = (list(chunks), stop_reason, error)

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(*self._args)


@pytest.fixture
def use_client():
    def install(client):
        app.dependency_overrides[get_client] = lambda: client
        return client

    yield install
    app.dependency_overrides.clear()


http = TestClient(app)


def post(**body):
    return http.post("/api/rewrite", json=body)


def events(response):
    return [json.loads(line) for line in response.text.splitlines()]


def status_error(cls, status):
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.test"))
    return cls("erreur", response=response, body=None)


def test_index_is_served():
    response = http.get("/")
    assert response.status_code == 200
    assert "Reformuler" in response.text


def test_streams_chunks_then_done(use_client):
    use_client(FakeClient())
    response = post(text="Un brouillon")
    assert response.status_code == 200
    assert events(response) == [
        {"type": "delta", "text": "Bonjour"},
        {"type": "delta", "text": " monde"},
        {"type": "done"},
    ]


def test_draft_is_delimited_for_the_model(use_client):
    client = use_client(FakeClient())
    post(text="Un brouillon")
    assert client.calls[0]["messages"] == [
        {"role": "user", "content": "<brouillon>\nUn brouillon\n</brouillon>"}
    ]


def test_adjustment_replays_draft_and_previous_version(use_client):
    client = use_client(FakeClient())
    post(text="Un brouillon", adjustment="shorter", previous="Version 1")
    messages = client.calls[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"] == "Version 1"
    assert messages[2]["content"] == ADJUSTMENTS["shorter"]


def test_accepts_exactly_the_word_limit(use_client):
    use_client(FakeClient())
    assert post(text=" ".join(["mot"] * MAX_WORDS)).status_code == 200


def test_rejects_text_over_the_word_limit(use_client):
    client = use_client(FakeClient())
    response = post(text=" ".join(["mot"] * (MAX_WORDS + 1)))
    assert response.status_code == 422
    assert client.calls == []


@pytest.mark.parametrize("text", ["", "   \n "])
def test_rejects_blank_text(use_client, text):
    use_client(FakeClient())
    assert post(text=text).status_code == 422


def test_rejects_adjustment_without_previous_version(use_client):
    use_client(FakeClient())
    assert post(text="Un brouillon", adjustment="direct").status_code == 422


def test_rejects_unknown_adjustment(use_client):
    use_client(FakeClient())
    assert post(text="Un brouillon", adjustment="poétique", previous="V1").status_code == 422


def test_missing_api_key_is_reported(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_client.cache_clear()
    response = post(text="Un brouillon")
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [("refusal", "pas pu être reformulé"), ("max_tokens", "trop long")],
)
def test_incomplete_results_end_with_an_error(use_client, stop_reason, expected):
    use_client(FakeClient(stop_reason=stop_reason))
    last = events(post(text="Un brouillon"))[-1]
    assert last["type"] == "error"
    assert expected in last["message"]


@pytest.mark.parametrize(
    ("cls", "status", "expected"),
    [
        (anthropic.AuthenticationError, 401, "clé API"),
        (anthropic.RateLimitError, 429, "Trop de demandes"),
        (anthropic.InternalServerError, 500, "Réessayez"),
    ],
)
def test_api_errors_become_user_messages(use_client, cls, status, expected):
    use_client(FakeClient(error=status_error(cls, status)))
    last = events(post(text="Un brouillon"))[-1]
    assert last["type"] == "error"
    assert expected in last["message"]


def test_thinking_is_disabled_only_where_the_api_allows_it():
    assert model_options("claude-haiku-5-5")["thinking"] == {"type": "disabled"}
    assert "thinking" not in model_options("claude-opus-5-5")
    assert "thinking" not in model_options("claude-sonnet-5-5")


def test_real_sdk_accepts_the_request_and_parses_the_stream(use_client):
    """Passe par le vrai SDK, seul le réseau est simulé."""
    captured = {}

    def sse(event, data):
        return f"event: {event}\ndata: {json.dumps({'type': event, **data})}\n\n"

    usage = {"input_tokens": 1, "output_tokens": 1}
    body = "".join(
        [
            sse(
                "message_start",
                {
                    "message": {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-haiku-5-5",
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": usage,
                    }
                },
            ),
            sse("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
            sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Net"}}),
            sse("content_block_stop", {"index": 0}),
            sse("message_delta", {"delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": usage}),
            sse("message_stop", {}),
        ]
    )

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    use_client(
        anthropic.AsyncAnthropic(
            api_key="test",
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )
    )
    assert events(post(text="Un brouillon")) == [
        {"type": "delta", "text": "Net"},
        {"type": "done"},
    ]
    assert captured["body"]["model"] == "claude-haiku-5-5"
    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert captured["body"]["output_config"] == {"effort": "low"}
