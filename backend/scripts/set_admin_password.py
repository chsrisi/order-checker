"""Apply the configured ADMIN_PASSWORD to the existing admin account (docs/RELEASE.md).

The startup seed only *creates* the admin when it is missing, so an admin created long ago
keeps its old password even after ADMIN_PASSWORD changes. Run this once after changing the
secret:

    docker compose -f compose.yaml -f compose.prod.yaml exec server \\
        python -m scripts.set_admin_password

It refuses empty/default/placeholder passwords and revokes the admin's refresh tokens.
"""

import sys

from sqlalchemy import delete, select

from src.config import get_config_value
from src.models import RefreshToken, User
from src.services.auth_service import get_password_hash
from src.services.queries.engine import get_db
from src.settings_guard import PLACEHOLDER_ADMIN_PASSWORDS


def set_admin_password() -> str:
    username = get_config_value("ADMIN_USERNAME", "admin") or "admin"
    password = (get_config_value("ADMIN_PASSWORD") or "").strip()
    if password in PLACEHOLDER_ADMIN_PASSWORDS:
        raise SystemExit("ADMIN_PASSWORD is empty or a default/placeholder value; refusing")
    with get_db() as db:
        user = db.execute(select(User).filter(User.username == username)).scalar_one_or_none()
        if user is None or user.scope != "admin":
            raise SystemExit(f"No admin account named {username!r}; start the server to seed it")
        user.password_hash = get_password_hash(password)
        db.execute(delete(RefreshToken).where(RefreshToken.username == username))
        db.commit()
    return username


if __name__ == "__main__":
    print(f"password updated for admin {set_admin_password()!r}; admin sessions revoked")
    sys.exit(0)
