
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import db
from app.database.event_models import Event, EventParticipation
from app.database.models import AuditLog


class EventServiceError(Exception):
    """Base error for event management operations."""


class EventNotFoundError(EventServiceError):
    pass


class EventStateError(EventServiceError):
    pass


def create_event(
    title: str,
    game: str,
    starts_at: datetime,
    created_by: str,
    description: str | None = None,
    game_link: str | None = None,
    room_code: str | None = None,
) -> Event:
    """Create and save a scheduled event."""

    title = title.strip()
    game = game.strip()
    created_by = str(created_by).strip()

    if not title:
        raise ValueError("Event title is required.")

    if not game:
        raise ValueError("Game name is required.")

    if not created_by:
        raise ValueError("Creator ID is required.")

    if not isinstance(starts_at, datetime):
        raise ValueError("Start time must be a datetime.")

    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise ValueError("Start time must include a timezone.")

    event = Event(
        title=title,
        game=game,
        starts_at=starts_at.astimezone(timezone.utc),
        created_by=created_by,
        description=description.strip() if description else None,
        game_link=game_link.strip() if game_link else None,
        room_code=room_code.strip() if room_code else None,
        status="scheduled",
    )

    try:
        db.session.add(event)
        db.session.commit()
        return event
    except Exception:
        db.session.rollback()
        raise


def cancel_event(event_id: int) -> Event:
    """Cancel a scheduled event without deleting its history."""

    try:
        event = db.session.execute(
            select(Event)
            .where(Event.id == event_id)
            .with_for_update()
        ).scalar_one_or_none()

        if event is None:
            raise EventNotFoundError("Event not found.")

        if event.status != "scheduled":
            raise EventStateError(
                "Only scheduled events can be cancelled."
            )

        event.status = "cancelled"
        db.session.commit()
        return event

    except Exception:
        db.session.rollback()
        raise


def set_participation(
    event_id: int,
    discord_id: str,
    status: str,
) -> EventParticipation:
    """Create or update a member's event response."""

    discord_id = str(discord_id).strip()
    status = status.strip().lower()

    if not discord_id:
        raise ValueError("Discord ID is required.")

    if status not in {"going", "not_going"}:
        raise ValueError(
            "Members can only choose going or not_going."
        )

    try:
        event = db.session.get(Event, event_id)

        if event is None:
            raise EventNotFoundError("Event not found.")

        if event.status != "scheduled":
            raise EventStateError(
                "Responses are closed for this event."
            )

        participation = db.session.execute(
            select(EventParticipation).where(
                EventParticipation.event_id == event_id,
                EventParticipation.discord_id == discord_id,
            )
        ).scalar_one_or_none()

        # A late cancellation means a previous "going" response changed to "not_going".
        starts_at = event.starts_at
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        seconds_to_start = (starts_at - datetime.now(timezone.utc)).total_seconds()
        late_cancellation = (
            participation is not None
            and participation.status == "going"
            and status == "not_going"
            and 0 < seconds_to_start <= 30 * 60
        )

        if participation is None:
            participation = EventParticipation(
                event_id=event_id,
                discord_id=discord_id,
                status=status,
            )
            db.session.add(participation)
        else:
            if participation.status in {"attended", "absent"}:
                raise EventStateError(
                    "Final attendance has already been recorded."
                )

            if participation.reward_approved:
                raise EventStateError(
                    "An approved reward record cannot be changed."
                )

            participation.status = status

        if late_cancellation:
            db.session.add(AuditLog(
                actor_discord_id=discord_id,
                action="event.rsvp_late_cancel",
                target_type="event_participation",
                target_id=f"{event_id}:{discord_id}",
                details={"seconds_before_start": int(seconds_to_start), "status": "not_going"},
                success=True,
            ))

        db.session.commit()
        return participation

    except Exception:
        db.session.rollback()
        raise


def record_attendance(
    event_id: int,
    discord_id: str,
    status: str,
    manager_discord_id: str,
) -> EventParticipation:
    """Record final attendance for a member."""

    discord_id = str(discord_id).strip()
    manager_discord_id = str(manager_discord_id).strip()
    status = status.strip().lower()

    if not discord_id or not manager_discord_id:
        raise ValueError("Member and manager IDs are required.")

    if status not in {"attended", "absent"}:
        raise ValueError("Attendance must be attended or absent.")

    try:
        event = db.session.get(Event, event_id)

        if event is None:
            raise EventNotFoundError("Event not found.")

        if event.status != "scheduled":
            raise EventStateError(
                "Attendance can only be recorded for scheduled events."
            )

        participation = db.session.execute(
            select(EventParticipation)
            .where(
                EventParticipation.event_id == event_id,
                EventParticipation.discord_id == discord_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if participation is None:
            participation = EventParticipation(
                event_id=event_id,
                discord_id=discord_id,
                status=status,
                marked_by=manager_discord_id,
                marked_at=datetime.now(timezone.utc),
            )
            db.session.add(participation)
        else:
            if participation.reward_approved:
                raise EventStateError(
                    "Attendance with an approved reward cannot be changed."
                )

            participation.status = status
            participation.marked_by = manager_discord_id
            participation.marked_at = datetime.now(timezone.utc)

        db.session.commit()
        return participation

    except Exception:
        db.session.rollback()
        raise


def list_upcoming_events(limit: int = 10) -> list[Event]:
    """Return future scheduled events in chronological order."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("Limit must be an integer.")

    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    now = datetime.now(timezone.utc)

    return list(
        db.session.execute(
            select(Event)
            .where(
                Event.status == "scheduled",
                Event.starts_at >= now,
            )
            .order_by(Event.starts_at.asc())
            .limit(limit)
        ).scalars()
    )


def get_event_participants(
    event_id: int,
) -> list[EventParticipation]:
    """Return participation records for an existing event."""

    event = db.session.get(Event, event_id)

    if event is None:
        raise EventNotFoundError("Event not found.")

    return list(
        db.session.execute(
            select(EventParticipation)
            .where(EventParticipation.event_id == event_id)
            .order_by(EventParticipation.id.asc())
        ).scalars()
        )
    
