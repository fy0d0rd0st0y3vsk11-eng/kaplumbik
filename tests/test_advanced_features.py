from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.database import db
from app.database.advanced_models import AchievementDefinition, BotHealthRecord, BotSetting
from app.database.models import AuditLog
from app.database.event_models import Event
from app.events.feature_service import get_setting, get_rsvp_summary, record_health, seed_achievements, set_setting
from app.events.service import EventStateError, create_event, set_participation


@pytest.fixture
def app():
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


def test_default_setting_is_available(app):
    with app.app_context():
        assert "Kaplumbik" in get_setting("ai_personality")


def test_setting_can_be_saved_and_updated(app):
    with app.app_context():
        set_setting("minecraft_realms_link", "https://example.com/realm", "12345678901234567")
        assert get_setting("minecraft_realms_link") == "https://example.com/realm"
        set_setting("minecraft_realms_link", "https://example.com/new", "12345678901234567")
        assert get_setting("minecraft_realms_link") == "https://example.com/new"
        assert BotSetting.query.count() == 1


def test_rsvp_summary_updates_live_counts(app):
    with app.app_context():
        event = create_event(
            title="Test event",
            game="Among Us",
            starts_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            created_by="12345678901234567",
        )
        set_participation(event.id, "11111111111111111", "going")
        set_participation(event.id, "22222222222222222", "not_going")
        summary = get_rsvp_summary(event.id)
        assert summary["going"] == ["11111111111111111"]
        assert summary["not_going"] == ["22222222222222222"]


def test_default_achievements_seed_once(app):
    with app.app_context():
        seed_achievements()
        seed_achievements()
        assert AchievementDefinition.query.count() == 5


def test_health_records_are_stored(app):
    with app.app_context():
        record_health("ai", "error", "test error")
        row = BotHealthRecord.query.one()
        assert row.component == "ai"
        assert row.status == "error"
        assert row.details == "test error"



def test_last_minute_cancellation_is_audited(app):
    with app.app_context():
        event = create_event(
            title="Soon event",
            game="Among Us",
            starts_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            created_by="12345678901234567",
        )
        set_participation(event.id, "33333333333333333", "going")
        set_participation(event.id, "33333333333333333", "not_going")
        log = AuditLog.query.filter_by(action="event.rsvp_late_cancel").one()
        assert log.target_id == f"{event.id}:33333333333333333"



def test_first_time_decline_is_not_a_late_cancellation(app):
    with app.app_context():
        event = create_event(
            title="Soon event",
            game="Among Us",
            starts_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            created_by="12345678901234567",
        )
        set_participation(event.id, "44444444444444444", "not_going")
        assert AuditLog.query.filter_by(action="event.rsvp_late_cancel").count() == 0



def test_rsvp_changes_close_after_event_start(app):
    with app.app_context():
        event = create_event(
            title="Started event",
            game="Among Us",
            starts_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            created_by="12345678901234567",
        )
        with pytest.raises(EventStateError, match="katılım yanıtları kapandı"):
            set_participation(event.id, "55555555555555555", "going")
