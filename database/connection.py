from sqlalchemy import create_engine, TypeDecorator, JSON as _SA_JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator, Any
import json
from datetime import date, datetime
from decimal import Decimal
from config import settings


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except Exception:
            return list(obj)
    if isinstance(obj, set):
        return list(obj)
    if hasattr(obj, "value"):
        try:
            return obj.value
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return str(obj)
        except Exception:
            return repr(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _recursive_convert(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _recursive_convert(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_recursive_convert(v) for v in obj]
    if isinstance(obj, (Decimal,)):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)
    return obj


def _json_serializer(obj, **kwargs):
    return json.dumps(_recursive_convert(obj), ensure_ascii=False, default=_json_default, **kwargs)


class JSON(TypeDecorator):
    impl = _SA_JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _recursive_convert(value)

    def process_result_value(self, value, dialect):
        return value


_db_url = settings.database_url
_is_sqlite = "sqlite" in _db_url

_engine_kwargs = {
    "pool_pre_ping": True,
    "echo": settings.debug,
    "json_serializer": _json_serializer,
}

if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 50,
        "pool_recycle": 3600,
    })

engine = create_engine(_db_url, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
