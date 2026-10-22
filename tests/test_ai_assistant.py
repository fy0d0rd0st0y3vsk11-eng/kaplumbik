from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import create_app
from app.database import db
from app.database.advanced_models import PersonProfile
from app.events import assistant_features, scheduler
from app.events.feature_service import LEGACY_DAILY_ANNOUNCEMENT, get_setting, set_setting


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
        db.session.add(PersonProfile(name="Ali", info="Bu bilgi yalnızca Ali ile ilgili sorularda görünmeli."))
        db.session.commit()

    knowledge = assistant_features._assistant_knowledge("Mert kim?")
    assert "Mahzen bir oyun topluluğudur." in knowledge
    assert "Mert: Minecraft oynamayı seviyor." in knowledge
    assert "Ada: Gartic Phone oynuyor." not in knowledge

    unrelated_knowledge = assistant_features._assistant_knowledge("Bu kaliteli bir oyun mu?")
    assert "Ali: Bu bilgi yalnızca Ali ile ilgili sorularda görünmeli." not in unrelated_knowledge


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
        lambda key, default="": "Benim duyurum: {title} | {game} | {description} | kod:{room_code}",
    )
    result = scheduler._event_announcement_message(event)
    assert result == "Benim duyurum: Mahzen oyun gecesi | Among Us | Herkes katılabilir. | kod:"
    assert "Katılımını aşağıdaki butonlardan bildir" not in result


def test_final_event_reminder_is_two_hours_not_twelve():
    assert scheduler._reminder_kind(120 * 60, [15, 5]) == "final_2h"
    assert scheduler._reminder_kind(119.5 * 60, [15, 5]) == "final_2h"
    assert scheduler._reminder_kind(118 * 60, [15, 5]) == "final_2h"
    assert scheduler._reminder_kind(117 * 60, [15, 5]) is None
    assert scheduler._reminder_kind(12 * 60 * 60, [15, 5]) is None
    assert scheduler._reminder_kind(0, [1]) is None
    assert scheduler._reminder_kind(-60, [1]) is None


def test_configured_event_reminder_minutes_are_respected():
    assert scheduler._reminder_kind(17 * 60, [15, 5]) == "reminder_15m"
    assert scheduler._reminder_kind(13 * 60, [15, 5]) == "reminder_15m"
    assert scheduler._reminder_kind(15 * 60, [15, 5]) == "reminder_15m"
    assert scheduler._reminder_kind(5 * 60, [15, 5]) == "reminder_5m"
    assert scheduler._reminder_kind(10 * 60, [15, 5]) is None


def test_default_event_template_contains_actual_line_breaks():
    from app.events.feature_service import DEFAULT_SETTINGS

    template = DEFAULT_SETTINGS["event_announcement_template"]
    assert "\n" in template
    assert r"\n" not in template


def test_ai_request_falls_back_when_primary_returns_invalid_json(monkeypatch):
    install_settings(monkeypatch, model="custom/primary")
    models = []

    class InvalidJSONResponse:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("invalid json")

    def fake_post(url, **kwargs):
        model = kwargs["json"]["model"]
        models.append(model)
        if model == "custom/primary":
            return InvalidJSONResponse()
        return FakeResponse({"choices": [{"message": {"content": "Yedek model yanıtı."}}]})

    monkeypatch.setattr(assistant_features.requests, "post", fake_post)
    assert assistant_features._ai_request("Bir soru", "") == "Yedek model yanıtı."
    assert models == ["custom/primary", "openai/gpt-4o-mini"]


def test_daily_announcement_is_disabled_until_owner_writes_text():
    from app.events.feature_service import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["daily_announcement_text"] == ""


def test_legacy_daily_announcement_default_is_disabled(assistant_app):
    with assistant_app.app_context():
        set_setting("daily_announcement_text", LEGACY_DAILY_ANNOUNCEMENT)
        assert get_setting("daily_announcement_text") == ""


def test_daily_announcement_slot_allows_short_retries():
    moment = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert scheduler._due_daily_slot(moment, "12:00,17:00") == "12:00"
    assert scheduler._due_daily_slot(moment.replace(minute=4), "12:00,17:00") == "12:00"
    assert scheduler._due_daily_slot(moment.replace(minute=5), "12:00,17:00") is None
    assert scheduler._due_daily_slot(moment.replace(minute=3), "12:00,12:03") == "12:03"
    assert scheduler._due_daily_slot(moment.replace(minute=2), "bad,12:00") == "12:00"

def test_kaplumbik_meme_triggers_are_deterministic():
    assert assistant_features._is_swearing("bu ne amk")
    assert assistant_features._is_swearing("what the fuck")
    assert assistant_features._is_swearing("siktir git")
    assert not assistant_features._is_swearing("Amınake meme'i")
    assert assistant_features._mentions_ruyar("Ruyar hakkında konuşuyorum")
    assert assistant_features._mentions_ruyar("RUYİŞ pro")
    assert not assistant_features._mentions_ruyar("ruyap hakkında")


def test_conversation_memory_persists_and_isolates_members(assistant_app, monkeypatch):
    from app.database.advanced_models import ConversationMemory
    from app.database.community_models import AIMemoryPreference

    monkeypatch.setattr(assistant_features, "create_app", lambda: assistant_app)
    with assistant_app.app_context():
        for guild_id, member_id in [("guild-1","member-1"),("guild-1","member-2"),("guild-2","member-1")]:
            db.session.add(AIMemoryPreference(guild_id=guild_id,discord_id=member_id,enabled=True))
        db.session.commit()
    assistant_features._save_conversation_memory(
        "guild-1", "channel-1", "member-1", "Fedya", "user", "Dün Among Us oynadık."
    )
    assistant_features._save_conversation_memory(
        "guild-1", "channel-1", "member-1", "Kaplumbik", "assistant", "PUAHAHAHA evet."
    )
    assistant_features._save_conversation_memory(
        "guild-1", "channel-1", "member-2", "Başka üye", "user", "Bu başka üyeye ait."
    )
    assistant_features._save_conversation_memory(
        "guild-2", "channel-2", "member-1", "Fedya", "user", "Bu başka sunucuya ait."
    )

    history = assistant_features._load_conversation_memory("guild-1", "member-1", "Among Us")
    assert "Dün Among Us oynadık." in history
    assert "PUAHAHAHA evet." in history
    assert "Bu başka üyeye ait." not in history
    assert "Bu başka sunucuya ait." not in history

    with assistant_app.app_context():
        assert ConversationMemory.query.count() == 4


def test_conversation_memory_ignores_empty_and_truncates_long_messages(assistant_app, monkeypatch):
    from app.database.advanced_models import ConversationMemory
    from app.database.community_models import AIMemoryPreference

    monkeypatch.setattr(assistant_features, "create_app", lambda: assistant_app)
    with assistant_app.app_context():
        db.session.add(AIMemoryPreference(guild_id="guild-1",discord_id="member-1",enabled=True))
        db.session.commit()
    assistant_features._save_conversation_memory("guild-1", "channel-1", "member-1", "Fedya", "user", "   ")
    assistant_features._save_conversation_memory(
        "guild-1", "channel-1", "member-1", "Fedya", "user", "x" * 4000
    )
    with assistant_app.app_context():
        row = ConversationMemory.query.one()
        assert len(row.content) == 3000


def test_personal_memory_is_off_until_member_opts_in(assistant_app, monkeypatch):
    from app.database.advanced_models import ConversationMemory
    monkeypatch.setattr(assistant_features, "create_app", lambda: assistant_app)
    assistant_features._save_conversation_memory("guild-1","channel-1","member-1","Member","user","Do not persist by default")
    assert assistant_features._load_conversation_memory("guild-1","member-1","anything") == ""
    with assistant_app.app_context():
        assert ConversationMemory.query.count() == 0

def test_ai_request_uses_dashboard_model_override_and_logs_usage(assistant_app, monkeypatch):
    from app.database.advanced_models import BotHealthRecord
    install_settings(monkeypatch, model="env/model")
    monkeypatch.setattr(assistant_features, "create_app", lambda: assistant_app)
    with assistant_app.app_context():
        set_setting("openrouter_model", "dashboard/model")
    captured={}
    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse({
            "choices":[{"message":{"content":"Test yanıtı"}}],
            "usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15,"cost":0.0002},
        })
    monkeypatch.setattr(assistant_features.requests, "post", fake_post)
    assert assistant_features._ai_request("Test", "") == "Test yanıtı"
    assert captured["json"]["model"] == "dashboard/model"
    with assistant_app.app_context():
        row=BotHealthRecord.query.filter_by(component="ai_usage",status="ok").one()
        assert "model=dashboard/model" in row.details
        assert "total_tokens=15" in row.details
        assert "cost=0.0002" in row.details
