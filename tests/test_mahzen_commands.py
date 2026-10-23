from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.database import db
from app.database.advanced_models import Giveaway, GiveawayParticipant


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


def test_giveaway_persists_prize_time_and_participants(app):
    with app.app_context():
        giveaway = Giveaway(
            title="Mahzen oyun gecesi",
            prize="Özel rol",
            description="Aktif üyeler katılabilir.",
            starts_at=datetime.now(timezone.utc) + timedelta(hours=2),
            status="open",
            created_by="12345678901234567",
        )
        db.session.add(giveaway)
        db.session.flush()
        participant = GiveawayParticipant(
            giveaway_id=giveaway.id,
            discord_id="23456789012345678",
        )
        db.session.add(participant)
        db.session.commit()

        saved = db.session.get(Giveaway, giveaway.id)
        assert saved.title == "Mahzen oyun gecesi"
        assert saved.prize == "Özel rol"
        assert len(saved.participants) == 1
        assert saved.participants[0].discord_id == "23456789012345678"


def test_giveaway_prevents_duplicate_entries(app):
    with app.app_context():
        giveaway = Giveaway(
            title="Tek bilet",
            prize="Rozet",
            starts_at=datetime.now(timezone.utc) + timedelta(hours=1),
            status="open",
            created_by="12345678901234567",
        )
        db.session.add(giveaway)
        db.session.flush()
        db.session.add(GiveawayParticipant(
            giveaway_id=giveaway.id,
            discord_id="23456789012345678",
        ))
        db.session.commit()

        db.session.add(GiveawayParticipant(
            giveaway_id=giveaway.id,
            discord_id="23456789012345678",
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_dashboard_local_time_displays_turkey_time():
    from app.dashboard.advanced_routes import _local_time as advanced_local_time
    from app.dashboard.routes import _local_time as main_local_time

    utc_value = datetime(2030, 1, 1, 18, 0, tzinfo=timezone.utc)
    naive_utc_value = datetime(2030, 1, 1, 18, 0)
    assert advanced_local_time(utc_value) == "01.01.2030 21:00"
    assert advanced_local_time(naive_utc_value) == "01.01.2030 21:00"
    assert main_local_time(utc_value) == "01.01.2030 21:00"
    assert main_local_time(naive_utc_value) == "01.01.2030 21:00"


def test_member_intro_is_pending_until_owner_approval(app):
    from app.database.advanced_models import MemberIntro
    with app.app_context():
        row = MemberIntro(guild_id="12345678901234567", discord_id="23456789012345678",
                          name="Fedya", info="Oyun ve kodlama seviyorum.")
        db.session.add(row)
        db.session.commit()
        saved = db.session.get(MemberIntro, row.id)
        assert saved.status == "pending"
        assert saved.reviewed_by is None


def test_directory_only_includes_approved_member_intros(app):
    from app.database.advanced_models import MemberIntro
    from app.events.mahzen_commands import _get_people
    with app.app_context():
        db.session.add(MemberIntro(guild_id="12345678901234567", discord_id="23456789012345678",
                                   name="Bekleyen", info="Bekliyor", status="pending"))
        db.session.add(MemberIntro(guild_id="12345678901234567", discord_id="34567890123456789",
                                   name="Onaylı", info="Tamam", status="approved"))
        db.session.commit()
    people = _get_people("12345678901234567")
    assert any(p["name"] == "Onaylı" for p in people)
    assert not any(p["name"] == "Bekleyen" for p in people)
