"""One-time, local-only bootstrap of the FIRST admin user.

Usage (from backend/, with .env holding real Firebase credentials):
    python -m scripts.bootstrap_admin --email you@brainware.example --name "Your Name"

The password is read with a hidden prompt (or BOOTSTRAP_ADMIN_PASSWORD env var);
nothing is hardcoded. Refuses to run if an ADMIN profile already exists.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from pydantic import ValidationError

from app.core.errors import UserServiceError
from app.schemas.user import UserCreate, UserRole
from app.services import users as user_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first ADMIN user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    if user_service.user_exists_with_role(UserRole.ADMIN):
        print("An ADMIN already exists. Use the authenticated POST /api/v1/users endpoint instead.")
        return 1

    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    try:
        payload = UserCreate(
            email=args.email, password=password, display_name=args.name, role=UserRole.ADMIN
        )
    except ValidationError as exc:
        for err in exc.errors():
            print(f"Invalid {'.'.join(map(str, err['loc']))}: {err['msg']}")
        return 2
    try:
        profile = user_service.create_user(payload, actor_uid=None, actor_role="BOOTSTRAP")
    except UserServiceError as exc:
        print(f"Failed: {exc}")
        return 3
    print(f"Admin created: uid={profile.uid} email={profile.email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
