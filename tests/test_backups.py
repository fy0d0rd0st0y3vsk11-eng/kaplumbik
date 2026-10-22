from datetime import date, datetime, timezone
from app.events.backups import _decode, _encode

class FakeColumn:
    pass

def test_backup_serializer_round_trips_datetime_date_and_json():
    values={
        "timestamp": datetime(2026,10,23,12,30,tzinfo=timezone.utc),
        "day": date(2026,10,23),
        "metadata": {"items":["one",2,True,None]},
    }
    encoded=_encode(values)
    assert encoded["timestamp"]["__type__"]=="datetime"
    assert encoded["day"]["__type__"]=="date"
    assert _decode(encoded["timestamp"],FakeColumn())==values["timestamp"]
    assert _decode(encoded["day"],FakeColumn())==values["day"]
    assert _decode(encoded["metadata"],FakeColumn())==values["metadata"]
