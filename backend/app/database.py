import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./petalplan.db")

if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    _engine_kwargs = {}
else:
    _connect_args = {"sslmode": "require"}
    _engine_kwargs = {"pool_pre_ping": True}  # reconnect after Supabase idle drops

engine = create_engine(DATABASE_URL, connect_args=_connect_args, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


Base = declarative_base()
