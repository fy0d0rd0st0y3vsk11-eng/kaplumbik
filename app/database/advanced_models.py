from datetime import datetime, timezone

from app.database import db


def utc_now():
    return datetime.now(timezone.utc)


class BotSetting(db.Model):
    __tablename__ = "bot_settings"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")
    updated_by = db.Column(db.String(25), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class AchievementDefinition(db.Model):
    __tablename__ = "achievement_definitions"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), unique=True, nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300), nullable=False, default="")
    condition_type = db.Column(db.String(40), nullable=False, default="events_attended")
    threshold = db.Column(db.Integer, nullable=False, default=1)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class AnnouncementLog(db.Model):
    __tablename__ = "announcement_logs"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=True, index=True)
    channel_id = db.Column(db.String(25), nullable=True)
    kind = db.Column(db.String(40), nullable=False)
    message = db.Column(db.Text, nullable=False)
    success = db.Column(db.Boolean, nullable=False, default=False)
    error = db.Column(db.String(500), nullable=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, index=True)


class BotHealthRecord(db.Model):
    __tablename__ = "bot_health_records"

    id = db.Column(db.Integer, primary_key=True)
    component = db.Column(db.String(60), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False)
    details = db.Column(db.String(500), nullable=True)
    checked_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, index=True)


class PersonProfile(db.Model):
    """Owner-maintained public/member intro facts for Kaplumbik's Q&A."""
    __tablename__ = "person_profiles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    info = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class Giveaway(db.Model):
    """Mahzen-only giveaway controlled by the owner dashboard."""
    __tablename__ = "mahzen_giveaways"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    prize = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    winner_discord_id = db.Column(db.String(25), nullable=True)
    created_by = db.Column(db.String(25), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)

    participants = db.relationship(
        "GiveawayParticipant",
        backref="giveaway",
        cascade="all, delete-orphan",
        lazy="select",
    )


class GiveawayParticipant(db.Model):
    """A single Discord account's entry in one Mahzen giveaway."""
    __tablename__ = "mahzen_giveaway_participants"

    id = db.Column(db.Integer, primary_key=True)
    giveaway_id = db.Column(
        db.Integer,
        db.ForeignKey("mahzen_giveaways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    discord_id = db.Column(db.String(25), nullable=False)
    joined_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint("giveaway_id", "discord_id", name="uq_mahzen_giveaway_member"),
    )
