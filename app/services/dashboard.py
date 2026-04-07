from collections import Counter
from datetime import datetime, time, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.models.document import Document, DocumentLink, DocumentPayload, DocumentUserState
from app.models.user import User


def _parse_date_start(value: str) -> datetime | None:
    try:
        return datetime.combine(datetime.fromisoformat(value).date(), time.min, tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_date_end(value: str) -> datetime | None:
    try:
        return datetime.combine(datetime.fromisoformat(value).date(), time.max, tzinfo=timezone.utc)
    except ValueError:
        return None


def _get_user_state(document: Document, user_id: str) -> DocumentUserState | None:
    return next((state for state in document.user_states if state.user_id == user_id), None)


def _normalize_search(search: str | None) -> str | None:
    if not search:
        return None
    value = search.strip().lower()
    return value or None


def _payload_values(payload: DocumentPayload | None) -> list[str]:
    if not payload:
        return []
    values = [
        payload.passenger_name,
        payload.ticket_number,
        payload.exchange_ticket_number,
        payload.pnr,
        payload.mom_number,
        payload.payment_number,
        payload.payment_purpose,
        payload.client_name,
        payload.direction,
        payload.route,
    ]
    return [value.lower() for value in values if value]


def _document_matches_search(document: Document, search: str | None) -> bool:
    normalized = _normalize_search(search)
    if not normalized:
        return True

    candidates = [
        (document.title or "").lower(),
        (document.file_name or "").lower(),
        (document.business_key or "").lower(),
        * _payload_values(document.payload),
    ]
    return any(normalized in candidate for candidate in candidates)


def _event_status(document: Document, step_code: str) -> str:
    statuses = [event.status for event in document.events if event.step_code == step_code]
    if not statuses:
        return "pending"
    if "error" in statuses:
        return "error"
    if "success" in statuses:
        return "success"
    return statuses[-1]


def _event_occurred_at(document: Document, step_code: str) -> datetime | None:
    timestamps = [event.occurred_at for event in document.events if event.step_code == step_code and event.occurred_at]
    if not timestamps:
        return None
    return max(timestamps)


def _combine_statuses(statuses: list[str]) -> str:
    if "error" in statuses:
        return "error"
    if "in_progress" in statuses or "pending" in statuses:
        return "in_progress"
    return "success"


def _format_delta(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 60:
        return f"{seconds}с"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}м {sec}с"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}ч {minutes}м {sec}с"
    days, hours = divmod(hours, 24)
    return f"{days}д {hours}ч {minutes}м"


def _with_step_deltas(steps: list[dict[str, object]]) -> list[dict[str, object]]:
    previous_time: datetime | None = None
    enriched: list[dict[str, object]] = []
    for step in steps:
        current_time = step.get("occurred_at")
        delta_seconds: int | None = None
        if previous_time and isinstance(current_time, datetime):
            raw = int((current_time - previous_time).total_seconds())
            if raw >= 0:
                delta_seconds = raw

        if isinstance(current_time, datetime):
            previous_time = current_time

        enriched.append(
            {
                **step,
                "delta_seconds": delta_seconds,
                "delta_human": _format_delta(delta_seconds),
            }
        )
    return enriched


def _ticket_case_steps(ticket: Document) -> list[dict[str, object]]:
    steps = [
        {
            "code": "sirena_received",
            "label": "Sirena приняла билет",
            "status": _event_status(ticket, "sirena_received"),
            "occurred_at": _event_occurred_at(ticket, "sirena_received"),
        },
        {
            "code": "ticket_copied_to_ftp",
            "label": "Билет переместился на FTP",
            "status": _event_status(ticket, "ticket_copied_to_ftp"),
            "occurred_at": _event_occurred_at(ticket, "ticket_copied_to_ftp"),
        },
        {
            "code": "ticket_seen_by_mom",
            "label": "MOM обработал билет",
            "status": _event_status(ticket, "ticket_seen_by_mom"),
            "occurred_at": _event_occurred_at(ticket, "ticket_seen_by_mom"),
        },
        {
            "code": "realization_received_from_mom",
            "label": "MOM вернул реализацию",
            "status": _event_status(ticket, "realization_received_from_mom"),
            "occurred_at": _event_occurred_at(ticket, "realization_received_from_mom"),
        },
        {
            "code": "realization_copied_to_smb",
            "label": "Реализация отправлена в 1С",
            "status": _event_status(ticket, "realization_copied_to_smb"),
            "occurred_at": _event_occurred_at(ticket, "realization_copied_to_smb"),
        },
    ]
    return _with_step_deltas(steps)


def _group_status(ticket: Document, realizations: list[Document]) -> str:
    statuses = [ticket.status, *[realization.status for realization in realizations]]
    return _combine_statuses(statuses)


def _matches_date_range(documents: list[Document], date_from: str | None, date_to: str | None) -> bool:
    parsed_from = _parse_date_start(date_from) if date_from else None
    parsed_to = _parse_date_end(date_to) if date_to else None
    if not parsed_from and not parsed_to:
        return True

    timestamps = [document.occurred_at for document in documents if document.occurred_at]
    if not timestamps:
        return False

    for timestamp in timestamps:
        if parsed_from and timestamp < parsed_from:
            continue
        if parsed_to and timestamp > parsed_to:
            continue
        return True
    return False


def _matches_status_filter(status: str, status_filter: str | None) -> bool:
    if not status_filter:
        return True
    return status == status_filter


def _matches_view(status: str, state: DocumentUserState | None, view: str) -> bool:
    is_hidden = bool(state and state.is_hidden)
    if view == "active":
        return status in {"in_progress", "error"} and not is_hidden
    if view == "errors":
        return status == "error" and not is_hidden
    if view == "success":
        return status == "success" and not is_hidden
    if view == "hidden":
        return is_hidden
    if view == "all":
        return True
    return status in {"in_progress", "error"} and not is_hidden


def build_ticket_case_listing(
    db: Session,
    *,
    user: User,
    search: str | None = None,
    view: str = "active",
    status_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, object]:
    documents = db.scalars(
        select(Document)
        .where(Document.flow_group == "tickets")
        .options(
            selectinload(Document.payload),
            selectinload(Document.events),
            selectinload(Document.outgoing_links),
            selectinload(Document.incoming_links),
            selectinload(Document.user_states),
        )
        .order_by(Document.occurred_at.desc().nullslast(), Document.created_at.desc())
    ).unique().all()

    ticket_by_id = {document.id: document for document in documents if document.doc_type == "ticket"}
    realization_by_id = {document.id: document for document in documents if document.doc_type == "realization"}

    linked_realization_ids: set[str] = set()
    ticket_cases: list[dict[str, object]] = []
    for ticket in ticket_by_id.values():
        related_realizations = []
        for link in ticket.outgoing_links:
            if link.link_type != "ticket_to_realization":
                continue
            realization = realization_by_id.get(link.to_document_id)
            if realization:
                related_realizations.append(realization)
                linked_realization_ids.add(realization.id)

        related_realizations.sort(key=lambda item: item.occurred_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        group_documents = [ticket, *related_realizations]
        group_status = _group_status(ticket, related_realizations)
        state = _get_user_state(ticket, user.id)

        if not _matches_status_filter(group_status, status_filter):
            continue
        if not _matches_view(group_status, state, view):
            continue
        if not _matches_date_range(group_documents, date_from, date_to):
            continue
        if search and not any(_document_matches_search(document, search) for document in group_documents):
            continue

        ticket_cases.append(
            {
                "ticket": ticket,
                "ticket_state": state,
                "realizations": related_realizations,
                "group_status": group_status,
                "steps": _ticket_case_steps(ticket),
                "last_activity_at": max((document.occurred_at for document in group_documents if document.occurred_at), default=ticket.created_at),
            }
        )

    ticket_cases.sort(key=lambda item: item["last_activity_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    orphan_realizations: list[dict[str, object]] = []
    for realization in realization_by_id.values():
        if realization.id in linked_realization_ids:
            continue
        state = _get_user_state(realization, user.id)
        if not _matches_status_filter(realization.status, status_filter):
            continue
        if not _matches_view(realization.status, state, view):
            continue
        if not _matches_date_range([realization], date_from, date_to):
            continue
        if search and not _document_matches_search(realization, search):
            continue

        orphan_realizations.append(
            {
                "realization": realization,
                "state": state,
            }
        )
    orphan_realizations.sort(
        key=lambda item: item["realization"].occurred_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    counters = Counter()
    for case in ticket_cases:
        counters[case["group_status"]] += 1
        if case["ticket_state"] and case["ticket_state"].is_hidden:
            counters["hidden"] += 1
    for orphan in orphan_realizations:
        counters[orphan["realization"].status] += 1
        if orphan["state"] and orphan["state"].is_hidden:
            counters["hidden"] += 1

    return {
        "ticket_cases": ticket_cases,
        "orphan_realizations": orphan_realizations,
        "counters": counters,
    }


def build_document_listing(
    db: Session,
    *,
    user: User,
    flow_group: str,
    search: str | None = None,
    view: str = "active",
    status_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> dict[str, object]:
    state_alias = aliased(DocumentUserState)
    stmt = (
        select(Document, DocumentPayload, state_alias)
        .join(DocumentPayload, DocumentPayload.document_id == Document.id, isouter=True)
        .join(
            state_alias,
            and_(state_alias.document_id == Document.id, state_alias.user_id == user.id),
            isouter=True,
        )
        .where(Document.flow_group == flow_group)
        .order_by(Document.occurred_at.desc().nullslast(), Document.created_at.desc())
        .limit(limit)
    )

    if status_filter:
        stmt = stmt.where(Document.status == status_filter)

    if date_from:
        parsed_from = _parse_date_start(date_from)
        if parsed_from:
            stmt = stmt.where(Document.occurred_at >= parsed_from)
    if date_to:
        parsed_to = _parse_date_end(date_to)
        if parsed_to:
            stmt = stmt.where(Document.occurred_at <= parsed_to)

    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Document.title.ilike(pattern),
                Document.file_name.ilike(pattern),
                Document.business_key.ilike(pattern),
                DocumentPayload.passenger_name.ilike(pattern),
                DocumentPayload.ticket_number.ilike(pattern),
                DocumentPayload.exchange_ticket_number.ilike(pattern),
                DocumentPayload.pnr.ilike(pattern),
                DocumentPayload.mom_number.ilike(pattern),
                DocumentPayload.payment_number.ilike(pattern),
                DocumentPayload.payment_purpose.ilike(pattern),
                DocumentPayload.client_name.ilike(pattern),
            )
        )

    hidden_clause = or_(state_alias.is_hidden.is_(None), state_alias.is_hidden.is_(False))
    if view == "active":
        stmt = stmt.where(Document.status.in_(["in_progress", "error"])).where(hidden_clause)
    elif view == "errors":
        stmt = stmt.where(Document.status == "error").where(hidden_clause)
    elif view == "success":
        stmt = stmt.where(Document.status == "success").where(hidden_clause)
    elif view == "hidden":
        stmt = stmt.where(state_alias.is_hidden.is_(True))
    elif view == "all":
        pass
    else:
        stmt = stmt.where(Document.status.in_(["in_progress", "error"])).where(hidden_clause)

    rows = db.execute(stmt).all()

    counters = Counter()
    for document, _, state in rows:
        counters[document.status] += 1
        if state and state.is_hidden:
            counters["hidden"] += 1

    return {"rows": rows, "counters": counters}


def load_document_with_context(db: Session, document_id: str) -> dict[str, object] | None:
    document = db.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(
            selectinload(Document.payload),
            selectinload(Document.events),
            selectinload(Document.outgoing_links),
            selectinload(Document.incoming_links),
            selectinload(Document.user_states),
        )
    )
    if not document:
        return None

    related_links = db.scalars(
        select(DocumentLink).where(
            or_(
                DocumentLink.from_document_id == document.id,
                DocumentLink.to_document_id == document.id,
            )
        )
    ).all()
    related_document_ids = {
        linked_id
        for link in related_links
        for linked_id in (link.from_document_id, link.to_document_id)
        if linked_id != document.id
    }

    related_documents = []
    if related_document_ids:
        related_documents = db.scalars(
            select(Document)
            .where(Document.id.in_(related_document_ids))
            .options(
                selectinload(Document.payload),
                selectinload(Document.events),
                selectinload(Document.outgoing_links),
                selectinload(Document.incoming_links),
                selectinload(Document.user_states),
            )
        ).all()

    related_by_id = {item.id: item for item in related_documents}
    root_ticket = document
    if document.doc_type == "realization":
        incoming_ticket_link = next((link for link in related_links if link.link_type == "ticket_to_realization" and link.to_document_id == document.id), None)
        if incoming_ticket_link and incoming_ticket_link.from_document_id in related_by_id:
            root_ticket = related_by_id[incoming_ticket_link.from_document_id]

    linked_realizations = []
    if root_ticket.doc_type == "ticket":
        root_links = db.scalars(
            select(DocumentLink).where(
                DocumentLink.from_document_id == root_ticket.id,
                DocumentLink.link_type == "ticket_to_realization",
            )
        ).all()
        realization_ids = [link.to_document_id for link in root_links]
        if realization_ids:
            linked_realizations = db.scalars(
                select(Document)
                .where(Document.id.in_(realization_ids))
                .options(selectinload(Document.payload), selectinload(Document.events))
            ).all()

    linked_payments = []
    if linked_realizations:
        realization_ids = [item.id for item in linked_realizations]
        payment_links = db.scalars(
            select(DocumentLink).where(
                DocumentLink.to_document_id.in_(realization_ids),
                DocumentLink.link_type == "payment_to_realization",
            )
        ).all()
        payment_ids = [link.from_document_id for link in payment_links]
        if payment_ids:
            linked_payments = db.scalars(
                select(Document)
                .where(Document.id.in_(payment_ids))
                .options(selectinload(Document.payload), selectinload(Document.events))
            ).all()

    detail_steps = _ticket_case_steps(root_ticket) if root_ticket.doc_type == "ticket" else []
    return {
        "document": document,
        "root_ticket": root_ticket,
        "linked_realizations": sorted(linked_realizations, key=lambda item: item.occurred_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True),
        "linked_payments": sorted(linked_payments, key=lambda item: item.occurred_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True),
        "steps": detail_steps,
    }
