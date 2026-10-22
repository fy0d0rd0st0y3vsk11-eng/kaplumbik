from datetime import datetime, timezone
from app.database import db

def utc_now():
    return datetime.now(timezone.utc)

class MemberGameProfile(db.Model):
    __tablename__ = "member_game_profiles"
    id=db.Column(db.Integer,primary_key=True)
    discord_id=db.Column(db.String(25),unique=True,nullable=False,index=True)
    games=db.Column(db.JSON,nullable=False,default=list)
    platform=db.Column(db.String(100),nullable=False,default="")
    availability=db.Column(db.String(200),nullable=False,default="")
    voice=db.Column(db.String(30),nullable=False,default="either")
    style=db.Column(db.String(100),nullable=False,default="")
    visible=db.Column(db.Boolean,nullable=False,default=True)
    updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now,onupdate=utc_now)

class CommunityPoll(db.Model):
    __tablename__ = "community_polls"
    id=db.Column(db.Integer,primary_key=True)
    guild_id=db.Column(db.String(25),nullable=False,index=True)
    channel_id=db.Column(db.String(25),nullable=False)
    message_id=db.Column(db.String(25),nullable=True,unique=True)
    creator_id=db.Column(db.String(25),nullable=False)
    question=db.Column(db.String(300),nullable=False)
    options=db.Column(db.JSON,nullable=False)
    status=db.Column(db.String(20),nullable=False,default="open",index=True)
    anonymous=db.Column(db.Boolean,nullable=False,default=False)
    ends_at=db.Column(db.DateTime(timezone=True),nullable=True)
    created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now)

class CommunityPollVote(db.Model):
    __tablename__ = "community_poll_votes"
    id=db.Column(db.Integer,primary_key=True)
    poll_id=db.Column(db.Integer,db.ForeignKey("community_polls.id",ondelete="CASCADE"),nullable=False)
    discord_id=db.Column(db.String(25),nullable=False)
    option_index=db.Column(db.Integer,nullable=False)
    created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint("poll_id","discord_id",name="uq_poll_member_vote"),)

class CommunitySuggestion(db.Model):
    __tablename__ = "community_suggestions"
    id=db.Column(db.Integer,primary_key=True)
    guild_id=db.Column(db.String(25),nullable=False,index=True)
    creator_id=db.Column(db.String(25),nullable=True,index=True)
    anonymous=db.Column(db.Boolean,nullable=False,default=False)
    content=db.Column(db.Text,nullable=False)
    status=db.Column(db.String(20),nullable=False,default="pending",index=True)
    message_id=db.Column(db.String(25),nullable=True)
    created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now)
    updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now,onupdate=utc_now)

class CommunitySuggestionVote(db.Model):
    __tablename__ = "community_suggestion_votes"
    id=db.Column(db.Integer,primary_key=True)
    suggestion_id=db.Column(db.Integer,db.ForeignKey("community_suggestions.id",ondelete="CASCADE"),nullable=False)
    discord_id=db.Column(db.String(25),nullable=False)
    value=db.Column(db.Integer,nullable=False,default=1)
    created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint("suggestion_id","discord_id",name="uq_suggestion_member_vote"),)

class WeeklyQuest(db.Model):
    __tablename__ = "weekly_quests"
    id=db.Column(db.Integer,primary_key=True)
    key=db.Column(db.String(80),unique=True,nullable=False)
    title=db.Column(db.String(120),nullable=False)
    description=db.Column(db.String(300),nullable=False,default="")
    quest_type=db.Column(db.String(30),nullable=False,default="messages")
    target=db.Column(db.Integer,nullable=False,default=1)
    reward_points=db.Column(db.Integer,nullable=False,default=0)
    starts_at=db.Column(db.DateTime(timezone=True),nullable=False,index=True)
    ends_at=db.Column(db.DateTime(timezone=True),nullable=False,index=True)
    enabled=db.Column(db.Boolean,nullable=False,default=True)

class WeeklyQuestProgress(db.Model):
    __tablename__ = "weekly_quest_progress"
    id=db.Column(db.Integer,primary_key=True)
    quest_id=db.Column(db.Integer,db.ForeignKey("weekly_quests.id",ondelete="CASCADE"),nullable=False)
    discord_id=db.Column(db.String(25),nullable=False,index=True)
    progress=db.Column(db.Integer,nullable=False,default=0)
    last_activity_day=db.Column(db.String(10),nullable=True)
    claimed_at=db.Column(db.DateTime(timezone=True),nullable=True)
    updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now,onupdate=utc_now)
    __table_args__=(db.UniqueConstraint("quest_id","discord_id",name="uq_quest_member"),)

class RewardShopItem(db.Model):
    __tablename__ = "reward_shop_items"
    id=db.Column(db.Integer,primary_key=True)
    key=db.Column(db.String(80),unique=True,nullable=False)
    title=db.Column(db.String(120),nullable=False)
    description=db.Column(db.String(300),nullable=False,default="")
    item_type=db.Column(db.String(30),nullable=False,default="cosmetic")
    price=db.Column(db.Integer,nullable=False,default=0)
    discord_role_id=db.Column(db.String(25),nullable=True)
    duration_days=db.Column(db.Integer,nullable=True)
    enabled=db.Column(db.Boolean,nullable=False,default=True)

class MemberCollectionItem(db.Model):
    __tablename__ = "member_collection_items"
    id=db.Column(db.Integer,primary_key=True)
    discord_id=db.Column(db.String(25),nullable=False,index=True)
    item_key=db.Column(db.String(80),nullable=False)
    source=db.Column(db.String(30),nullable=False,default="purchase")
    acquired_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now)
    expires_at=db.Column(db.DateTime(timezone=True),nullable=True)
    __table_args__=(db.UniqueConstraint("discord_id","item_key",name="uq_member_collection_item"),)

class FeaturePermission(db.Model):
    __tablename__ = "feature_permissions"
    id=db.Column(db.Integer,primary_key=True)
    module_key=db.Column(db.String(80),nullable=False,index=True)
    discord_role_id=db.Column(db.String(25),nullable=False)
    can_manage=db.Column(db.Boolean,nullable=False,default=False)
    updated_by=db.Column(db.String(25),nullable=True)
    updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now,onupdate=utc_now)
    __table_args__=(db.UniqueConstraint("module_key","discord_role_id",name="uq_feature_permission_role"),)

class ServerMemoryProposal(db.Model):
    __tablename__ = "server_memory_proposals"
    id=db.Column(db.Integer,primary_key=True)
    guild_id=db.Column(db.String(25),nullable=False,index=True)
    proposer_id=db.Column(db.String(25),nullable=False,index=True)
    content=db.Column(db.String(1000),nullable=False)
    status=db.Column(db.String(20),nullable=False,default="pending",index=True)
    reviewed_by=db.Column(db.String(25),nullable=True)
    created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=utc_now)
    reviewed_at=db.Column(db.DateTime(timezone=True),nullable=True)
