from datetime import date, datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.database import db
from app.database.advanced_models import BotSetting
from app.database.models import AuditLog
from app.seri.models import StreakContribution, StreakDay

GOAL = 3


def _day_key(day: date) -> str:
    return day.isoformat()


def get_or_create_day(day: date) -> StreakDay:
    key = _day_key(day)
    row = db.session.execute(select(StreakDay).where(StreakDay.day == key)).scalar_one_or_none()
    if row is not None:
        return row
    row = StreakDay(day=key, status="open")
    db.session.add(row)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        row = db.session.execute(select(StreakDay).where(StreakDay.day == key)).scalar_one()
    return row


def contribution_count(day_row: StreakDay) -> int:
    return int(db.session.scalar(
        select(func.count(StreakContribution.id)).where(StreakContribution.day_id == day_row.id)
    ) or 0)


def contributor_ids(day_row: StreakDay) -> list[str]:
    return list(db.session.execute(
        select(StreakContribution.discord_id).where(StreakContribution.day_id == day_row.id)
        .order_by(StreakContribution.first_message_at.asc(), StreakContribution.id.asc())
    ).scalars())


def record_contribution(day: date, discord_id: str, channel_id: str, message_id: str) -> tuple[StreakDay, bool]:
    row = get_or_create_day(day)
    existing = db.session.execute(select(StreakContribution.id).where(
        StreakContribution.day_id == row.id,
        StreakContribution.discord_id == str(discord_id),
    )).scalar_one_or_none()
    if existing is not None:
        return row, False
    db.session.add(StreakContribution(
        day_id=row.id, discord_id=str(discord_id), source_channel_id=str(channel_id),
        source_message_id=str(message_id),
    ))
    try:
        db.session.commit()
        return row, True
    except IntegrityError:
        db.session.rollback()
        row = db.session.execute(select(StreakDay).where(StreakDay.day == _day_key(day))).scalar_one()
        return row, False


def latest_streak_length() -> int:
    """Return the latest completed streak length; pending days pause rather than reset it."""
    rows = list(db.session.execute(select(StreakDay).where(
        StreakDay.status.in_(["completed", "forgiven"])
    ).order_by(StreakDay.day.asc())).scalars())
    streak = 0
    previous_date = None
    for row in rows:
        row_date = date.fromisoformat(row.day)
        if previous_date is None or (row_date - previous_date).days == 1:
            streak += 1
        else:
            streak = 1
        previous_date = row_date
    # A pending day pauses the streak; it is not counted as a failure/reset.
    return streak


def close_day(day: date, actor_discord_id: str | None = None) -> tuple[StreakDay, bool]:
    row = get_or_create_day(day)
    if row.status != "open":
        return row, False
    pending_before = db.session.execute(select(StreakDay.id).where(
        StreakDay.day < row.day, StreakDay.status == "pending"
    ).limit(1)).scalar_one_or_none() is not None
    count = contribution_count(row)
    if count >= GOAL and not pending_before:
        row.status = "completed"
        row.streak_after = latest_streak_length() + 1
    else:
        row.status = "pending"
        row.streak_after = latest_streak_length()
    row.closed_at = datetime.now(timezone.utc)
    db.session.add(AuditLog(
        actor_discord_id=actor_discord_id, action="streak.day_closed", target_type="streak_day",
        target_id=row.day, details={"status": row.status, "contributors": count, "goal": GOAL}, success=True,
    ))
    db.session.commit()
    return row, True


def make_up_pending_days(count: int, actor_discord_id: str) -> list[StreakDay]:
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 365:
        raise ValueError("Telafi sayısı 1–365 arasında bir tam sayı olmalı.")
    rows = list(db.session.execute(select(StreakDay).where(StreakDay.status == "pending")
        .order_by(StreakDay.day.desc()).limit(count)).scalars())
    if len(rows) != count:
        raise ValueError(f"Yalnızca {len(rows)} telafi bekleyen gün var; {count} istedin.")
    for row in rows:
        row.status = "forgiven"
        row.streak_after = 0  # Recomputed below from chronological history.
    ordered = list(db.session.execute(select(StreakDay).where(
        StreakDay.status.in_(["completed", "forgiven"])
    ).order_by(StreakDay.day.asc())).scalars())
    streak = 0
    previous_date = None
    for row in ordered:
        row_date = date.fromisoformat(row.day)
        streak = streak + 1 if previous_date is not None and (row_date - previous_date).days == 1 else 1
        row.streak_after = streak
        previous_date = row_date
    db.session.add(AuditLog(
        actor_discord_id=str(actor_discord_id), action="streak.make_up", target_type="streak_day",
        target_id=",".join(sorted(row.day for row in rows)),
        details={"count": len(rows), "days": sorted(row.day for row in rows)}, success=True,
    ))
    db.session.commit()
    return sorted(rows, key=lambda item: item.day)


def correct_contribution(day: date, discord_id: str, add: bool, actor_discord_id: str, reason: str) -> int:
    reason = (reason or "").strip()[:300]
    if not reason:
        raise ValueError("Düzeltme gerekçesi zorunlu.")
    row = get_or_create_day(day)
    contribution = db.session.execute(select(StreakContribution).where(
        StreakContribution.day_id == row.id, StreakContribution.discord_id == str(discord_id)
    )).scalar_one_or_none()
    if add and contribution is None:
        db.session.add(StreakContribution(day_id=row.id, discord_id=str(discord_id), correction_note=reason))
    elif not add and contribution is not None:
        db.session.delete(contribution)
    elif add == (contribution is not None):
        raise ValueError("Bu üyenin o gündeki katkısı zaten istediğin durumda.")
    db.session.add(AuditLog(
        actor_discord_id=str(actor_discord_id), action="streak.contribution_correct", target_type="streak_contribution",
        target_id=f"{row.day}:{discord_id}", details={"add": add, "reason": reason}, success=True,
    ))
    db.session.commit()
    return contribution_count(row)


def get_channel_id() -> str:
    row = db.session.get(BotSetting, "streak_channel_id")
    return (row.value or "").strip() if row else ""


def set_channel_id(channel_id: str, actor_discord_id: str) -> None:
    value = str(channel_id)
    row = db.session.get(BotSetting, "streak_channel_id")
    if row is None:
        row = BotSetting(key="streak_channel_id", value=value)
        db.session.add(row)
    else:
        row.value = value
    row.updated_by = str(actor_discord_id)
    db.session.add(AuditLog(actor_discord_id=str(actor_discord_id), action="streak.channel_set",
        target_type="channel", target_id=value, details={}, success=True))
    db.session.commit()
