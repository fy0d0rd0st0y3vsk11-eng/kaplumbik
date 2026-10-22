from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.database import db
from app.database.models import EconomyTransaction, UserProfile


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
    """Atomically adjust a balance and append its immutable ledger entry.

    Positive amounts credit coins; negative amounts debit them. The conditional
    SQL UPDATE prevents concurrent purchases from overspending even on SQLite,
    where SELECT ... FOR UPDATE is not enforced. The unique idempotency key and
    balance update share one transaction, so a duplicate insert rolls back the
    balance change too.
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError("Amount must be an integer.")
    if amount == 0:
        raise ValueError("Amount cannot be zero.")
    if not isinstance(transaction_type, str) or not transaction_type.strip():
        raise ValueError("Transaction type is required.")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Description is required.")
    if idempotency_key is not None and (not idempotency_key.strip() or len(idempotency_key) > 150):
        raise ValueError("Idempotency key must be non-empty and at most 150 characters.")

    try:
        if idempotency_key:
            existing = db.session.execute(
                select(EconomyTransaction.id).where(
                    EconomyTransaction.idempotency_key == idempotency_key
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise DuplicateTransactionError("This transaction has already been processed.")

        changed = db.session.execute(
            update(UserProfile)
            .where(
                UserProfile.discord_id == str(discord_id),
                UserProfile.balance + amount >= 0,
            )
            .values(balance=UserProfile.balance + amount)
        )
        if changed.rowcount != 1:
            exists = db.session.execute(
                select(UserProfile.id).where(UserProfile.discord_id == str(discord_id))
            ).scalar_one_or_none()
            if exists is None:
                raise UserNotFoundError("Member profile not found.")
            raise InsufficientFundsError("Insufficient coins for this transaction.")

        profile = db.session.execute(
            select(UserProfile).where(UserProfile.discord_id == str(discord_id))
        ).scalar_one()
        transaction = EconomyTransaction(
            user_id=profile.id,
            amount=amount,
            balance_after=profile.balance,
            transaction_type=transaction_type.strip()[:40],
            description=description.strip()[:300],
            actor_discord_id=str(actor_discord_id) if actor_discord_id is not None else None,
            idempotency_key=idempotency_key,
        )
        db.session.add(transaction)
        db.session.commit()
        return transaction
    except IntegrityError as exc:
        db.session.rollback()
        if idempotency_key:
            existing = db.session.execute(
                select(EconomyTransaction.id).where(
                    EconomyTransaction.idempotency_key == idempotency_key
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise DuplicateTransactionError("A transaction with this key already exists.") from exc
        raise EconomyError("The transaction could not be saved.") from exc
    except Exception:
        db.session.rollback()
        raise
