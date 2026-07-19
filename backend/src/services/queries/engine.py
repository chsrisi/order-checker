import logging
from typing import Generator, Optional
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ...config import get_config_value

logger = logging.getLogger("backend.services.queries.engine")

# Database setup
SQLALCHEMY_DATABASE_URL: Optional[str] = get_config_value("DATABASE_URL")
if not SQLALCHEMY_DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./local.db"
    logger.warning(
        "DATABASE_URL not found in env/secrets, defaulting to: %s",
        SQLALCHEMY_DATABASE_URL,
    )

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    logger.debug("Database session opened")
    try:
        yield db
    finally:
        logger.debug("Database session closed")
        db.close()
