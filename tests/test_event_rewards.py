
import pytest

from app import create_app
from app.database import db
from app.database.models import UserProfile, EconomyTransaction
from app.database.event_models import Event, EventParticipation
from app.economy.events import (
    EventRewardError,
    approve_event_reward,
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

        member = UserProfile(
            discord_id="123456789",
            username="TestMember",
            balance=50,
        )
        event = Event(
            title="Test Among Us",
            game="Among Us",
            starts_at=__import__("datetime").datetime(
                2030, 1, 1
            ),
            created_by="987654321",
        )

        db.session.add_all([member, event])
        db.session.flush()

        db.session.add(
            EventParticipation(
                event_id=event.id,
                discord_id=member.discord_id,
                status="going",
            )
        )
        db.session.commit()

        yield application

        db.session.remove()
        db.drop_all()


def test_reward_requires_confirmed_attendance(app):
    with app.app_context():
        with pytest.raises(EventRewardError):
            approve_event_reward(
                event_id=1,
                discord_id="123456789",
                manager_discord_id="987654321",
                reward_amount=10,
            )

        profile = UserProfile.query.filter_by(
            discord_id="123456789"
        ).one()
        assert profile.balance == 50
        assert EconomyTransaction.query.count() == 0


def test_confirmed_attendance_can_be_rewarded_once(app):
    with app.app_context():
        participation = EventParticipation.query.one()
        participation.status = "attended"
        db.session.commit()

        transaction = approve_event_reward(
            event_id=1,
            discord_id="123456789",
            manager_discord_id="987654321",
            reward_amount=10,
        )

        assert transaction.amount == 10

        profile = UserProfile.query.filter_by(
            discord_id="123456789"
        ).one()
        assert profile.balance == 60

        with pytest.raises(EventRewardError):
            approve_event_reward(
                event_id=1,
                discord_id="123456789",
                manager_discord_id="987654321",
                reward_amount=10,
            )

        assert profile.balance == 60
        assert EconomyTransaction.query.count() == 1
