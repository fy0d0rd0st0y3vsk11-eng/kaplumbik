from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy.exc import IntegrityError
from app import create_app
from app.database import db
from app.database.community_models import CommunityPoll, CommunityPollVote, CommunitySuggestion, CommunitySuggestionVote, MemberGameProfile, RewardShopItem, WeeklyQuest, WeeklyQuestProgress

@pytest.fixture
def app():
    application=create_app({"TESTING":True,"SECRET_KEY":"test-only-secret","SQLALCHEMY_DATABASE_URI":"sqlite://"})
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove(); db.drop_all()

def test_member_game_profile_is_unique_per_member(app):
    with app.app_context():
        db.session.add(MemberGameProfile(discord_id="123",games=["Among Us"],platform="mobile")); db.session.commit()
        db.session.add(MemberGameProfile(discord_id="123",games=["Minecraft"],platform="PC"))
        with pytest.raises(IntegrityError): db.session.commit()
        db.session.rollback()
        row=MemberGameProfile.query.filter_by(discord_id="123").one()
        assert row.games==["Among Us"]

def test_poll_allows_one_changeable_vote_per_member(app):
    with app.app_context():
        poll=CommunityPoll(guild_id="1",channel_id="2",creator_id="3",question="Which game?",options=["A","B"],ends_at=datetime.now(timezone.utc)+timedelta(hours=1))
        db.session.add(poll); db.session.commit()
        db.session.add(CommunityPollVote(poll_id=poll.id,discord_id="4",option_index=0)); db.session.commit()
        vote=CommunityPollVote.query.filter_by(poll_id=poll.id,discord_id="4").one(); vote.option_index=1; db.session.commit()
        assert CommunityPollVote.query.filter_by(poll_id=poll.id,discord_id="4").count()==1
        assert vote.option_index==1

def test_suggestion_vote_is_unique_per_member(app):
    with app.app_context():
        suggestion=CommunitySuggestion(guild_id="1",creator_id="2",anonymous=True,content="Add another game night")
        db.session.add(suggestion); db.session.commit()
        db.session.add(CommunitySuggestionVote(suggestion_id=suggestion.id,discord_id="3",value=1)); db.session.commit()
        vote=CommunitySuggestionVote.query.filter_by(suggestion_id=suggestion.id,discord_id="3").one(); vote.value=-1; db.session.commit()
        assert CommunitySuggestionVote.query.filter_by(suggestion_id=suggestion.id,discord_id="3").count()==1
        assert vote.value==-1

def test_weekly_quest_progress_is_unique_per_member(app):
    with app.app_context():
        now=datetime.now(timezone.utc)
        quest=WeeklyQuest(key="week1",title="Chat",quest_type="messages",target=10,reward_points=20,starts_at=now,ends_at=now+timedelta(days=7))
        db.session.add(quest); db.session.commit()
        db.session.add(WeeklyQuestProgress(quest_id=quest.id,discord_id="3",progress=1)); db.session.commit()
        db.session.add(WeeklyQuestProgress(quest_id=quest.id,discord_id="3",progress=2))
        with pytest.raises(IntegrityError): db.session.commit()
        db.session.rollback()
        assert WeeklyQuestProgress.query.filter_by(quest_id=quest.id,discord_id="3").count()==1

def test_expiry_checks_accept_sqlite_naive_datetimes():
    from app.events.community import as_utc, is_expired
    naive_past=datetime(2020,1,1)
    assert as_utc(naive_past).tzinfo is timezone.utc
    assert is_expired(naive_past)
    assert not is_expired(datetime.now(timezone.utc)+timedelta(days=1))
