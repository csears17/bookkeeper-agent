from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(db_path: str | Path) -> Engine:
    return create_engine(f"sqlite:///{db_path}", future=True)


def init_db(engine: Engine) -> None:
    # Import models so they register on Base.metadata before create_all.
    from bookkeeper_agent.db import models  # noqa: F401

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine):
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
