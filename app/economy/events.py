
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

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
)


class EventRewardError(EconomyError):
    pass


def approve_event_reward(
    event_id: int,
    discord_id: str,
    manager_discord_id: str,
    reward_amount: int,
) -> EconomyTransaction:
    """Approve attendance and award coins in one transaction."""

    if (
        isinstance(reward_amount, bool)
        or not isinstance(reward_amount, int)
        or reward_amount <= 0
    ):
        raise ValueError("Reward amount must be a positive integer.")

    discord_id = str(discord_id)
    manager_discord_id = str(manager_discord_id)
    idempotency_key = f"event-reward-{event_id}-{discord_id}"

    try:
        event = db.session.get(Event, event_id)

        if event is None:
            raise EventRewardError("Event not found.")

        participation = db.session.execute(
            select(EventParticipation)
            .where(
                EventParticipation.event_id == event_id,
                EventParticipation.discord_id == discord_id,
            )
            .with_for_update()
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

        existing = db.session.execute(
            select(EconomyTransaction).where(
                EconomyTransaction.idempotency_key
                == idempotency_key
            )
        ).scalar_one_or_none()

        if existing is not None:
            raise EventRewardError(
                "A reward transaction already exists."
            )

        profile = db.session.execute(
            select(UserProfile)
            .where(UserProfile.discord_id == discord_id)
            .with_for_update()
        ).scalar_one_or_none()

        if profile is None:
            raise UserNotFoundError("Member profile not found.")

        new_balance = profile.balance + reward_amount

        transaction = EconomyTransaction(
            user_id=profile.id,
            amount=reward_amount,
            balance_after=new_balance,
            transaction_type="event_reward",
            description=f"Attendance reward for event #{event_id}",
            actor_discord_id=manager_discord_id,
            reference_type="event",
            reference_id=str(event_id),
            idempotency_key=idempotency_key,
        )

        profile.balance = new_balance
        participation.reward_approved = True
        participation.reward_transaction_id = None
        participation.marked_by = manager_discord_id

        db.session.add(transaction)
        db.session.flush()

        participation.reward_transaction_id = transaction.id

        # Both the balance and approval are committed together.
        db.session.commit()

        return transaction

    except IntegrityError as exc:
        db.session.rollback()
        raise EventRewardError(
            "The reward conflicted with another database change. "
            "Check the transaction history before retrying."
        ) from exc

    except Exception:
        db.session.rollback()
        raise
        
