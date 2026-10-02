import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://finapp:finapp@localhost:5432/finapp_test")
os.environ["ADMIN_TOKEN"] = "test-admin-token"

import pytest
from sqlalchemy import create_engine

import app.providers.base as pbase
from app.db import Base, set_engine, session_scope
from app import models  # noqa: F401

pbase._TESTING = True


@pytest.fixture(scope="session")
def engine():
    e = create_engine(os.environ["DATABASE_URL"], future=True)
    Base.metadata.drop_all(e)
    Base.metadata.create_all(e)
    set_engine(e)
    yield e
    Base.metadata.drop_all(e)


@pytest.fixture()
def db(engine):
    with engine.begin() as c:
        for t in reversed(Base.metadata.sorted_tables):
            c.execute(t.delete())
    with session_scope() as s:
        yield s
