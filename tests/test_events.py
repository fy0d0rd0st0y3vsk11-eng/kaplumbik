
from datetime import datetime, timezone

import pytest

from app import create_app
from app.database import db
from app.database.event_models import Event, EventParticipation
from app.economy.events import approve_event_reward
from app.events.service import (
    EventNotFoundError,
    EventStateError,
    cancel_event,
    create_event,
    record_attendance,
    set_participation,
)


@pytest.fixture
def app():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        }
    )

    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def event(app):
    with app.app_context():
        created = create_event(
            title="Test Among Us",
            game="Among Us",
            starts_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            created_by="987654321",
        )
        event_id = created.id

    return event_id


def test_create_event(app):
    with app.app_context():
        event = create_event(
            title="  Test Game  ",
            game="  Minecraft  ",
            starts_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            created_by="987654321",
        )

        assert event.title == "Test Game"
        assert event.game == "Minecraft"
        assert event.status == "scheduled"


def test_create_event_requires_timezone(app):
    with app.app_context():
        with pytest.raises(ValueError):
            create_event(
                title="Test",
                game="Among Us",
                starts_at=datetime(2030, 1, 1),
                created_by="987654321",
            )


def test_cancel_event_preserves_record(app, event):
    with app.app_context():
        cancelled = cancel_event(event)

        assert cancelled.status == "cancelled"
        assert db.session.get(Event, event) is not None


def test_cannot_cancel_event_twice(app, event):
    with app.app_context():
        cancel_event(event)

        with pytest.raises(EventStateError):
            cancel_event(event)


def test_missing_event_cannot_be_cancelled(app):
    with app.app_context():
        with pytest.raises(EventNotFoundError):
            cancel_event(9999)


def test_member_can_change_rsvp(app, event):
    with app.app_context():
        first = set_participation(event, "123456789", "going")
        assert first.status == "going"

        updated = set_participation(
            event, "123456789", "not_going"
        )
        assert updated.status == "not_going"
        assert EventParticipation.query.count() == 1


def test_member_cannot_mark_themselves_attended(app, event):
    with app.app_context():
        with pytest.raises(ValueError):
            set_participation(event, "123456789", "attended")


def test_attendance_is_recorded_by_manager(app, event):
    with app.app_context():
        participation = record_attendance(
            event_id=event,
            discord_id="123456789",
            status="attended",
            manager_discord_id="987654321",
        )

        assert participation.status == "attended"
        assert participation.marked_by == "987654321"
        assert participation.marked_at is not None


def test_attendance_cannot_be_changed_after_reward(app, event):
    with app.app_context():
        from app.database.models import UserProfile

        db.session.add(
            UserProfile(
                discord_id="123456789",
                username="TestMember",
                balance=0,
            )
        )
        db.session.commit()

        record_attendance(
            event_id=event,
            discord_id="123456789",
            status="attended",
            manager_discord_id="987654321",
        )

        approve_event_reward(
            event_id=event,
            discord_id="123456789",
            manager_discord_id="987654321",
            reward_amount=10,
        )

        with pytest.raises(EventStateError):
            record_attendance(
                event_id=event,
                discord_id="123456789",
                status="absent",
                manager_discord_id="987654321",
)
                                   
