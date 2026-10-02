"""Opt-in, read-only Firebase connectivity check. Never prints documents or secrets."""
from __future__ import annotations

import argparse

from firebase_admin import auth

from app.core.config import get_settings
from app.core.firebase import get_firestore_client, require_firebase_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true", required=True,
                        help="Explicitly allow a bounded Firebase Auth and Firestore read.")
    parser.add_argument("--expected-project", required=True,
                        help="Must match FIREBASE_PROJECT_ID to prevent checking the wrong project.")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        if settings.firebase_project_id != args.expected_project:
            print("Configuration check failed: expected project does not match.")
            return 1
        app = require_firebase_app()
        if app.project_id != args.expected_project:
            print("Configuration check failed: initialized app project does not match.")
            return 1
        auth.list_users(max_results=1, app=app)
        # An empty users collection is a valid response; no data is displayed.
        list(get_firestore_client().collection("users").limit(1).stream())
    except Exception as exc:
        print(f"Firebase check failed ({type(exc).__name__}). Check configuration, IAM and network access.")
        return 1
    print("Firebase Auth read: OK. Firestore read: OK. No writes performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
