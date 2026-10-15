
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.database import db


def event_utc_now():
    return datetime.now(timezone.utc)


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    game = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=True)

    starts_at = db.Column(
        db.DateTime(timezone=True), nullable=False
    )
    created_by = db.Column(db.String(25), nullable=False)

    status = db.Column(
        db.String(20), nullable=False, default="scheduled"
    )
    game_link = db.Column(db.String(500), nullable=True)
    room_code = db.Column(db.String(100), nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=event_utc_now,
    )

    participations = db.relationship(
        "EventParticipation", backref="event", lazy="select"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'cancelled', 'completed')",
            name="ck_event_status",
        ),
    )


class EventParticipation(db.Model):
    __tablename__ = "event_participation"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.Integer,
        db.ForeignKey("events.id"),
        nullable=False,
    )
    discord_id = db.Column(db.String(25), nullable=False)

    # going, not_going, attended, absent
    status = db.Column(
        db.String(20), nullable=False, default="going"
    )

    reward_approved = db.Column(
        db.Boolean, nullable=False, default=False
    )
    reward_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("economy_transactions.id"),
        nullable=True,
    )

    marked_by = db.Column(db.String(25), nullable=True)
    marked_at = db.Column(
        db.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "discord_id",
            name="uq_event_member",
        ),
        CheckConstraint(
            "status IN ('going', 'not_going', 'attended', 'absent')",
            name="ck_participation_status",
        ),
  )
  
