
def list_upcoming_events(limit: int = 10) -> list[Event]:
    """Return scheduled events ordered by start time."""

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


def get_event_participants(event_id: int) -> list[EventParticipation]:
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
    
