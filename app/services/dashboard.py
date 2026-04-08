from collections import Counter
from datetime import datetime, time, timezone
from pathlib import Path

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.core.config import get_settings
from app.models.archive import ArchivedDocument, ArchivedDocumentPayload
from app.models.archive import ArchivedDocumentEvent
from app.models.document import Document, DocumentEvent, DocumentLink, DocumentPayload, DocumentUserState
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp_future_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    now = _utc_now()
    return value if value <= now else now


def _document_sort_time(document: Document) -> datetime:
    return _clamp_future_datetime(document.occurred_at) or _clamp_future_datetime(document.created_at) or datetime.min.replace(tzinfo=timezone.utc)


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


def _event_status_any(document: Document, step_codes: list[str]) -> str:
    statuses = [_event_status(document, code) for code in step_codes]
    if "error" in statuses:
        return "error"
    if "success" in statuses:
        return "success"
    if "in_progress" in statuses:
        return "in_progress"
    return "pending"


def _event_occurred_at(document: Document, step_code: str) -> datetime | None:
    timestamps = [_clamp_future_datetime(event.occurred_at) for event in document.events if event.step_code == step_code and event.occurred_at]
    timestamps = [timestamp for timestamp in timestamps if timestamp]
    if not timestamps:
        return None
    return max(timestamps)


def _event_occurred_at_any(document: Document, step_codes: list[str]) -> datetime | None:
    timestamps = [_event_occurred_at(document, code) for code in step_codes]
    timestamps = [timestamp for timestamp in timestamps if timestamp]
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
            "code": "ticket_issued_in_sirena",
            "label": "Билет выписан (Sirena Online Ticket)",
            "status": _event_status_any(ticket, ["ticket_issued_in_sirena", "sirena_received"]),
            "occurred_at": _event_occurred_at_any(ticket, ["ticket_issued_in_sirena", "sirena_received"]),
        },
        {
            "code": "ticket_copied_to_ftp",
            "label": "Билет перемещен на FTP",
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
        {
            "code": "realization_accepted_by_1c",
            "label": "1С принял реализацию",
            "status": _event_status(ticket, "realization_accepted_by_1c"),
            "occurred_at": _event_occurred_at(ticket, "realization_accepted_by_1c"),
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

    timestamps = [_clamp_future_datetime(document.occurred_at) for document in documents if document.occurred_at]
    timestamps = [timestamp for timestamp in timestamps if timestamp]
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
    limit: int = 50,
    offset: int = 0,
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

    all_ticket_cases: list[dict[str, object]] = []
    for ticket in ticket_by_id.values():
        related_realizations = []
        for link in ticket.outgoing_links:
            if link.link_type != "ticket_to_realization":
                continue
            realization = realization_by_id.get(link.to_document_id)
            if realization:
                related_realizations.append(realization)

        related_realizations.sort(key=lambda item: item.occurred_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        group_documents = [ticket, *related_realizations]
        group_status = _group_status(ticket, related_realizations)
        state = _get_user_state(ticket, user.id)

        all_ticket_cases.append(
            {
                "ticket": ticket,
                "ticket_state": state,
                "realizations": related_realizations,
                "group_status": group_status,
                "steps": _ticket_case_steps(ticket),
                "last_activity_at": max((_document_sort_time(document) for document in group_documents), default=_document_sort_time(ticket)),
            }
        )

    all_ticket_cases.sort(key=lambda item: item["last_activity_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    counters = Counter()
    for case in all_ticket_cases:
        counters[case["group_status"]] += 1
        if case["ticket_state"] and case["ticket_state"].is_hidden:
            counters["hidden"] += 1

    filtered_entries: list[dict[str, object]] = []
    for case in all_ticket_cases:
        group_documents = [case["ticket"], *case["realizations"]]
        if not _matches_status_filter(case["group_status"], status_filter):
            continue
        if not _matches_view(case["group_status"], case["ticket_state"], view):
            continue
        if not _matches_date_range(group_documents, date_from, date_to):
            continue
        if search and not any(_document_matches_search(document, search) for document in group_documents):
            continue
        filtered_entries.append(
            {
                "entry_type": "ticket_case",
                "entry_id": case["ticket"].id,
                "sort_time": case["last_activity_at"],
                "ticket_case": case,
            }
        )

    filtered_entries.sort(key=lambda item: item["sort_time"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    page_entries = filtered_entries[offset : offset + limit]
    ticket_cases = [item["ticket_case"] for item in page_entries if item["entry_type"] == "ticket_case"]
    orphan_realizations: list[dict[str, object]] = []

    return {
        "entries": page_entries,
        "ticket_cases": ticket_cases,
        "orphan_realizations": orphan_realizations,
        "counters": counters,
        "total_count": len(all_ticket_cases),
        "filtered_count": len(filtered_entries),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page_entries) < len(filtered_entries),
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
    offset: int = 0,
) -> dict[str, object]:
    state_alias = aliased(DocumentUserState)
    base_stmt = (
        select(Document, DocumentPayload, state_alias)
        .join(DocumentPayload, DocumentPayload.document_id == Document.id, isouter=True)
        .join(
            state_alias,
            and_(state_alias.document_id == Document.id, state_alias.user_id == user.id),
            isouter=True,
        )
        .where(Document.flow_group == flow_group)
    )

    counter_rows = db.execute(base_stmt.with_only_columns(Document.status, state_alias.is_hidden)).all()
    counters = Counter()
    for status, is_hidden in counter_rows:
        counters[status] += 1
        if is_hidden:
            counters["hidden"] += 1

    stmt = base_stmt
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

    filtered_count = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(
        stmt.order_by(Document.occurred_at.desc().nullslast(), Document.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "rows": rows,
        "counters": counters,
        "total_count": len(counter_rows),
        "filtered_count": int(filtered_count),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < int(filtered_count),
    }


def build_archived_document_listing(
    db: Session,
    *,
    search: str | None = None,
    view: str = "all",
    status_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    flow_group: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    base_stmt = (
        select(ArchivedDocument, ArchivedDocumentPayload)
        .join(ArchivedDocumentPayload, ArchivedDocumentPayload.document_id == ArchivedDocument.id, isouter=True)
    )
    if flow_group:
        base_stmt = base_stmt.where(ArchivedDocument.flow_group == flow_group)

    counter_rows = db.execute(base_stmt.with_only_columns(ArchivedDocument.status)).all()
    counters = Counter()
    for status, in counter_rows:
        counters[status] += 1

    stmt = base_stmt
    if status_filter:
        stmt = stmt.where(ArchivedDocument.status == status_filter)
    elif view == "errors":
        stmt = stmt.where(ArchivedDocument.status == "error")
    elif view == "success":
        stmt = stmt.where(ArchivedDocument.status == "success")
    elif view == "active":
        stmt = stmt.where(ArchivedDocument.status.in_(["in_progress", "error"]))

    if date_from:
        parsed_from = _parse_date_start(date_from)
        if parsed_from:
            stmt = stmt.where(ArchivedDocument.occurred_at >= parsed_from)
    if date_to:
        parsed_to = _parse_date_end(date_to)
        if parsed_to:
            stmt = stmt.where(ArchivedDocument.occurred_at <= parsed_to)

    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                ArchivedDocument.title.ilike(pattern),
                ArchivedDocument.file_name.ilike(pattern),
                ArchivedDocument.business_key.ilike(pattern),
                ArchivedDocumentPayload.passenger_name.ilike(pattern),
                ArchivedDocumentPayload.ticket_number.ilike(pattern),
                ArchivedDocumentPayload.exchange_ticket_number.ilike(pattern),
                ArchivedDocumentPayload.pnr.ilike(pattern),
                ArchivedDocumentPayload.mom_number.ilike(pattern),
                ArchivedDocumentPayload.payment_number.ilike(pattern),
                ArchivedDocumentPayload.payment_purpose.ilike(pattern),
                ArchivedDocumentPayload.client_name.ilike(pattern),
            )
        )

    filtered_count = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(
        stmt.order_by(ArchivedDocument.archived_at.desc(), ArchivedDocument.occurred_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "rows": rows,
        "counters": counters,
        "total_count": len(counter_rows),
        "filtered_count": int(filtered_count),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < int(filtered_count),
    }


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
        "linked_realizations": sorted(linked_realizations, key=_document_sort_time, reverse=True),
        "linked_payments": sorted(linked_payments, key=_document_sort_time, reverse=True),
        "steps": detail_steps,
    }


FOLDER_QUEUE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("ticket_inbox", "Sirena: билеты (вход)", "ticket_inbox_dir"),
    ("ticket_ftp_in", "FTP: билеты (вход)", "ftp_tickets_dir"),
    ("ticket_ftp_processed", "FTP: билеты (processed)", "ftp_tickets_processed_dir"),
    ("ticket_ftp_error", "FTP: билеты (error)", "ftp_tickets_error_dir"),
    ("realization_ftp_in", "FTP: реализации (вход)", "ftp_realisations_dir"),
    ("realization_1c_target", "1С: реализации (inbox)", "onec_realisations_target_dir"),
    ("realization_1c_archive", "1С: реализации (archive)", "onec_realisations_archive_dir"),
    ("realization_1c_bad", "1С: реализации (bad)", "onec_realisations_bad_dir"),
    ("realization_1c_del_bad", "1С: реализации (del_bad)", "onec_realisations_del_bad_dir"),
    ("realization_1c_empty", "1С: реализации (empty)", "onec_realisations_empty_dir"),
    ("payment_1c_in", "1С: платежки (вход)", "onec_payments_source_dir"),
    ("payment_ftp_in", "FTP: платежки (вход)", "ftp_payments_dir"),
    ("payment_ftp_processed", "FTP: платежки (processed)", "ftp_payments_processed_dir"),
    ("payment_ftp_error", "FTP: платежки (error)", "ftp_payments_error_dir"),
)

DAILY_METRIC_SPECS: tuple[tuple[str, str, str], ...] = (
    ("tickets_created", "Билеты: появились в папке", "ticket_issued_in_sirena"),
    ("tickets_sent_to_ftp", "Билеты: перемещены на FTP", "ticket_copied_to_ftp"),
    ("tickets_mom_processed", "Билеты: MOM обработал", "ticket_seen_by_mom"),
    ("tickets_realization_received", "Билеты: получены реализации", "realization_received_from_mom"),
    ("tickets_realization_sent_1c", "Билеты: реализации отправлены в 1С", "realization_copied_to_smb"),
    ("tickets_final_1c", "Билеты: финал 1С", "realization_accepted_by_1c"),
    ("payments_created", "Платежки: появились в папке", "payment_received_from_1c"),
    ("payments_sent_to_ftp", "Платежки: перемещены на FTP", "payment_copied_to_ftp"),
    ("payments_mom_processed", "Платежки: MOM обработал", "payment_seen_by_mom"),
)


def _count_xml_files(folder: Path) -> tuple[int, bool, str | None]:
    try:
        if not folder.exists() or not folder.is_dir():
            return 0, False, None
        total = sum(1 for item in folder.iterdir() if item.is_file() and item.suffix.lower() == ".xml")
        return total, True, None
    except Exception as exc:
        return 0, False, str(exc)


def _collect_event_counts(db: Session, start_utc: datetime, end_utc: datetime) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for model in (DocumentEvent, ArchivedDocumentEvent):
        rows = db.execute(
            select(
                model.step_code,
                model.status,
                func.count(func.distinct(model.document_id)),
            )
            .where(
                model.occurred_at >= start_utc,
                model.occurred_at <= end_utc,
            )
            .group_by(model.step_code, model.status)
        ).all()
        for step_code, status, value in rows:
            key = (step_code, status)
            counts[key] = counts.get(key, 0) + int(value or 0)
    return counts


def build_operations_overview(db: Session) -> dict[str, object]:
    settings = get_settings()
    generated_at = _utc_now()
    day_start = generated_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = generated_at.replace(hour=23, minute=59, second=59, microsecond=999999)

    folders: list[dict[str, object]] = []
    total_xml = 0
    for key, label, attr_name in FOLDER_QUEUE_SPECS:
        path_value = Path(getattr(settings, attr_name))
        xml_count, exists, error = _count_xml_files(path_value)
        total_xml += xml_count
        folders.append(
            {
                "key": key,
                "label": label,
                "path": str(path_value),
                "xml_count": xml_count,
                "exists": exists,
                "error": error,
            }
        )

    event_counts = _collect_event_counts(db, day_start, day_end)
    daily_metrics: list[dict[str, object]] = []
    total_success = 0
    total_error = 0
    for code, label, step_code in DAILY_METRIC_SPECS:
        success_count = int(event_counts.get((step_code, "success"), 0))
        error_count = int(event_counts.get((step_code, "error"), 0))
        total_success += success_count
        total_error += error_count
        daily_metrics.append(
            {
                "code": code,
                "label": label,
                "success": success_count,
                "error": error_count,
                "total": success_count + error_count,
            }
        )

    return {
        "generated_at": generated_at,
        "folder_xml_total": total_xml,
        "folders": folders,
        "daily_metrics": daily_metrics,
        "daily_totals": {
            "success": total_success,
            "error": total_error,
            "events": total_success + total_error,
        },
    }
