from types import SimpleNamespace

import pytest

from app.events import assistant_features


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


def install_settings(monkeypatch, model="test/primary", api_key="test-key"):
    monkeypatch.setattr(
        assistant_features,
        "settings",
        SimpleNamespace(openrouter_api_key=api_key, openrouter_model=model),
    )


def test_ai_request_uses_core_personality_and_returns_text(monkeypatch):
    install_settings(monkeypatch)
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse({"choices": [{"message": {"content": "  Selam Mahzen!  "}}]})

    monkeypatch.setattr(assistant_features.requests, "post", fake_post)
    answer = assistant_features._ai_request("Selam", "Biraz daha şakacı ol.")

    assert answer == "Selam Mahzen!"
    messages = captured["json"]["messages"]
    assert "Kaplumbik" in messages[0]["content"]
    assert "Biraz daha şakacı ol." in messages[0]["content"]
    assert messages[1]["content"] == "Selam"
    assert captured["timeout"] == (5, 25)


def test_ai_request_uses_fallback_when_primary_returns_empty(monkeypatch):
    install_settings(monkeypatch, model="custom/primary")
    models = []

    def fake_post(url, **kwargs):
        model = kwargs["json"]["model"]
        models.append(model)
        if model == "custom/primary":
            return FakeResponse({"choices": [{"message": {"content": None}}]})
        return FakeResponse({"choices": [{"message": {"content": "Yedek model burada!"}}]})

    monkeypatch.setattr(assistant_features.requests, "post", fake_post)
    assert assistant_features._ai_request("Bir soru", "") == "Yedek model burada!"
    assert models == ["custom/primary", "openai/gpt-4o-mini"]


def test_ai_request_rejects_empty_final_response(monkeypatch):
    install_settings(monkeypatch, model="openai/gpt-4o-mini")

    monkeypatch.setattr(
        assistant_features.requests,
        "post",
        lambda url, **kwargs: FakeResponse({"choices": [{"message": {"content": None}}]}),
    )
    with pytest.raises(RuntimeError, match="boş yanıt"):
        assistant_features._ai_request("Bir soru", "")


def test_ai_request_requires_api_key(monkeypatch):
    install_settings(monkeypatch, api_key=" ")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        assistant_features._ai_request("Bir soru", "")
