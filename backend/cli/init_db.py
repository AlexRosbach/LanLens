"""
Initialize the SQLite database — create all tables if they don't exist.
Called from entrypoint.sh on container startup.
"""
import os
import sys

# Allow running directly: python backend/cli/init_db.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Set a dummy SECRET_KEY so config.py doesn't exit
os.environ.setdefault("SECRET_KEY", "init-placeholder-32chars-do-not-use")

from backend.database import engine, Base
import backend.models  # noqa: F401 — registers all models


def init():
    Base.metadata.create_all(bind=engine)
    print("Database initialized.")


if __name__ == "__main__":
    init()
