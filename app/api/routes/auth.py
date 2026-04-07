from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import verify_password
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.api import LoginRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> UserResponse:
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    request.session["user_id"] = user.id
    user.last_login_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            user_id=user.id,
            action="login",
            entity_type="user",
            entity_id=user.id,
            message="Пользователь вошел в систему",
        )
    )
    db.commit()
    db.refresh(user)
    return _serialize_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    db.add(
        AuditLog(
            user_id=user.id,
            action="logout",
            entity_type="user",
            entity_id=user.id,
            message="Пользователь вышел из системы",
        )
    )
    db.commit()
    request.session.clear()


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return _serialize_user(user)
