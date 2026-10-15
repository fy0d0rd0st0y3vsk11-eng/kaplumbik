
import pytest

from app import create_app
from app.database import db
from app.database.models import (
    EconomyTransaction,
    UserProfile,
)
from app.economy.service import (
    DuplicateTransactionError,
    InsufficientFundsError,
    adjust_balance,
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

        db.session.add(
            UserProfile(
                discord_id="123456789",
                username="TestMember",
                balance=100,
            )
        )
        db.session.commit()

        yield application

        db.session.remove()
        db.drop_all()


def test_add_coins_and_record_transaction(app):
    with app.app_context():
        transaction = adjust_balance(
            discord_id="123456789",
            amount=25,
            transaction_type="test_reward",
            description="Test reward",
            idempotency_key="reward-test-001",
        )

        profile = UserProfile.query.filter_by(
            discord_id="123456789"
        ).one()

        assert profile.balance == 125
        assert transaction.amount == 25
        assert transaction.balance_after == 125


def test_reject_overspending(app):
    with app.app_context():
        with pytest.raises(InsufficientFundsError):
            adjust_balance(
                discord_id="123456789",
                amount=-101,
                transaction_type="test_purchase",
                description="Too expensive",
            )

        profile = UserProfile.query.filter_by(
            discord_id="123456789"
        ).one()

        assert profile.balance == 100
        assert EconomyTransaction.query.count() == 0


def test_reject_duplicate_reward(app):
    with app.app_context():
        arguments = {
            "discord_id": "123456789",
            "amount": 10,
            "transaction_type": "event_reward",
            "description": "Event attendance",
            "idempotency_key": "event-42-user-123456789",
        }

        adjust_balance(**arguments)

        with pytest.raises(DuplicateTransactionError):
            adjust_balance(**arguments)

        profile = UserProfile.query.filter_by(
            discord_id="123456789"
        ).one()

        assert profile.balance == 110
        assert EconomyTransaction.query.count() == 1
          
