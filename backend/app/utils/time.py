from datetime import datetime, timezone


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()