"""
Database engine and session setup.
Uses SQLModel (SQLAlchemy + Pydantic) with PostgreSQL.
"""
import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://assetuser:assetpass@localhost:5432/assetdb"
)

engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    """Create all tables on startup (no Alembic — acceptable for 1-week project)."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yields a DB session per request."""
    with Session(engine) as session:
        yield session
