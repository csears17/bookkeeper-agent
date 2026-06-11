import pytest
from sqlalchemy import create_engine

from bookkeeper_agent.db.base import Base


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    return eng
