"""Time tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now(tz_offset_hours: float = 0.0) -> dict:
    """Returns the current date and time, optionally shifted by a UTC offset.

    Args:
        tz_offset_hours: Offset from UTC in hours (e.g. 2.0 for CEST). Defaults to 0 (UTC).

    Returns:
        A dict with the ISO-8601 'timestamp', the 'weekday' name and the applied 'utc_offset'.
    """
    tz = timezone(timedelta(hours=tz_offset_hours))
    now = datetime.now(tz)
    return {
        "timestamp": now.isoformat(timespec="seconds"),
        "weekday": now.strftime("%A"),
        "utc_offset": tz_offset_hours,
    }
