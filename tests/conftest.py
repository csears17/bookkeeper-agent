import pytest
from sqlalchemy import create_engine

from bookkeeper_agent.db.base import init_db


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", future=True)
    init_db(eng)
    return eng
