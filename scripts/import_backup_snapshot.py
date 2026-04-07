from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal
from app.models.document import Document, DocumentEvent, DocumentLink, DocumentPayload


MOM_REF_PATTERN = re.compile(r"[MМ][OО][MМ]-\d{7}")
REALIZATION_NS = {"x": "http://www.gridnine.com/export/xml"}


def parse_ticket_datetime(date_text: str | None, time_text: str | None) -> datetime | None:
    if not date_text:
        return None
    time_value = time_text or "0000"
    try:
        return datetime.strptime(f"{date_text}{time_value}", "%d%m%Y%H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_mom_ref(value: str | None) -> str | None:
    if not value:
        return None
    match = MOM_REF_PATTERN.search(value)
    if not match:
        return None
    normalized = match.group(0).replace("М", "M").replace("О", "O")
    return normalized


def find_or_create_document(session, *, doc_type: str, flow_group: str, file_name: str, source_system: str) -> Document:
    existing = session.scalar(
        select(Document).where(
            Document.doc_type == doc_type,
            Document.file_name == file_name,
            Document.source_system == source_system,
        )
    )
    if existing:
        return existing
    document = Document(
        doc_type=doc_type,
        flow_group=flow_group,
        source_system=source_system,
        status="in_progress",
        file_name=file_name,
    )
    session.add(document)
    session.flush()
    return document


def upsert_payload(document: Document, **fields) -> DocumentPayload:
    payload = document.payload or DocumentPayload(document_id=document.id)
    for key, value in fields.items():
        setattr(payload, key, value)
    document.payload = payload
    return payload


def add_event(document: Document, *, step_code: str, status: str, message: str, occurred_at: datetime | None) -> None:
    document.events.append(
        DocumentEvent(
            event_type="imported_snapshot",
            step_code=step_code,
            status=status,
            message=message,
            occurred_at=occurred_at,
        )
    )


def import_tickets(session, tickets_dir: Path) -> dict[str, list[Document]]:
    pnr_to_docs: dict[str, list[Document]] = {}
    for file in sorted(tickets_dir.glob("*.xml")):
        root = ET.fromstring(file.read_text(encoding="utf-8"))
        ticket_node = root.find("TICKET")
        if ticket_node is None:
            continue

        deal_date = ticket_node.findtext("DEALDATE")
        deal_time = ticket_node.findtext("DEALTIME")
        occurred_at = parse_ticket_datetime(deal_date, deal_time)
        pnr = ticket_node.findtext("PNR_LAT") or ticket_node.findtext("PNR")
        bsonum = ticket_node.findtext("BSONUM")
        ex_bsonum = ticket_node.findtext("EX_BSONUM")
        passenger = ticket_node.findtext("FIO")
        op_type = ticket_node.findtext("OPTYPE")
        trans_type = ticket_node.findtext("TRANS_TYPE")
        fare_text = ticket_node.findtext("FARE")
        fare_amount = float(fare_text) if fare_text else None

        document = find_or_create_document(
            session,
            doc_type="ticket",
            flow_group="tickets",
            file_name=file.name,
            source_system="sirena",
        )
        document.file_path = str(file)
        document.file_size = file.stat().st_size
        document.occurred_at = occurred_at
        document.title = passenger or bsonum or file.name
        document.business_key = pnr or bsonum
        document.current_step = "ticket_copied_to_ftp"
        document.status = "in_progress"

        upsert_payload(
            document,
            passenger_name=passenger,
            ticket_number=bsonum,
            exchange_ticket_number=ex_bsonum,
            pnr=pnr,
            amount=fare_amount,
            currency=ticket_node.findtext("CURRENCY"),
            direction=op_type,
            document_date=occurred_at,
            extra_json={"op_type": op_type, "trans_type": trans_type},
        )

        add_event(
            document,
            step_code="sirena_received",
            status="success",
            message="Билет найден в снапшоте sirena-olt-client",
            occurred_at=occurred_at,
        )
        add_event(
            document,
            step_code="ticket_copied_to_ftp",
            status="success",
            message="В бэкапе билет уже находится в цепочке FTP",
            occurred_at=occurred_at,
        )

        if pnr:
            pnr_to_docs.setdefault(pnr, []).append(document)
    return pnr_to_docs


def import_realizations(session, realization_dir: Path) -> tuple[dict[str, Document], dict[str, list[Document]]]:
    mom_to_docs: dict[str, Document] = {}
    pnr_to_realizations: dict[str, list[Document]] = {}
    for file in sorted(realization_dir.glob("*.xml")):
        root = ET.fromstring(file.read_text(encoding="utf-8"))
        number = root.attrib.get("number")
        occurred_at = parse_iso_datetime(root.attrib.get("time"))
        deleted = root.attrib.get("deleted") == "true"

        document = find_or_create_document(
            session,
            doc_type="realization",
            flow_group="tickets",
            file_name=file.name,
            source_system="mom",
        )
        document.file_path = str(file)
        document.file_size = file.stat().st_size
        document.occurred_at = occurred_at
        document.title = number or file.name
        document.business_key = number
        document.current_step = "realization_received_from_mom"
        document.status = "error" if deleted else "success"
        document.error_message = "MOM пометил реализацию как deleted" if deleted else None

        customer = root.find("x:customer/x:shortName/x:item[@locale='ru']", REALIZATION_NS)
        currency = root.find("x:currency", REALIZATION_NS)
        reservations = {node.attrib.get("number") for node in root.findall(".//x:reservation", REALIZATION_NS) if node.attrib.get("number")}
        products = [node.attrib.get("number") for node in root.findall(".//x:product", REALIZATION_NS) if node.attrib.get("number")]

        upsert_payload(
            document,
            mom_number=number,
            client_name=customer.attrib.get("value") if customer is not None else None,
            currency=currency.attrib.get("code") if currency is not None else None,
            pnr=sorted(reservations)[0] if reservations else None,
            document_date=parse_iso_datetime(root.attrib.get("date")),
            extra_json={"deleted": deleted, "pnrs": sorted(reservations), "product_numbers": products},
        )

        add_event(
            document,
            step_code="realization_received_from_mom",
            status="error" if deleted else "success",
            message="Реализация найдена в снапшоте MOM",
            occurred_at=occurred_at,
        )

        if number:
            mom_to_docs[number] = document
        for pnr in reservations:
            pnr_to_realizations.setdefault(pnr, []).append(document)
    return mom_to_docs, pnr_to_realizations


def import_payments(session, payments_file: Path, mom_to_docs: dict[str, Document]) -> None:
    root = ET.fromstring(payments_file.read_text(encoding="utf-8"))
    data = None
    for child in root:
        if child.tag.endswith("Data"):
            data = child
            break
    if data is None:
        return

    for node in data:
        if node.tag not in {"DocumentObject.ПоступлениеНаРасчетныйСчет", "DocumentObject.СписаниеСРасчетногоСчета"}:
            continue
        direction = "incoming" if "Поступление" in node.tag else "outgoing"
        number = node.findtext("Number")
        occurred_at = parse_iso_datetime(node.findtext("Date"))
        amount_text = node.findtext("СуммаДокумента")
        purpose = node.findtext("НазначениеПлатежа")
        mom_ref = normalize_mom_ref(purpose)
        amount = float(amount_text.replace(",", ".")) if amount_text else None

        document = find_or_create_document(
            session,
            doc_type="payment",
            flow_group="payments",
            file_name=f"{payments_file.name}:{number}",
            source_system="1c",
        )
        document.file_path = str(payments_file)
        document.file_size = payments_file.stat().st_size
        document.occurred_at = occurred_at
        document.title = f"{number or 'Без номера'} / {direction}"
        document.business_key = number
        document.current_step = "payment_received_from_1c" if direction == "incoming" else "payment_loaded_from_bank"
        document.status = "success" if mom_ref else "in_progress"

        upsert_payload(
            document,
            payment_number=number,
            payment_purpose=purpose,
            mom_number=mom_ref,
            amount=amount,
            direction=direction,
            document_date=occurred_at,
            extra_json={"operation_type": node.findtext("ВидОперации")},
        )

        add_event(
            document,
            step_code=document.current_step,
            status="success",
            message="Платежка импортирована из снапшота 1С",
            occurred_at=occurred_at,
        )

        if mom_ref and mom_ref in mom_to_docs:
            session.add(
                DocumentLink(
                    from_document_id=document.id,
                    to_document_id=mom_to_docs[mom_ref].id,
                    link_type="payment_to_realization",
                    confidence="high",
                    reason="Связь по номеру MOM в назначении платежа",
                )
            )


def link_tickets_to_realizations(session, pnr_to_tickets: dict[str, list[Document]], pnr_to_realizations: dict[str, list[Document]]) -> None:
    for pnr, ticket_documents in pnr_to_tickets.items():
        realizations = pnr_to_realizations.get(pnr, [])
        if realizations:
            for ticket in ticket_documents:
                ticket.status = "success"
                ticket.current_step = "realization_received_from_mom"
                add_event(
                    ticket,
                    step_code="realization_received_from_mom",
                    status="success",
                    message="Найдена связанная реализация по PNR",
                    occurred_at=max((r.occurred_at for r in realizations if r.occurred_at), default=ticket.occurred_at),
                )
                for realization in realizations:
                    session.add(
                        DocumentLink(
                            from_document_id=ticket.id,
                            to_document_id=realization.id,
                            link_type="ticket_to_realization",
                            confidence="high",
                            reason="Связь по PNR",
                        )
                    )
        else:
            for ticket in ticket_documents:
                ticket.status = "in_progress"
                add_event(
                    ticket,
                    step_code="ticket_seen_by_mom",
                    status="pending",
                    message="Связанная реализация в снапшоте не найдена",
                    occurred_at=ticket.occurred_at,
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", nargs="?", default="2025-11-13")
    args = parser.parse_args()

    snapshot_dir = Path(args.snapshot)
    if not snapshot_dir.exists():
        raise SystemExit(f"Snapshot not found: {snapshot_dir}")

    with SessionLocal() as session:
        pnr_to_tickets = import_tickets(session, snapshot_dir / "tickets")
        mom_to_docs, pnr_to_realizations = import_realizations(session, snapshot_dir / "realization")
        import_payments(session, snapshot_dir / "payments" / "MOM.xml", mom_to_docs)
        link_tickets_to_realizations(session, pnr_to_tickets, pnr_to_realizations)
        session.commit()

    print(f"Imported snapshot from {snapshot_dir}")


if __name__ == "__main__":
    main()
