from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_admin
from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.document import Document, DocumentUserState
from app.models.user import User
from app.services.dashboard import build_document_listing, build_ticket_case_listing, load_document_with_context


router = APIRouter()
templates = Jinja2Templates(directory=str(get_settings().templates_dir))


def set_flash(request: Request, *, level: str, message: str) -> None:
    request.session["flash"] = {"level": level, "message": message}


def pop_flash(request: Request) -> dict | None:
    return request.session.pop("flash", None)


@router.get("/", response_class=HTMLResponse)
def root(request: Request) -> RedirectResponse:
    destination = "/documents/tickets" if request.session.get("user_id") else "/login"
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {"app_name": get_settings().app_name, "flash": pop_flash(request)},
    )


@router.post("/login")
def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        set_flash(request, level="error", message="Неверный логин или пароль")
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

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
    return RedirectResponse("/documents/tickets", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout_action(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RedirectResponse:
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
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


def _documents_response(
    request: Request,
    *,
    user: User,
    listing: dict[str, object],
    current_tab: str,
    page_title: str,
    q: str | None,
    view: str,
    status_filter: str | None,
    date_from: str | None,
    date_to: str | None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "documents.html",
        {
            "app_name": get_settings().app_name,
            "flash": pop_flash(request),
            "current_user": user,
            "current_tab": current_tab,
            "page_title": page_title,
            "rows": listing["rows"],
            "counters": listing["counters"],
            "filters": {
                "q": q or "",
                "view": view,
                "status_filter": status_filter or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
    )


@router.get("/documents/tickets", response_class=HTMLResponse)
def tickets_page(
    request: Request,
    q: str | None = None,
    view: str = "active",
    status_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HTMLResponse:
    listing = build_ticket_case_listing(
        db,
        user=user,
        search=q,
        view=view,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
    )
    return templates.TemplateResponse(
        request,
        "ticket_cases.html",
        {
            "app_name": get_settings().app_name,
            "flash": pop_flash(request),
            "current_user": user,
            "current_tab": "tickets",
            "page_title": "Билеты и реализации",
            "ticket_cases": listing["ticket_cases"],
            "orphan_realizations": listing["orphan_realizations"],
            "counters": listing["counters"],
            "filters": {
                "q": q or "",
                "view": view,
                "status_filter": status_filter or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
    )


@router.get("/documents/payments", response_class=HTMLResponse)
def payments_page(
    request: Request,
    q: str | None = None,
    view: str = "active",
    status_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HTMLResponse:
    listing = build_document_listing(
        db,
        user=user,
        flow_group="payments",
        search=q,
        view=view,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
    )
    return _documents_response(
        request,
        user=user,
        listing=listing,
        current_tab="payments",
        page_title="Платежки",
        q=q,
        view=view,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(
    request: Request,
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HTMLResponse:
    context = load_document_with_context(db, document_id)
    if not context:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return templates.TemplateResponse(
        request,
        "document_detail.html",
        {
            "app_name": get_settings().app_name,
            "flash": pop_flash(request),
            "current_user": user,
            **context,
        },
    )


@router.post("/documents/{document_id}/hide")
def hide_document(
    request: Request,
    document_id: str,
    reason: str = Form(default="Просмотрено"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RedirectResponse:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")

    state = db.scalar(
        select(DocumentUserState).where(
            DocumentUserState.document_id == document_id,
            DocumentUserState.user_id == user.id,
        )
    )
    if not state:
        state = DocumentUserState(document_id=document_id, user_id=user.id)
        db.add(state)

    state.is_hidden = True
    state.is_viewed = True
    state.hidden_reason = reason
    state.hidden_at = datetime.now(timezone.utc)
    state.viewed_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            user_id=user.id,
            action="document_hidden",
            entity_type="document",
            entity_id=document_id,
            message="Документ скрыт из оперативного списка",
            details_json={"reason": reason},
        )
    )
    db.commit()
    set_flash(request, level="success", message="Документ скрыт из оперативного списка")
    redirect_to = request.headers.get("referer") or "/documents/tickets"
    return RedirectResponse(redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/documents/{document_id}/unhide")
def unhide_document(
    request: Request,
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RedirectResponse:
    state = db.scalar(
        select(DocumentUserState).where(
            DocumentUserState.document_id == document_id,
            DocumentUserState.user_id == user.id,
        )
    )
    if state:
        state.is_hidden = False
        state.hidden_reason = None
        state.hidden_at = None
    db.add(
        AuditLog(
            user_id=user.id,
            action="document_unhidden",
            entity_type="document",
            entity_id=document_id,
            message="Документ возвращен в оперативный список",
        )
    )
    db.commit()
    set_flash(request, level="success", message="Документ снова виден в оперативном списке")
    redirect_to = request.headers.get("referer") or "/documents/tickets"
    return RedirectResponse(redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> HTMLResponse:
    users = db.scalars(select(User).order_by(User.username.asc())).all()
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "app_name": get_settings().app_name,
            "flash": pop_flash(request),
            "current_user": user,
            "users": users,
        },
    )


@router.post("/admin/users")
def create_user_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> RedirectResponse:
    existing = db.scalar(select(User).where(User.username == username))
    if existing:
        set_flash(request, level="error", message="Пользователь с таким логином уже существует")
        return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)

    account = User(username=username, password_hash=hash_password(password), role=role, is_active=True)
    db.add(account)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action="user_created",
            entity_type="user",
            entity_id=account.id,
            message="Создана учетная запись",
            details_json={"username": username, "role": role},
        )
    )
    db.commit()
    set_flash(request, level="success", message="Учетная запись создана")
    return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)
