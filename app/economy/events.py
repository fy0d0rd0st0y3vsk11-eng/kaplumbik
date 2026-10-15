
from sqlalchemy import select

from app.database import db
from app.database.models import (
    EconomyTransaction,
    UserProfile,
)
from app.database.event_models import (
    Event,
    EventParticipation,
)
from app.economy.service import (
    EconomyError,
    UserNotFoundError,
    adjust_balance,
)


class EventRewardError(EconomyError):
    pass


def approve_event_reward(
    event_id: int,
    discord_id: str,
    manager_discord_id: str,
    reward_amount: int,
) -> EconomyTransaction:
    """Award event coins only after attendance is approved."""

    if reward_amount <= 0:
        raise ValueError("Reward amount must be positive.")

    try:
        event = db.session.get(Event, event_id)
        if event is None:
            raise EventRewardError("Event not found.")

        participation = db.session.execute(
            select(EventParticipation).where(
                EventParticipation.event_id == event_id,
                EventParticipation.discord_id == str(discord_id),
            )
        ).scalar_one_or_none()

        if participation is None:
            raise EventRewardError(
                "Member has no participation record."
            )

        if participation.status != "attended":
            raise EventRewardError(
                "Attendance must be confirmed before rewarding."
            )

        if participation.reward_approved:
            raise EventRewardError(
                "This attendance reward was already approved."
            )

        profile = db.session.execute(
            select(UserProfile).where(
                UserProfile.discord_id == str(discord_id)
            )
        ).scalar_one_or_none()

        if profile is None:
            raise UserNotFoundError("Member profile not found.")

        transaction = adjust_balance(
            discord_id=str(discord_id),
            amount=reward_amount,
            transaction_type="event_reward",
            description=f"Attendance reward for event #{event_id}",
            actor_discord_id=str(manager_discord_id),
            idempotency_key=(
                f"event-reward-{event_id}-{discord_id}"
            ),
        )

        participation.reward_approved = True
        participation.reward_transaction_id = transaction.id
        participation.marked_by = str(manager_discord_id)

        db.session.commit()
        return transaction

    except Exception:
        db.session.rollback()
        raise
      
