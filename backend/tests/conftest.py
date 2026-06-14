import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.main import app

# In-memory SQLite shared across all connections via StaticPool
SQLALCHEMY_TEST_URL = "sqlite://"

_engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(autouse=True)
def reset_db():
    """Recreate all tables before each test and tear down after."""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


def _override_session():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_session] = _override_session


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    """Raw DB session for setting up fixture data directly."""
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()
