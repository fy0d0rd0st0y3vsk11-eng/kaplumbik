from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.database import db


def utc_now():
    return datetime.now(timezone.utc)


class StreakDay(db.Model):
    __tablename__ = "streak_days"

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), nullable=False, unique=True, index=True)  # YYYY-MM-DD, Europe/Istanbul
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    progress_message_id = db.Column(db.String(25), nullable=True)
    summary_message_id = db.Column(db.String(25), nullable=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    streak_after = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    contributions = db.relationship(
        "StreakContribution", backref="streak_day", cascade="all, delete-orphan", lazy="select"
    )

    __table_args__ = (
        CheckConstraint("status IN ('open', 'completed', 'pending', 'forgiven')", name="ck_streak_day_status"),
        CheckConstraint("streak_after >= 0", name="ck_streak_day_length_nonnegative"),
    )


class StreakContribution(db.Model):
    __tablename__ = "streak_contributions"

    id = db.Column(db.Integer, primary_key=True)
    day_id = db.Column(db.Integer, db.ForeignKey("streak_days.id", ondelete="CASCADE"), nullable=False, index=True)
    discord_id = db.Column(db.String(25), nullable=False)
    first_message_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    source_channel_id = db.Column(db.String(25), nullable=True)
    source_message_id = db.Column(db.String(25), nullable=True)
    correction_note = db.Column(db.String(300), nullable=True)

    __table_args__ = (
        UniqueConstraint("day_id", "discord_id", name="uq_streak_day_member"),
    )
