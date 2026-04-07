from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import hash_password
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.document import DocumentUserState
from app.models.user import User
from app.schemas.api import CreateUserRequest, UpdateUserRequest, UserResponse

router = APIRouter(prefix="/admin", tags=["admin"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )


@router.get("/users", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[UserResponse]:
    users = db.scalars(select(User).order_by(User.username.asc())).all()
    return [_user_response(item) for item in users]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserResponse:
    username = payload.username.strip()
    existing = db.scalar(select(User).where(User.username == username))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пользователь с таким логином уже существует")

    account = User(
        username=username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(account)
    db.flush()
    db.add(
        AuditLog(
            user_id=admin.id,
            action="user_created",
            entity_type="user",
            entity_id=account.id,
            message="Создана учетная запись",
            details_json={"username": username, "role": payload.role},
        )
    )
    db.commit()
    db.refresh(account)

    return _user_response(account)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserResponse:
    account = db.get(User, user_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    old_role = account.role
    account.role = payload.role
    db.add(
        AuditLog(
            user_id=admin.id,
            action="user_role_changed",
            entity_type="user",
            entity_id=account.id,
            message="Изменена роль пользователя",
            details_json={"username": account.username, "old_role": old_role, "new_role": payload.role},
        )
    )
    db.commit()
    db.refresh(account)
    return _user_response(account)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> None:
    account = db.get(User, user_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    if account.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя удалить текущего администратора")

    username = account.username
    db.query(DocumentUserState).filter(DocumentUserState.user_id == account.id).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.user_id == account.id).update({"user_id": None}, synchronize_session=False)
    db.delete(account)
    db.add(
        AuditLog(
            user_id=admin.id,
            action="user_deleted",
            entity_type="user",
            entity_id=user_id,
            message="Удалена учетная запись",
            details_json={"username": username},
        )
    )
    db.commit()
