from types import SimpleNamespace

import pytest

from app import create_app
from app.database import db
from app.database.advanced_models import PersonProfile
from app.events import assistant_features, scheduler
from app.events.feature_service import set_setting


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
    answer = assistant_features._ai_request("Selam", "Biraz daha şakacı ol.", "Mahzen bilgisi: oyun sunucusu")

    assert answer == "Selam Mahzen!"
    messages = captured["json"]["messages"]
    assert "Kaplumbik" in messages[0]["content"]
    assert "Biraz daha şakacı ol." in messages[0]["content"]
    assert "Mahzen bilgisi: oyun sunucusu" in messages[0]["content"]
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


@pytest.fixture
def assistant_app():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
    })
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def test_assistant_knowledge_only_includes_matching_person(assistant_app, monkeypatch):
    monkeypatch.setattr(assistant_features, "create_app", lambda: assistant_app)
    with assistant_app.app_context():
        set_setting("server_knowledge", "Mahzen bir oyun topluluğudur.")
        db.session.add(PersonProfile(name="Mert", info="Minecraft oynamayı seviyor."))
        db.session.add(PersonProfile(name="Ada", info="Gartic Phone oynuyor."))
        db.session.commit()

    knowledge = assistant_features._assistant_knowledge("Mert kim?")
    assert "Mahzen bir oyun topluluğudur." in knowledge
    assert "Mert: Minecraft oynamayı seviyor." in knowledge
    assert "Ada: Gartic Phone oynuyor." not in knowledge


def test_event_announcement_uses_owner_written_template(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    event = SimpleNamespace(
        title="Mahzen oyun gecesi",
        game="Among Us",
        starts_at=datetime(2030, 1, 1, 18, 0, tzinfo=timezone.utc),
        description="Herkes katılabilir.",
        game_link="https://example.com/game",
        room_code="ABCD",
    )
    monkeypatch.setattr(
        scheduler,
        "_read_setting",
        lambda key, default="": "Benim duyurum: {title} | {game} | {description}",
    )
    result = scheduler._event_announcement_message(event)
    assert result == "Benim duyurum: Mahzen oyun gecesi | Among Us | Herkes katılabilir."
    assert "Katılımını aşağıdaki butonlardan bildir" not in result


def test_final_event_reminder_is_two_hours_not_twelve():
    assert scheduler._reminder_kind(120 * 60, [15, 5]) == "final_2h"
    assert scheduler._reminder_kind(119.5 * 60, [15, 5]) == "final_2h"
    assert scheduler._reminder_kind(12 * 60 * 60, [15, 5]) is None


def test_configured_event_reminder_minutes_are_respected():
    assert scheduler._reminder_kind(15 * 60, [15, 5]) == "reminder_15m"
    assert scheduler._reminder_kind(5 * 60, [15, 5]) == "reminder_5m"
    assert scheduler._reminder_kind(10 * 60, [15, 5]) is None
