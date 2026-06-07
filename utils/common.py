from datetime import datetime, date
from decimal import Decimal
import uuid
import json
from typing import Any, Optional


def generate_id(prefix: str = "") -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    unique = uuid.uuid4().hex[:8].upper()
    return f"{prefix}{timestamp}{unique}"


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def to_json(data: Any) -> str:
    return json.dumps(data, default=decimal_default, ensure_ascii=False)


def parse_date(date_str: Optional[str]) -> Optional[date]:
    if not date_str:
        return None
    if isinstance(date_str, date):
        return date_str
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    try:
        import dateparser
        parsed = dateparser.parse(date_str)
        return parsed.date() if parsed else None
    except Exception:
        return None


def safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None:
            return default
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (ValueError, TypeError):
        return default


def calculate_percentage(part: Decimal, whole: Decimal) -> Decimal:
    if whole == 0:
        return Decimal("0")
    return (part / whole) * 100
