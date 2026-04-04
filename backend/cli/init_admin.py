"""
Create default admin user if no users exist in the database.
Called from entrypoint.sh on container startup.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("SECRET_KEY", "init-placeholder-32chars-do-not-use")

from backend.database import SessionLocal
from backend.models import User
from backend.auth.password import hash_password


def init_admin():
    db = SessionLocal()
    try:
        count = db.query(User).count()
        if count == 0:
            default_password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "admin")
            admin = User(
                username="admin",
                password_hash=hash_password(default_password),
                force_password_change=True,
            )
            db.add(admin)
            db.commit()
            print(f"Created default admin user (password: '{default_password}')")
            print("You will be prompted to change it on first login.")
        else:
            print(f"Admin user already exists ({count} user(s) found). Skipping.")
    finally:
        db.close()


if __name__ == "__main__":
    init_admin()
