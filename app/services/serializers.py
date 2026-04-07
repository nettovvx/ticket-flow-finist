from app.models.document import Document, DocumentEvent, DocumentPayload, DocumentUserState


def serialize_state(state: DocumentUserState | None) -> dict | None:
    if not state:
        return None
    return {
        "is_hidden": state.is_hidden,
        "is_viewed": state.is_viewed,
        "hidden_reason": state.hidden_reason,
        "viewed_at": state.viewed_at,
        "hidden_at": state.hidden_at,
    }


def serialize_payload(payload: DocumentPayload | None) -> dict | None:
    if not payload:
        return None
    return {
        "passenger_name": payload.passenger_name,
        "ticket_number": payload.ticket_number,
        "exchange_ticket_number": payload.exchange_ticket_number,
        "pnr": payload.pnr,
        "mom_number": payload.mom_number,
        "payment_number": payload.payment_number,
        "payment_purpose": payload.payment_purpose,
        "client_name": payload.client_name,
        "amount": payload.amount,
        "currency": payload.currency,
        "direction": payload.direction,
        "document_date": payload.document_date,
        "route": payload.route,
        "extra_json": payload.extra_json,
    }


def serialize_event(event: DocumentEvent) -> dict:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "step_code": event.step_code,
        "status": event.status,
        "message": event.message,
        "occurred_at": event.occurred_at,
        "duration_ms": event.duration_ms,
        "meta_json": event.meta_json,
    }


def serialize_document(document: Document, *, include_events: bool = False) -> dict:
    data = {
        "id": document.id,
        "doc_type": document.doc_type,
        "flow_group": document.flow_group,
        "source_system": document.source_system,
        "status": document.status,
        "current_step": document.current_step,
        "title": document.title,
        "file_name": document.file_name,
        "file_path": document.file_path,
        "file_size": document.file_size,
        "business_key": document.business_key,
        "error_message": document.error_message,
        "occurred_at": document.occurred_at,
        "completed_at": document.completed_at,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "payload": serialize_payload(document.payload),
        "events": None,
    }
    if include_events:
        data["events"] = [serialize_event(event) for event in sorted(document.events, key=lambda item: item.occurred_at or item.created_at)]
    return data


def serialize_ticket_listing(raw_listing: dict[str, object]) -> dict[str, object]:
    entries = []
    for item in raw_listing["entries"]:
        if item["entry_type"] == "ticket_case":
            case = item["ticket_case"]
            entries.append(
                {
                    "entry_type": "ticket_case",
                    "entry_id": item["entry_id"],
                    "ticket_case": {
                        "ticket": serialize_document(case["ticket"]),
                        "ticket_state": serialize_state(case["ticket_state"]),
                        "realizations": [serialize_document(realization) for realization in case["realizations"]],
                        "group_status": case["group_status"],
                        "steps": case["steps"],
                        "last_activity_at": case["last_activity_at"],
                    },
                    "orphan_realization": None,
                }
            )
        else:
            orphan = item["orphan_realization"]
            entries.append(
                {
                    "entry_type": "orphan_realization",
                    "entry_id": item["entry_id"],
                    "ticket_case": None,
                    "orphan_realization": {
                        "realization": serialize_document(orphan["realization"]),
                        "state": serialize_state(orphan["state"]),
                    },
                }
            )

    ticket_cases = []
    for case in raw_listing["ticket_cases"]:
        ticket_cases.append(
            {
                "ticket": serialize_document(case["ticket"]),
                "ticket_state": serialize_state(case["ticket_state"]),
                "realizations": [serialize_document(item) for item in case["realizations"]],
                "group_status": case["group_status"],
                "steps": case["steps"],
                "last_activity_at": case["last_activity_at"],
            }
        )

    orphan_realizations = []
    for item in raw_listing["orphan_realizations"]:
        orphan_realizations.append(
            {
                "realization": serialize_document(item["realization"]),
                "state": serialize_state(item["state"]),
            }
        )

    counters = {key: int(value) for key, value in dict(raw_listing["counters"]).items()}
    return {
        "entries": entries,
        "ticket_cases": ticket_cases,
        "orphan_realizations": orphan_realizations,
        "counters": counters,
        "total_count": raw_listing["total_count"],
        "filtered_count": raw_listing["filtered_count"],
        "offset": raw_listing["offset"],
        "limit": raw_listing["limit"],
        "has_more": raw_listing["has_more"],
    }


def serialize_documents_listing(raw_listing: dict[str, object]) -> dict[str, object]:
    rows = []
    for document, _, state in raw_listing["rows"]:
        rows.append(
            {
                "document": serialize_document(document),
                "state": serialize_state(state),
            }
        )

    counters = {key: int(value) for key, value in dict(raw_listing["counters"]).items()}
    return {
        "rows": rows,
        "counters": counters,
        "total_count": raw_listing["total_count"],
        "filtered_count": raw_listing["filtered_count"],
        "offset": raw_listing["offset"],
        "limit": raw_listing["limit"],
        "has_more": raw_listing["has_more"],
    }


def serialize_document_detail(context: dict[str, object]) -> dict[str, object]:
    return {
        "document": serialize_document(context["document"], include_events=True),
        "root_ticket": serialize_document(context["root_ticket"]),
        "root_ticket_state": serialize_state(context.get("root_ticket_state")),
        "linked_realizations": [serialize_document(item) for item in context["linked_realizations"]],
        "linked_payments": [serialize_document(item) for item in context["linked_payments"]],
        "steps": context["steps"],
    }
