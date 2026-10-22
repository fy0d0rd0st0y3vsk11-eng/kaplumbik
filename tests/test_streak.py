from datetime import date, timedelta

import pytest

from app import create_app
from app.database import db
from app.seri.models import StreakContribution, StreakDay
from app.seri.service import (
    close_day,
    contribution_count,
    make_up_pending_days,
    record_contribution,
)


@pytest.fixture
def app():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
    })
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def test_one_member_counts_only_once_per_day(app):
    with app.app_context():
        day = date(2026, 10, 20)
        first, created = record_contribution(day, "11111111111111111", "222", "msg-1")
        again, added_again = record_contribution(day, "11111111111111111", "222", "msg-2")
        assert created is True
        assert added_again is False
        assert first.id == again.id
        assert contribution_count(first) == 1
        assert StreakContribution.query.count() == 1


def test_three_distinct_members_complete_day_once(app):
    with app.app_context():
        day = date(2026, 10, 20)
        for i in range(3):
            record_contribution(day, str(11111111111111111 + i), "222", f"msg-{i}")
        row, newly_closed = close_day(day)
        assert newly_closed is True
        assert row.status == "completed"
        assert row.streak_after == 1
        same_row, closed_again = close_day(day)
        assert same_row.id == row.id
        assert closed_again is False
        assert StreakDay.query.count() == 1


def test_missed_day_stays_pending_until_makeup(app):
    with app.app_context():
        day = date(2026, 10, 20)
        record_contribution(day, "11111111111111111", "222", "msg-1")
        row, _ = close_day(day)
        assert row.status == "pending"
        made_up = make_up_pending_days(1, "99999999999999999")
        assert [item.day for item in made_up] == [day.isoformat()]
        assert row.status == "forgiven"
        assert row.streak_after == 1


def test_makeup_cannot_repeat_a_resolved_day(app):
    with app.app_context():
        day = date(2026, 10, 20)
        close_day(day)
        make_up_pending_days(1, "99999999999999999")
        with pytest.raises(ValueError):
            make_up_pending_days(1, "99999999999999999")

def test_successful_streak_awards_each_contributor_once(app):
    from app.database.models import UserProfile, EconomyTransaction
    with app.app_context():
        day = date(2026, 10, 21)
        for i in range(3):
            record_contribution(day, str(21111111111111111 + i), "222", f"reward-msg-{i}")
        row, _ = close_day(day)
        assert row.status == "completed"
        profiles = UserProfile.query.order_by(UserProfile.discord_id).all()
        assert len(profiles) == 3
        assert [profile.balance for profile in profiles] == [5, 5, 5]
        assert EconomyTransaction.query.filter_by(transaction_type="shared_streak_reward").count() == 3
        close_day(day)
        assert EconomyTransaction.query.filter_by(transaction_type="shared_streak_reward").count() == 3

def test_streak_tracking_starts_only_after_both_channel_settings(app):
    from app.database.advanced_models import BotSetting
    from app.seri.service import ensure_tracking_started_date, set_channel_id, set_source_channel
    with app.app_context():
        assert ensure_tracking_started_date("owner") == ""
        set_channel_id("300", "owner")
        assert db.session.get(BotSetting, "streak_tracking_started_date") is None
        set_source_channel("400", True, "owner")
        row = db.session.get(BotSetting, "streak_tracking_started_date")
        assert row is not None
        assert row.value == date.today().isoformat() or len(row.value) == 10
