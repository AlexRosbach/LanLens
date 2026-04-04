#!/usr/bin/env python3
"""
Reset the LanLens admin password directly in the SQLite database.
This bypasses the API entirely — works even if the app is down.

Usage:
    docker exec -it lanlens reset-password
    docker exec -it lanlens reset-password --password "newpassword"
"""
import argparse
import getpass
import os
import sqlite3
import sys

DB_PATH = os.environ.get("DB_PATH", "/data/lanlens.db")


def hash_bcrypt(password: str) -> str:
    try:
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
        return ctx.hash(password)
    except ImportError:
        print("ERROR: passlib is not installed.", file=sys.stderr)
        sys.exit(1)


def reset_password(new_password: str):
    if len(new_password) < 8:
        print("ERROR: Password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    password_hash = hash_bcrypt(new_password)

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT id, username FROM users WHERE username='admin'")
        row = cur.fetchone()
        if not row:
            print("ERROR: No admin user found in database.", file=sys.stderr)
            sys.exit(1)

        conn.execute(
            "UPDATE users SET password_hash=?, force_password_change=1 WHERE username='admin'",
            (password_hash,),
        )
        conn.commit()
        print("Password reset successfully.")
        print("The admin user will be prompted to change it on next login.")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Reset the LanLens admin password",
        prog="reset-password",
    )
    parser.add_argument(
        "--password",
        help="New password (if not provided, will prompt interactively)",
        default=None,
    )
    args = parser.parse_args()

    if args.password:
        new_password = args.password
    else:
        print("Reset LanLens Admin Password")
        print("=" * 40)
        new_password = getpass.getpass("New password (min 8 chars): ")
        confirm = getpass.getpass("Confirm new password: ")
        if new_password != confirm:
            print("ERROR: Passwords do not match.", file=sys.stderr)
            sys.exit(1)

    reset_password(new_password)


if __name__ == "__main__":
    main()
