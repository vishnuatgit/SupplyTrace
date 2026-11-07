"""
The application database: a SQLAlchemy engine for the review workflow (and the
features built on it).

By default this is a SQLite file under the app's data directory. Setting
DATABASE_URL points the app at another database instead, for example a free
PostgreSQL on Neon. Nothing needs to be set for the demo to work.
"""

import logging
import os

from sqlalchemy import Engine, create_engine

from src.storage.schema import metadata

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join("data", "supplytrace.db")


def database_url(url: str | None, path: str) -> str:
    """
    The URL to connect to: `url` (DATABASE_URL) when set, otherwise a SQLite file at `path`.
    Hosts hand out PostgreSQL URLs that start with "postgres://", which SQLAlchemy
    does not accept, so that prefix is rewritten.
    """
    if not url:
        return f"sqlite:///{os.path.abspath(path)}"
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def create_database(url: str | None, path: str) -> Engine:
    """Connects (creating a SQLite file's folder if needed) and creates any missing tables."""
    full_url = database_url(url, path)
    if full_url.startswith("sqlite:///"):
        os.makedirs(os.path.dirname(full_url.removeprefix("sqlite:///")), exist_ok=True)
    engine = create_engine(full_url, pool_pre_ping=True)
    metadata.create_all(engine)
    logger.info(f"Database ready ({engine.dialect.name})")
    return engine
