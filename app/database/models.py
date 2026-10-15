
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index

from . import db


def utc_now():
    return datetime.now(timezone.utc)


class UserProfile(db.Model):
    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    discord_id = db.Column(db.String(25), unique=True, nullable=False)
    username = db.Column(db.String(100), nullable=True)

    balance = db.Column(
        db.Integer, nullable=False, default=0
    )
    total_event_points = db.Column(
        db.Integer, nullable=False, default=0
    )
    xp = db.Column(db.Integer, nullable=False, default=0)
    level = db.Column(db.Integer, nullable=False, default=1)

    joined_at = db.Column(
        db.DateTime(timezone=True), nullable=True
    )
    last_event_at = db.Column(
        db.DateTime(timezone=True), nullable=True
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        CheckConstraint(
            "balance >= 0",
            name="ck_user_balance_nonnegative",
        ),
        CheckConstraint(
            "total_event_points >= 0",
            name="ck_user_event_points_nonnegative",
        ),
        CheckConstraint("xp >= 0", name="ck_user_xp_nonnegative"),
        CheckConstraint("level >= 1", name="ck_user_level_positive"),
    )


class EconomyTransaction(db.Model):
    __tablename__ = "economy_transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user_profiles.id"),
        nullable=False,
        index=True,
    )

    # positive = credit, negative = debit
    amount = db.Column(db.Integer, nullable=False)
    balance_after = db.Column(db.Integer, nullable=False)

    transaction_type = db.Column(
        db.String(40), nullable=False
    )
    description = db.Column(db.String(300), nullable=False)

    actor_discord_id = db.Column(db.String(25), nullable=True)
    reference_type = db.Column(db.String(40), nullable=True)
    reference_id = db.Column(db.String(100), nullable=True)

    # Prevents the same reward from being recorded twice.
    idempotency_key = db.Column(
        db.String(150), unique=True, nullable=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )

    user = db.relationship("UserProfile", backref="transactions")

    __table_args__ = (
        CheckConstraint(
            "balance_after >= 0",
            name="ck_transaction_balance_nonnegative",
        ),
        Index(
            "ix_transaction_user_created",
            "user_id",
            "created_at",
        ),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_discord_id = db.Column(
        db.String(25), nullable=True, index=True
    )
    action = db.Column(db.String(100), nullable=False)
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.String(100), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    success = db.Column(
        db.Boolean, nullable=False, default=True
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
  )
  
