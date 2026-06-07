from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from config import settings

_db_url = settings.database_url
_is_sqlite = "sqlite" in _db_url

_engine_kwargs = {
    "pool_pre_ping": True,
    "echo": settings.debug,
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
