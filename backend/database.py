import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Support external database via DATABASE_URL env var (MariaDB/MySQL/PostgreSQL)
_DATABASE_URL = os.environ.get("DATABASE_URL")

if _DATABASE_URL:
    # External database — use as-is (caller is responsible for driver packages)
    engine = create_engine(_DATABASE_URL, pool_pre_ping=True)
    IS_SQLITE = False
    DB_PATH = None
else:
    # Default: SQLite
    DB_PATH = os.environ.get("DB_PATH", "/data/lanlens.db")
    _DATABASE_URL = f"sqlite:///{DB_PATH}"
    engine = create_engine(
        _DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    IS_SQLITE = True

    # SQLite does not enforce foreign key constraints by default.
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
