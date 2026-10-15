
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import db
from app.database.models import (
    EconomyTransaction,
    UserProfile,
)


class EconomyError(Exception):
    """Base exception for economy operations."""


class UserNotFoundError(EconomyError):
    pass


class InsufficientFundsError(EconomyError):
    pass


class DuplicateTransactionError(EconomyError):
    pass


def adjust_balance(
    discord_id: str,
    amount: int,
    transaction_type: str,
    description: str,
    actor_discord_id: str | None = None,
    idempotency_key: str | None = None,
) -> EconomyTransaction:
    """
    Add or subtract coins and record the transaction.

    Positive amount = add coins.
    Negative amount = spend or remove coins.
    """

    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError("Amount must be an integer.")

    if amount == 0:
        raise ValueError("Amount cannot be zero.")

    if not transaction_type.strip():
        raise ValueError("Transaction type is required.")

    if not description.strip():
        raise ValueError("Description is required.")

    try:
        # Begin a transaction before reading or changing the balance.
        profile = db.session.execute(
            select(UserProfile)
            .where(UserProfile.discord_id == str(discord_id))
            .with_for_update()
        ).scalar_one_or_none()

        if profile is None:
            raise UserNotFoundError("Member profile not found.")

        if idempotency_key:
            existing = db.session.execute(
                select(EconomyTransaction).where(
                    EconomyTransaction.idempotency_key
                    == idempotency_key
                )
            ).scalar_one_or_none()

            if existing is not None:
                raise DuplicateTransactionError(
                    "This transaction has already been processed."
                )

        new_balance = profile.balance + amount

        if new_balance < 0:
            raise InsufficientFundsError(
                "Insufficient coins for this transaction."
            )

        profile.balance = new_balance

        transaction = EconomyTransaction(
            user_id=profile.id,
            amount=amount,
            balance_after=new_balance,
            transaction_type=transaction_type.strip(),
            description=description.strip(),
            actor_discord_id=(
                str(actor_discord_id)
                if actor_discord_id is not None
                else None
            ),
            idempotency_key=idempotency_key,
        )

        db.session.add(transaction)
        db.session.commit()

        return transaction

    except IntegrityError as exc:
        db.session.rollback()

        if idempotency_key:
            raise DuplicateTransactionError(
                "A transaction with this key already exists."
            ) from exc

        raise EconomyError(
            "The transaction could not be saved."
        ) from exc

    except Exception:
        db.session.rollback()
        raise
