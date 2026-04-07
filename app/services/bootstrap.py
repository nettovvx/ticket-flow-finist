from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.user import User


def ensure_bootstrap_admin(db: Session) -> None:
    settings = get_settings()
    existing = db.scalar(select(User).where(User.username == settings.bootstrap_admin_username))
    if existing:
        return

    admin = User(
        username=settings.bootstrap_admin_username,
        password_hash=hash_password(settings.bootstrap_admin_password),
        role=settings.bootstrap_admin_role,
        is_active=True,
        last_login_at=None,
    )
    db.add(admin)
    db.flush()
    db.add(
        AuditLog(
            user_id=admin.id,
            action="bootstrap_admin_created",
            entity_type="user",
            entity_id=admin.id,
            message="Создан стартовый администратор",
            details_json={"username": admin.username, "created_at": datetime.now(timezone.utc).isoformat()},
        )
    )
    db.commit()

