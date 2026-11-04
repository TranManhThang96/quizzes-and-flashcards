from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def day_start(now: datetime, tz: ZoneInfo) -> datetime:
    """The first instant of the local day, expressed in UTC."""
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
